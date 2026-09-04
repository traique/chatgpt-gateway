from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse

DEFAULT_PUBLIC_MODEL = "chatgpt-gpt-5.6"
WEB_SEARCH_TOOL_TYPES = frozenset({"web_search", "web_search_preview"})


def _convert_tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    tool_type = tool.get("type")
    if tool_type in WEB_SEARCH_TOOL_TYPES:
        converted = {key: value for key, value in tool.items() if key != "type"}
        return {"type": "web_search", **converted}
    if tool_type == "function":
        function = tool.get("function")
        if not isinstance(function, dict):
            return None
        converted: dict[str, Any] = {
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description"),
            "parameters": function.get("parameters", {}),
        }
        if "strict" in function:
            converted["strict"] = function["strict"]
        return converted
    return None


def _convert_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tools = payload.get("tools")
    converted: list[dict[str, Any]] = []
    if isinstance(tools, list):
        for raw_tool in tools:
            if not isinstance(raw_tool, dict):
                continue
            tool = _convert_tool(raw_tool)
            if tool is not None:
                converted.append(tool)
    if payload.get("web_search_options") is not None and not any(tool.get("type") == "web_search" for tool in converted):
        options = payload.get("web_search_options")
        converted.append({"type": "web_search", **options} if isinstance(options, dict) else {"type": "web_search"})
    return converted


def build_openai_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from faable import app as runtime

    upstream = runtime.build_chat_completions_payload(payload)
    for source_key in ("temperature", "top_p"):
        value = payload.get(source_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            upstream[source_key] = value

    max_tokens = payload.get("max_tokens")
    if not isinstance(max_tokens, int):
        max_tokens = payload.get("max_completion_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        upstream["max_output_tokens"] = max_tokens

    tools = _convert_tools(payload)
    if tools:
        upstream["tools"] = tools

    reasoning_effort = payload.get("reasoning_effort")
    if isinstance(reasoning_effort, str) and reasoning_effort:
        upstream["reasoning"] = {"effort": reasoning_effort}

    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, (str, dict)):
        upstream["tool_choice"] = tool_choice

    response_format = payload.get("response_format")
    if isinstance(response_format, dict):
        format_type = response_format.get("type")
        if format_type == "json_object":
            upstream["text"] = {"format": {"type": "json_object"}}
        elif format_type == "json_schema" and isinstance(response_format.get("json_schema"), dict):
            schema = response_format["json_schema"]
            upstream["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema.get("name", "response"),
                    "schema": schema.get("schema", {}),
                    "strict": schema.get("strict", True),
                }
            }
    return upstream


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _output_item(event: dict[str, Any]) -> dict[str, Any] | None:
    item = event.get("item")
    return item if isinstance(item, dict) else None


