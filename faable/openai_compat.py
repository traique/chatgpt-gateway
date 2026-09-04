from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse

DEFAULT_PUBLIC_MODEL = "chatgpt-gpt-5.6"
IMAGE_TOOL_TYPE = "image_generation"
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
        converted = {
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description"),
            "parameters": function.get("parameters", {}),
        }
        if "strict" in function:
            converted["strict"] = function["strict"]
        return converted

    if tool_type == IMAGE_TOOL_TYPE:
        converted = {key: value for key, value in tool.items() if key != "type"}
        return {"type": IMAGE_TOOL_TYPE, **converted}

    return tool if isinstance(tool_type, str) else None


def _convert_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        tools = []

    converted = [
        tool
        for raw_tool in tools
        if isinstance(raw_tool, dict)
        for tool in [_convert_tool(raw_tool)]
        if tool is not None
    ]

    if payload.get("web_search_options") is not None and not any(
        tool.get("type") == "web_search" for tool in converted
    ):
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
                if first_delta:
                    first_delta = False
                    role_delta: dict[str, Any] = {"role": "assistant"}
                else:
                    role_delta = {}
                yield _sse({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": requested_model,
                    "choices": [{
                        "index": 0,
                        "delta": {**role_delta, "tool_calls": [{
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {"arguments": delta},
                        }]},
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
                arguments = str(item.get("arguments") or function_arguments.get(call_id, ""))
                function_metadata.setdefault(call_id, {})["arguments"] = arguments
                continue

            if event_type in {"response.error", "response.failed"}:
                error = event.get("error") or event.get("response") or "ChatGPT upstream failed."
                yield _sse({"error": error})
                break

            if event_type == "response.completed":
                if function_metadata:
                    tool_calls = []
                    for index, (call_id, metadata) in enumerate(function_metadata.items()):
                        tool_calls.append({
                            "index": index,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": metadata.get("name", ""),
                                "arguments": metadata.get("arguments", ""),
                            },
                        })
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
        if event_type == "response.output_item.done":
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
            if item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        annotations.extend(part.get("annotations", [])) if isinstance(part.get("annotations"), list) else None
                        text = part.get("text")
                        if isinstance(text, str) and text and not text_parts:
                            text_parts.append(text)

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")

    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts).strip() or None}
    if annotations:
        message["annotations"] = annotations
    if tool_calls:
        message["tool_calls"] = tool_calls

    finish_reason = "tool_calls" if tool_calls else "stop"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "provider_model": provider_model,
    }


def _image_generation_response(response: Any) -> dict[str, Any]:
    events = _read_response_events(response)
    images: list[str] = []
    terminal_error: str | None = None

    for event in events:
        event_type = event.get("type")
        if event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
            break
        if event_type != "response.output_item.done":
            continue
        item = _output_item(event)
        if not item or item.get("type") != "image_generation_call":
            continue
        result = item.get("result")
        if isinstance(result, str) and result:
            images.append(result)

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT image generation failed: {terminal_error}")
    if not images:
        raise HTTPException(status_code=502, detail="ChatGPT image generation completed without image data.")

    return {
        "created": int(time.time()),
        "data": [{"b64_json": image} for image in images],
    }


def _remove_route(runtime: Any, path: str) -> None:
    runtime.app.router.routes[:] = [
        route for route in runtime.app.router.routes if getattr(route, "path", None) != path
    ]


def install(runtime: Any) -> None:
    _remove_route(runtime, "/v1/chat/completions")
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

        return _aggregate_with_tools(
            response,
            requested_model,
            str(upstream_payload["model"]),
        )

    def images_generations(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        runtime.authorize(authorization, x_api_key)
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt is required.")

        model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        upstream_payload: dict[str, Any] = {
            "model": runtime.normalize_codex_model(model),
            "input": prompt,
            "tools": [{"type": IMAGE_TOOL_TYPE, "action": "generate"}],
            "store": False,
            "stream": True,
        }
        for key in ("quality", "size", "background", "output_format", "output_compression"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                upstream_payload["tools"][0][key] = value
        response = runtime.upstream_request(upstream_payload)
        return _image_generation_response(response)

    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
    runtime.app.add_api_route("/v1/images/generations", images_generations, methods=["POST"])
