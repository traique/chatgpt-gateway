from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse

DEFAULT_PUBLIC_MODEL = "chatgpt-gpt-5.6"
DEFAULT_CODEX_MODEL = "gpt-5.6-terra"
WEB_SEARCH_TOOL_TYPES = frozenset({"web_search", "web_search_preview"})


def normalize_codex_model(model: str) -> str:
    normalized = model.strip()
    if normalized in {"", DEFAULT_PUBLIC_MODEL, "gpt-5.6"}:
        return DEFAULT_CODEX_MODEL
    if normalized.startswith("chatgpt:"):
        normalized = normalized.removeprefix("chatgpt:")
    if normalized.startswith("chatgpt-"):
        normalized = normalized.removeprefix("chatgpt-")
    return normalized or DEFAULT_CODEX_MODEL


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"text", "input_text", "output_text"}:
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _responses_content(role: str, content: Any) -> list[dict[str, Any]]:
    text_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str):
        return [{"type": text_type, "text": content}] if content else []
    if not isinstance(content, list):
        return []

    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                blocks.append({"type": text_type, "text": text})
            continue
        if part_type == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if isinstance(url, str) and url:
                block: dict[str, Any] = {"type": "input_image", "image_url": url}
                if isinstance(image_url, dict) and image_url.get("detail"):
                    block["detail"] = image_url["detail"]
                blocks.append(block)
            continue
        if part_type in {"input_text", "input_image", "output_text"}:
            blocks.append(dict(part))
    return blocks


def build_openai_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array.")

    system_chunks: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if role == "system":
            text = _message_text(content)
            if text:
                system_chunks.append(text)
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        blocks = _responses_content(role, content)
        if blocks:
            input_items.append({"role": role, "content": blocks})

    if not input_items:
        input_items = [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]

    instructions = "\n\n".join(system_chunks) or "You are a helpful assistant."
    upstream: dict[str, Any] = {
        "model": normalize_codex_model(str(payload.get("model") or DEFAULT_PUBLIC_MODEL)),
        "instructions": instructions,
        "store": False,
        "stream": True,
        "input": input_items,
    }

    tools = _convert_tools(payload)
    if tools:
        upstream["tools"] = tools
    return upstream


def _convert_tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    tool_type = tool.get("type")
    if tool_type in WEB_SEARCH_TOOL_TYPES:
        converted = {key: value for key, value in tool.items() if key != "type"}
        return {"type": "web_search", **converted}
    if tool_type != "function":
        return None
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


def _convert_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    tools = payload.get("tools")
    if isinstance(tools, list):
        for raw_tool in tools:
            if isinstance(raw_tool, dict):
                tool = _convert_tool(raw_tool)
                if tool is not None:
                    converted.append(tool)
    if payload.get("web_search_options") is not None and not any(tool.get("type") == "web_search" for tool in converted):
        options = payload.get("web_search_options")
        converted.append({"type": "web_search", **options} if isinstance(options, dict) else {"type": "web_search"})
    return converted


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _output_item(event: dict[str, Any]) -> dict[str, Any] | None:
    item = event.get("item")
    return item if isinstance(item, dict) else None


def _item_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def iter_openai_chat_stream(response: Any, requested_model: str) -> Iterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    first_delta = True
    emitted_text = False
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
                emitted_text = True
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

            if event_type == "response.output_item.done":
                item = _output_item(event)
                if item and item.get("type") == "message" and not emitted_text:
                    text = _item_text(item)
                    if text:
                        emitted_text = True
                        delta: dict[str, Any] = {"role": "assistant", "content": text}
                        first_delta = False
                        yield _sse({
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        })
                continue

            if event_type in {"response.error", "response.failed"}:
                error = event.get("error") or event.get("response") or "ChatGPT upstream failed."
                yield _sse({"error": error})
                break

            if event_type == "response.completed":
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


def _read_events(response: Any) -> list[dict[str, Any]]:
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


def _aggregate_chat(response: Any, requested_model: str) -> dict[str, Any]:
    events = _read_events(response)
    text_parts: list[str] = []
    terminal_error: str | None = None
    for event in events:
        event_type = event.get("type")
        if event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
            break
        if event_type == "response.output_text.delta":
            text_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.output_item.done":
            item = _output_item(event)
            if item and item.get("type") == "message" and not text_parts:
                text_parts.append(_item_text(item))

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    final_text = "".join(text_parts).strip()
    if not final_text:
        raise HTTPException(status_code=502, detail="ChatGPT Responses stream completed without assistant text.")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": final_text},
            "finish_reason": "stop",
        }],
    }


def _aggregate_responses(response: Any, requested_model: str) -> dict[str, Any]:
    events = _read_events(response)
    completed: dict[str, Any] | None = None
    output: list[dict[str, Any]] = []
    text_parts: list[str] = []
    terminal_error: str | None = None
    for event in events:
        event_type = event.get("type")
        if event_type == "response.completed" and isinstance(event.get("response"), dict):
            completed = event["response"]
        elif event_type in {"response.error", "response.failed"}:
            terminal_error = str(event.get("error") or event.get("response") or event)[:500]
        elif event_type == "response.output_text.delta":
            text_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.output_item.done":
            item = _output_item(event)
            if item:
                output.append(item)
                if item.get("type") == "message":
                    text_parts.append(_item_text(item))

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    if completed is not None:
        result = dict(completed)
        if not result.get("output") and output:
            result["output"] = output
        if not result.get("output_text") and text_parts:
            result["output_text"] = "".join(text_parts)
        return result
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": requested_model,
        "output": output,
        "output_text": "".join(text_parts),
    }


def _read_upstream_error(response: Any) -> str:
    try:
        body = response.text
        if body:
            return body[:1000]
    except Exception:
        pass
    return f"HTTP {response.status_code}"


def _request(runtime: Any, payload: dict[str, Any]) -> Any:
    response = runtime.upstream_request(payload)
    if response.status_code == 400 and "tools" in payload:
        try:
            response.close()
        except Exception:
            pass
        retry_payload = {key: value for key, value in payload.items() if key != "tools"}
        response = runtime.upstream_request(retry_payload)
    if response.status_code >= 400:
        detail = _read_upstream_error(response)
        try:
            response.close()
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses HTTP {response.status_code}: {detail}")
    return response


def install(runtime: Any) -> None:
    _remove_route(runtime, "/v1/chat/completions")
    _remove_route(runtime, "/v1/responses")

    def chat_completions(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        requested_model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        upstream_payload = build_openai_chat_payload(payload)
        response = _request(runtime, upstream_payload)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                iter_openai_chat_stream(response, requested_model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return _aggregate_chat(response, requested_model)

    def responses(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        requested_model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        upstream_payload = dict(payload)
        upstream_payload["model"] = normalize_codex_model(requested_model)
        upstream_payload["store"] = False
        upstream_payload["stream"] = True
        response = _request(runtime, upstream_payload)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                response.iter_content(chunk_size=4096),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return _aggregate_responses(response, requested_model)

    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
    runtime.app.add_api_route("/v1/responses", responses, methods=["POST"])


def _remove_route(runtime: Any, path: str) -> None:
    runtime.app.router.routes[:] = [route for route in runtime.app.router.routes if getattr(route, "path", None) != path]
