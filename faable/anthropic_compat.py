from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .openai_compat import (
    DEFAULT_PUBLIC_MODEL,
    _active_provider,
    _output_item,
    _read_events,
    _read_upstream_error,
    normalize_codex_model,
)


def _anthropic_error_response(error_type: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"type": "error", "error": {"type": error_type, "message": message}},
        status_code=status_code,
    )


def _sse_event(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts: list[str] = []
        for part in system:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n\n".join(parts)
    return ""


def _image_block(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    media_type = str(source.get("media_type") or "image/png")
    if source.get("type") == "url" and isinstance(source.get("url"), str):
        return {"type": "input_image", "image_url": source["url"]}
    data = source.get("data")
    if isinstance(data, str) and data:
        return {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}
    return None


def _tool_result_output(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _convert_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return None
    return {
        "type": "function",
        "name": name,
        "description": tool.get("description"),
        "parameters": tool.get("input_schema") or {"type": "object"},
    }


def _tool_choice_from_anthropic(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    choice_type = value.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type in {"any", "required"}:
        return "required"
    if choice_type == "tool" and isinstance(value.get("name"), str):
        return {"type": "function", "name": value["name"]}
    return None


def build_responses_payload_from_anthropic(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array.")

    input_items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"

        if isinstance(content, str):
            if content:
                input_items.append({"role": role, "content": [{"type": text_type, "text": content}]})
            continue
        if not isinstance(content, list):
            continue

        blocks: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "text" and isinstance(part.get("text"), str) and part["text"]:
                blocks.append({"type": text_type, "text": part["text"]})
            elif part_type == "image":
                image = _image_block(part.get("source"))
                if image:
                    blocks.append(image)
            elif part_type == "tool_use" and role == "assistant":
                input_items.append({
                    "type": "function_call",
                    "call_id": str(part.get("id") or ""),
                    "name": str(part.get("name") or ""),
                    "arguments": json.dumps(part.get("input") or {}, ensure_ascii=False),
                })
            elif part_type == "tool_result":
                input_items.append({
                    "type": "function_call_output",
                    "call_id": str(part.get("tool_use_id") or ""),
                    "output": _tool_result_output(part.get("content")),
                })
        if blocks:
            input_items.append({"role": role, "content": blocks})

    if not input_items:
        input_items = [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]

    upstream: dict[str, Any] = {
        "model": normalize_codex_model(str(payload.get("model") or DEFAULT_PUBLIC_MODEL)),
        "instructions": _system_text(payload.get("system")) or "You are a helpful assistant.",
        "store": False,
        "stream": True,
        "input": input_items,
    }

    max_tokens = payload.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        upstream["max_output_tokens"] = max_tokens
    for key in ("temperature", "top_p"):
        if isinstance(payload.get(key), (int, float)):
            upstream[key] = payload[key]

    tools = payload.get("tools")
    if isinstance(tools, list):
        converted = [converted for tool in tools if isinstance(tool, dict) and (converted := _convert_anthropic_tool(tool))]
        if converted:
            upstream["tools"] = converted
    tool_choice = _tool_choice_from_anthropic(payload.get("tool_choice"))
    if tool_choice is not None and "tools" in upstream:
        upstream["tool_choice"] = tool_choice
    return upstream


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _anthropic_usage(usage: Any) -> dict[str, int]:
    result = {"input_tokens": 0, "output_tokens": 0}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        if isinstance(input_tokens, int):
            result["input_tokens"] = input_tokens
        if isinstance(output_tokens, int):
            result["output_tokens"] = output_tokens
    return result


def anthropic_message_from_events(events: list[dict[str, Any]], requested_model: str) -> dict[str, Any]:
    text_parts: list[str] = []
    content: list[dict[str, Any]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    terminal_error: str | None = None
    for event in events:
        event_type = event.get("type")
        if event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
            break
        if event_type == "response.output_text.delta":
            text_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.completed":
            response_payload = event.get("response")
            if isinstance(response_payload, dict):
                usage = _anthropic_usage(response_payload.get("usage"))
        elif event_type == "response.output_item.done":
            item = _output_item(event)
            if item and item.get("type") == "function_call":
                content.append({
                    "type": "tool_use",
                    "id": str(item.get("call_id") or item.get("id") or f"toolu_{uuid.uuid4().hex[:24]}"),
                    "name": str(item.get("name") or ""),
                    "input": _parse_tool_arguments(item.get("arguments")),
                })
            elif item and item.get("type") == "message" and not text_parts:
                text = _item_text_content(item)
                if text:
                    text_parts.append(text)

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    final_text = "".join(text_parts).strip()
    if final_text:
        content.insert(0, {"type": "text", "text": final_text})
    if not content:
        raise HTTPException(status_code=502, detail="ChatGPT Responses stream completed without assistant output.")
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content,
        "stop_reason": "tool_use" if any(block["type"] == "tool_use" for block in content) else "end_turn",
        "stop_sequence": None,
        "usage": usage,
    }


def _item_text_content(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def iter_anthropic_stream(response: Any, requested_model: str) -> Iterator[str]:
    message_id = f"msg_{uuid.uuid4().hex}"
    started_at = int(time.time())
    next_block_index = 0
    text_block_open = False
    text_block_index = -1
    text_emitted = False
    tool_seen = False
    open_tool_blocks: set[str] = set()
    pending_calls: dict[str, dict[str, Any]] = {}
    tool_block_indices: dict[str, int] = {}

    def open_text_block() -> str | None:
        nonlocal next_block_index, text_block_open, text_block_index
        if text_block_open:
            return None
        text_block_open = True
        text_block_index = next_block_index
        next_block_index += 1
        return _sse_event("content_block_start", {
            "type": "content_block_start",
            "index": text_block_index,
            "content_block": {"type": "text", "text": ""},
        })

    def open_tool_block(item_id: str, call_id: str, name: str) -> str:
        nonlocal next_block_index, tool_seen
        tool_seen = True
        close_text = _close_text_block()
        index = next_block_index
        next_block_index += 1
        tool_block_indices[item_id] = index
        open_tool_blocks.add(item_id)
        start = _sse_event("content_block_start", {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "tool_use", "id": call_id, "name": name, "input": {}},
        })
        return (close_text or "") + start

    def _close_text_block() -> str | None:
        nonlocal text_block_open
        if not text_block_open:
            return None
        text_block_open = False
        return _sse_event("content_block_stop", {"type": "content_block_stop", "index": text_block_index})

    try:
        yield _sse_event("message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": requested_model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        })

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
                start = open_text_block()
                if start:
                    yield start
                text_emitted = True
                yield _sse_event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": text_block_index,
                    "delta": {"type": "text_delta", "text": delta},
                })
                continue

            if event_type == "response.output_item.added":
                item = _output_item(event)
                if item and item.get("type") == "function_call":
                    item_id = str(item.get("id") or "")
                    pending_calls[item_id] = item
                    yield open_tool_block(
                        item_id,
                        str(item.get("call_id") or item_id),
                        str(item.get("name") or ""),
                    )
                continue

            if event_type == "response.function_call_arguments.delta":
                item_id = str(event.get("item_id") or "")
                delta = str(event.get("delta") or "")
                if item_id and item_id not in tool_block_indices:
                    item = pending_calls.get(item_id, {})
                    yield open_tool_block(
                        item_id,
                        str(item.get("call_id") or item_id),
                        str(item.get("name") or ""),
                    )
                if delta and item_id in tool_block_indices:
                    yield _sse_event("content_block_delta", {
                        "type": "content_block_delta",
                        "index": tool_block_indices[item_id],
                        "delta": {"type": "input_json_delta", "partial_json": delta},
                    })
                continue

            if event_type == "response.output_item.done":
                item = _output_item(event)
                if item and item.get("type") == "function_call":
                    item_id = str(item.get("id") or "")
                    if item_id not in tool_block_indices:
                        yield open_tool_block(
                            item_id,
                            str(item.get("call_id") or item_id),
                            str(item.get("name") or ""),
                        )
                        arguments = str(item.get("arguments") or "")
                        if arguments:
                            yield _sse_event("content_block_delta", {
                                "type": "content_block_delta",
                                "index": tool_block_indices[item_id],
                                "delta": {"type": "input_json_delta", "partial_json": arguments},
                            })
                    if item_id in open_tool_blocks:
                        open_tool_blocks.discard(item_id)
                        yield _sse_event("content_block_stop", {
                            "type": "content_block_stop",
                            "index": tool_block_indices[item_id],
                        })
                elif item and item.get("type") == "message" and not text_emitted:
                    text = _item_text_content(item)
                    if text:
                        start = open_text_block()
                        if start:
                            yield start
                        text_emitted = True
                        yield _sse_event("content_block_delta", {
                            "type": "content_block_delta",
                            "index": text_block_index,
                            "delta": {"type": "text_delta", "text": text},
                        })
                continue

            if event_type in {"response.error", "response.failed"}:
                error = event.get("error") or event.get("response") or "ChatGPT upstream failed."
                if isinstance(error, dict):
                    message = str(error.get("message") or error)
                else:
                    message = str(error)
                yield _sse_event("error", {
                    "type": "error",
                    "error": {"type": "api_error", "message": message},
                })
                break

            if event_type == "response.completed":
                response_payload = event.get("response")
                usage = {"input_tokens": 0, "output_tokens": 0}
                if isinstance(response_payload, dict):
                    usage = _anthropic_usage(response_payload.get("usage"))
                close_text = _close_text_block()
                if close_text:
                    yield close_text
                yield _sse_event("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use" if tool_seen else "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": usage["output_tokens"]},
                })
                yield _sse_event("message_stop", {"type": "message_stop"})
                break
    finally:
        try:
            response.close()
        except Exception:
            pass