def iter_openai_chat_stream(response: Any, requested_model: str) -> Iterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    first_delta = True
    function_arguments: dict[str, str] = {}
    function_metadata: dict[str, dict[str, Any]] = {}
    try:
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            line = line.strip()
            if not line.startswith("data:"):
                continue
            raw_event = line[5:].strip()
            if not raw_event or raw_event == "[DONE]":
                continue
            try:
                event = json.loads(raw_event)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "response.output_text.delta":
                delta = str(event.get("delta") or "")
                if not delta:
                    continue
                content_delta: dict[str, Any] = {"content": delta}
                if first_delta:
                    content_delta["role"] = "assistant"
                    first_delta = False
                yield _sse({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": content_delta, "finish_reason": None}],
                })
                continue
            if event_type == "response.function_call_arguments.delta":
                call_id = str(event.get("item_id") or event.get("call_id") or "0")
                delta = str(event.get("delta") or "")
                function_arguments[call_id] = function_arguments.get(call_id, "") + delta
                role_delta = {"role": "assistant"} if first_delta else {}
                first_delta = False
                yield _sse({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": requested_model,
                    "choices": [{
                        "index": 0,
                        "delta": {
                            **role_delta,
                            "tool_calls": [{
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {"arguments": delta},
                            }],
                        },
                        "finish_reason": None,
                    }],
                })
                continue
            if event_type == "response.output_item.done":
                item = _output_item(event)
                if not item or item.get("type") != "function_call":
                    continue
                call_id = str(item.get("call_id") or item.get("id") or "0")
                function = item.get("name")
                if isinstance(function, str):
                    function_metadata[call_id] = {"name": function}
                function_metadata.setdefault(call_id, {})["arguments"] = str(item.get("arguments") or function_arguments.get(call_id, ""))
                continue
            if event_type in {"response.error", "response.failed"}:
                yield _sse({"error": event.get("error") or event.get("response") or "ChatGPT upstream failed."})
                break
            if event_type == "response.completed":
                if function_metadata:
                    tool_calls = [{
                        "index": index,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": metadata.get("name", ""),
                            "arguments": metadata.get("arguments", ""),
                        },
                    } for index, (call_id, metadata) in enumerate(function_metadata.items())]
                    yield _sse({
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": requested_model,
                        "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": "tool_calls"}],
                    })
                else:
                    yield _sse({
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": requested_model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    })
                break
    finally:
        try:
            response.close()
        except Exception:
            pass
    yield "data: [DONE]\n\n"


def _read_response_events(response: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            line = line.strip()
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    finally:
        try:
            response.close()
        except Exception:
            pass
    return events


def _extract_message_content(item: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    text_parts: list[str] = []
    annotations: list[dict[str, Any]] = []
    content = item.get("content")
    if not isinstance(content, list):
        return text_parts, annotations
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
        part_annotations = part.get("annotations")
        if isinstance(part_annotations, list):
            annotations.extend(annotation for annotation in part_annotations if isinstance(annotation, dict))
    return text_parts, annotations


def _aggregate_with_tools(response: Any, requested_model: str, provider_model: str) -> dict[str, Any]:
    events = _read_response_events(response)
    text_parts: list[str] = []
    annotations: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    terminal_error: str | None = None
    for event in events:
        event_type = event.get("type")
        if event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
            break
        if event_type == "response.output_text.delta":
            text_parts.append(str(event.get("delta") or ""))
            continue
        if event_type != "response.output_item.done":
            continue
        item = _output_item(event)
        if not item:
            continue
        if item.get("type") == "function_call":
            tool_calls.append({
                "id": str(item.get("call_id") or item.get("id") or uuid.uuid4().hex),
                "type": "function",
                "function": {
                    "name": str(item.get("name") or ""),
                    "arguments": str(item.get("arguments") or "{}"),
                },
            })
            continue
        if item.get("type") == "message":
            message_text, message_annotations = _extract_message_content(item)
            if not text_parts:
                text_parts.extend(message_text)
            annotations.extend(message_annotations)
    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts).strip() or None}
    if annotations:
        message["annotations"] = annotations
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "provider_model": provider_model,
    }


def _responses_input(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("input")
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [{"role": "user", "content": [{"type": "input_text", "text": value}]}]
    raise HTTPException(status_code=400, detail="input must be a string or array.")


def _merge_response_output(completed: dict[str, Any], output: list[dict[str, Any]], text_parts: list[str]) -> dict[str, Any]:
    merged = dict(completed)
    if not merged.get("output") and output:
        merged["output"] = output
    if text_parts and not merged.get("output_text"):
        merged["output_text"] = "".join(text_parts)
    return merged


def _aggregate_responses(response: Any, requested_model: str, provider_model: str) -> dict[str, Any]:
    events = _read_response_events(response)
    completed: dict[str, Any] | None = None
    output: list[dict[str, Any]] = []
    text_parts: list[str] = []
    annotations: list[dict[str, Any]] = []
    terminal_error: str | None = None
    for event in events:
        event_type = event.get("type")
        if event_type == "response.completed" and isinstance(event.get("response"), dict):
            completed = event["response"]
            continue
        if event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
            continue
        if event_type != "response.output_item.done":
            if event_type == "response.output_text.delta":
                text_parts.append(str(event.get("delta") or ""))
            continue
        item = _output_item(event)
        if not isinstance(item, dict):
            continue
        output.append(item)
        if item.get("type") == "message":
            message_text, message_annotations = _extract_message_content(item)
            text_parts.extend(message_text)
            annotations.extend(message_annotations)

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    if completed is not None:
        return _merge_response_output(completed, output, text_parts)

    text = "".join(text_parts)
    if not output and text:
        content: dict[str, Any] = {"type": "output_text", "text": text}
        if annotations:
            content["annotations"] = annotations
        output = [{
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "content": [content],
        }]
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": requested_model,
        "output": output,
        "output_text": text,
        "provider_model": provider_model,
    }


def _remove_route(runtime: Any, path: str) -> None:
    runtime.app.router.routes[:] = [route for route in runtime.app.router.routes if getattr(route, "path", None) != path]


def install(runtime: Any) -> None:
    _remove_route(runtime, "/v1/chat/completions")
    _remove_route(runtime, "/v1/responses")
    _remove_route(runtime, "/v1/images/generations")

    def chat_completions(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        upstream_payload = build_openai_chat_payload(payload)
        response = runtime.upstream_request(upstream_payload)
        requested_model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                iter_openai_chat_stream(response, requested_model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        return _aggregate_with_tools(response, requested_model, str(upstream_payload["model"]))

    def responses(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        requested_model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        upstream_payload = {
            **payload,
            "input": _responses_input(payload),
            "store": False,
            "stream": True,
        }
        upstream_payload["model"] = runtime.normalize_codex_model(requested_model)
        response = runtime.upstream_request(upstream_payload)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                response.iter_content(chunk_size=4096),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        return _aggregate_responses(response, requested_model, str(upstream_payload["model"]))

    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
    runtime.app.add_api_route("/v1/responses", responses, methods=["POST"])