def _http_error_type(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code in (400, 404, 422):
        return "invalid_request_error"
    if status_code == 429:
        return "rate_limit_error"
    return "api_error"


def _bai_messages_passthrough(runtime: Any, payload: dict[str, Any], requested_model: str) -> Any:
    """B.AI natively speaks the Anthropic Messages protocol — forward as-is."""
    if not getattr(runtime, "BAI_API_KEY", ""):
        return _anthropic_error_response("authentication_error", "BAI_API_KEY is not configured.", 503)
    resolver = getattr(runtime, "resolve_model", None)
    effective_model = resolver(requested_model, DEFAULT_PUBLIC_MODEL) if resolver else (requested_model or DEFAULT_PUBLIC_MODEL)
    bai_payload = {**payload, "model": effective_model}
    try:
        response = runtime.requests.post(
            f"{runtime.BAI_BASE_URL}/messages",
            json=bai_payload,
            headers={
                "x-api-key": runtime.BAI_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            impersonate="chrome120",
            timeout=120,
            stream=True,
        )
    except Exception as error:
        return _anthropic_error_response("api_error", f"B.AI transport failed: {error}", 502)
    if response.status_code >= 400:
        detail = _read_upstream_error(response)
        try:
            response.close()
        except Exception:
            pass
        return _anthropic_error_response(
            _http_error_type(response.status_code),
            f"B.AI HTTP {response.status_code}: {detail}",
            response.status_code,
        )
    if bool(payload.get("stream", False)):
        return StreamingResponse(
            response.iter_content(chunk_size=4096),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    try:
        return JSONResponse(response.json())
    except (TypeError, ValueError):
        return _anthropic_error_response("api_error", "B.AI returned a non-JSON response.", 502)


def install(runtime: Any) -> None:
    runtime.app.router.routes[:] = [
        route for route in runtime.app.router.routes if getattr(route, "path", None) != "/v1/messages"
    ]

    def messages(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        try:
            runtime.authorize(authorization, x_api_key)
            requested_model = str(payload.get("model") or "")
            if _active_provider(runtime) == "bai":
                return _bai_messages_passthrough(runtime, payload, requested_model)
            resolver = getattr(runtime, "resolve_model", None)
            effective_model = resolver(requested_model, DEFAULT_PUBLIC_MODEL) if resolver else (requested_model or DEFAULT_PUBLIC_MODEL)
            upstream_payload = build_responses_payload_from_anthropic(payload)
            response = runtime.upstream_request(upstream_payload)
            if response.status_code >= 400:
                detail = _read_upstream_error(response)
                try:
                    response.close()
                except Exception:
                    pass
                return _anthropic_error_response(
                    _http_error_type(response.status_code),
                    f"ChatGPT upstream HTTP {response.status_code}: {detail}",
                    response.status_code if response.status_code >= 400 else 502,
                )
            if bool(payload.get("stream", False)):
                return StreamingResponse(
                    iter_anthropic_stream(response, effective_model),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )
            return anthropic_message_from_events(_read_events(response), effective_model)
        except HTTPException as error:
            return _anthropic_error_response(
                _http_error_type(error.status_code or 500),
                str(error.detail),
                error.status_code or 500,
            )

    runtime.app.add_api_route("/v1/messages", messages, methods=["POST"])
