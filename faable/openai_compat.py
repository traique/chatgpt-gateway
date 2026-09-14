from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .notion_provider import aggregate_notion_chat, iter_notion_chat_stream

DEFAULT_PUBLIC_MODEL = "chatgpt-gpt-5.6"
DEFAULT_CODEX_MODEL = "gpt-5.6-terra"
WEB_SEARCH_TOOL_TYPES = frozenset({"web_search", "web_search_preview"})
TRANSIENT_CHATGPT_CODES = frozenset({"server_is_overloaded", "server_overloaded", "overloaded", "rate_limit_exceeded"})
CHATGPT_TRANSIENT_RETRIES = 1


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


def _tool_call_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return items
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        items.append({
            "type": "function_call",
            "call_id": str(call.get("id") or ""),
            "name": str(function.get("name") or ""),
            "arguments": str(function.get("arguments") or "{}"),
        })
    return items


def build_openai_chat_payload(payload: dict[str, Any], resolved_model: str | None = None) -> dict[str, Any]:
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
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": str(message.get("tool_call_id") or ""),
                "output": _message_text(content),
            })
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        blocks = _responses_content(role, content)
        if blocks:
            input_items.append({"role": role, "content": blocks})
        input_items.extend(_tool_call_items(message))

    if not input_items:
        input_items = [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]

    instructions = "\n\n".join(system_chunks) or "You are a helpful assistant."
    upstream: dict[str, Any] = {
        "model": normalize_codex_model(str(resolved_model or payload.get("model") or DEFAULT_PUBLIC_MODEL)),
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


def _chat_usage(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if total is None and isinstance(prompt, int) and isinstance(completion, int):
        total = prompt + completion
    if not isinstance(prompt, int) and not isinstance(completion, int):
        return None
    result: dict[str, int] = {}
    if isinstance(prompt, int):
        result["prompt_tokens"] = prompt
    if isinstance(completion, int):
        result["completion_tokens"] = completion
    if isinstance(total, int):
        result["total_tokens"] = total
    return result or None


def _tool_call_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("call_id") or item.get("id") or ""),
        "type": "function",
        "function": {
            "name": str(item.get("name") or ""),
            "arguments": str(item.get("arguments") or "{}"),
        },
    }


def _response_error(event: dict[str, Any]) -> tuple[str, str]:
    error: Any = event.get("error")
    response_payload = event.get("response")
    if not error and isinstance(response_payload, dict):
        error = response_payload.get("error")
    if not error:
        error = response_payload
    if isinstance(error, dict):
        return str(error.get("code") or "").strip().lower(), str(error.get("message") or error.get("code") or error)
    return "", str(error or "ChatGPT upstream failed.")


def _is_transient_chatgpt_event(event: dict[str, Any]) -> bool:
    response_payload = event.get("response")
    is_failed = (
        event.get("type") in {"response.error", "response.failed"}
        or event.get("status") == "failed"
        or (isinstance(response_payload, dict) and response_payload.get("status") == "failed")
    )
    if not is_failed:
        return False
    code, message = _response_error(event)
    normalized_message = message.lower().replace("-", "_").replace(" ", "_")
    return code in TRANSIENT_CHATGPT_CODES or any(code in normalized_message for code in TRANSIENT_CHATGPT_CODES)


def _iter_response_sse_with_retry(runtime: Any, payload: dict[str, Any], response: Any) -> Iterator[bytes | str]:
    """Proxy Responses SSE and retry one pre-output transient ChatGPT failure.

    Lifecycle events are buffered until the first actual output. This prevents a
    failed response id from reaching clients such as 9Router before a safe retry.
    """
    attempt = 0
    current = response
    while True:
        buffered: list[str] = []
        committed = False
        retry = False
        try:
            for line in current.iter_lines():
                if isinstance(line, bytes):
                    text = line.decode("utf-8", "ignore")
                else:
                    text = str(line or "")
                stripped = text.strip()
                if not stripped:
                    continue
                frame = stripped + "\n\n"
                if not stripped.startswith("data:"):
                    if committed:
                        yield frame
                    else:
                        buffered.append(frame)
                    continue
                raw = stripped[5:].strip()
                if raw == "[DONE]":
                    for item in buffered:
                        yield item
                    yield frame
                    return
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    event = None

                if isinstance(event, dict) and _is_transient_chatgpt_event(event) and not committed and attempt < CHATGPT_TRANSIENT_RETRIES:
                    retry = True
                    break

                event_type = event.get("type") if isinstance(event, dict) else ""
                lifecycle = event_type in {"response.created", "response.in_progress", "response.queued"}
                if not committed and lifecycle:
                    buffered.append(frame)
                    continue
                if not committed:
                    committed = True
                    for item in buffered:
                        yield item
                    buffered.clear()
                yield frame
        finally:
            try:
                current.close()
            except Exception:
                pass

        if retry:
            attempt += 1
            current = _request(runtime, payload)
            continue
        for item in buffered:
            yield item
        return


def iter_openai_chat_stream(
    response: Any,
    requested_model: str,
    *,
    retry_request: Any | None = None,
) -> Iterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    first_delta = True
    emitted_text = False
    tool_calls_emitted = False
    tool_index = -1
    announced_calls: set[str] = set()
    pending_calls: dict[str, dict[str, Any]] = {}
    usage: dict[str, int] | None = None
    retries = 0

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        return _sse({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": requested_model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        })

    def announce_tool_call(call_id: str, name: str, arguments: str) -> str:
        nonlocal tool_index, tool_calls_emitted
        tool_index += 1
        tool_calls_emitted = True
        return chunk({"tool_calls": [{
            "index": tool_index,
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }]})

    while True:
        retry_stream = False
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
                    yield chunk(content_delta)
                    continue

                if event_type == "response.output_item.added":
                    item = _output_item(event)
                    if item and item.get("type") == "function_call":
                        item_id = str(item.get("id") or "")
                        pending_calls[item_id] = item
                        call_id = str(item.get("call_id") or item_id)
                        yield announce_tool_call(call_id, str(item.get("name") or ""), "")
                        announced_calls.add(item_id or call_id)
                    continue

                if event_type == "response.function_call_arguments.delta":
                    item_id = str(event.get("item_id") or "")
                    delta = str(event.get("delta") or "")
                    if item_id and item_id not in announced_calls:
                        item = pending_calls.get(item_id, {})
                        yield announce_tool_call(
                            str(item.get("call_id") or item_id or f"call_{uuid.uuid4().hex[:24]}"),
                            str(item.get("name") or ""),
                            "",
                        )
                        announced_calls.add(item_id)
                    if delta:
                        yield chunk({"tool_calls": [{"index": tool_index, "function": {"arguments": delta}}]})
                    continue

                if event_type == "response.output_item.done":
                    item = _output_item(event)
                    if item and item.get("type") == "function_call":
                        item_id = str(item.get("id") or "")
                        if item_id not in announced_calls:
                            yield announce_tool_call(
                                str(item.get("call_id") or item_id),
                                str(item.get("name") or ""),
                                str(item.get("arguments") or "{}"),
                            )
                    elif item and item.get("type") == "message" and not emitted_text:
                        text = _item_text(item)
                        if text:
                            emitted_text = True
                            first_delta = False
                            yield chunk({"role": "assistant", "content": text})
                    continue

                if event_type in {"response.error", "response.failed"}:
                    code, message = _response_error(event)
                    if (
                        _is_transient_chatgpt_event(event)
                        and retry_request is not None
                        and retries < CHATGPT_TRANSIENT_RETRIES
                        and not emitted_text
                        and not tool_calls_emitted
                    ):
                        retry_stream = True
                        break
                    yield _sse({"error": {"message": message, "type": "upstream_error", "code": code or None}})
                    break

                if event_type == "response.completed":
                    response_payload = event.get("response")
                    if isinstance(response_payload, dict):
                        usage = _chat_usage(response_payload.get("usage"))
                    finish_reason = "tool_calls" if tool_calls_emitted else "stop"
                    final_chunk: dict[str, Any] = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": requested_model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    }
                    if usage:
                        final_chunk["usage"] = usage
                    yield _sse(final_chunk)
                    break
        finally:
            try:
                response.close()
            except Exception:
                pass
        if retry_stream:
            retries += 1
            response = retry_request()
            continue
        break
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
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] | None = None
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
                usage = _chat_usage(response_payload.get("usage"))
        elif event_type == "response.output_item.done":
            item = _output_item(event)
            if item and item.get("type") == "function_call":
                tool_calls.append(_tool_call_from_item(item))
            elif item and item.get("type") == "message" and not text_parts:
                text_parts.append(_item_text(item))

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")
    final_text = "".join(text_parts).strip()
    if not final_text and not tool_calls:
        raise HTTPException(status_code=502, detail="ChatGPT Responses stream completed without assistant text.")
    message: dict[str, Any] = {"role": "assistant", "content": final_text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    result: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
    }
    if usage:
        result["usage"] = usage
    return result


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


def _active_provider(runtime: Any) -> str:
    policy_getter = getattr(runtime, "get_client_policy", None)
    policy = policy_getter() if policy_getter else None
    if policy and policy.get("provider"):
        return policy["provider"]
    provider_getter = getattr(runtime, "get_active_provider", None)
    return provider_getter() if provider_getter else "chatgpt"


def _resolved_model(runtime: Any, requested: str, default: str) -> str:
    resolver = getattr(runtime, "resolve_model", None)
    return resolver(requested, default) if resolver else (str(requested or "").strip() or default)


def _passthrough_response(response: Any, stream: bool, provider_label: str = "B.AI") -> Any:
    if response.status_code >= 400:
        detail = _read_upstream_error(response)
        try:
            response.close()
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"{provider_label} HTTP {response.status_code}: {detail}")
    if stream:
        return StreamingResponse(
            response.iter_content(chunk_size=4096),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    try:
        return JSONResponse(response.json())
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"{provider_label} returned a non-JSON response.") from error


def install(runtime: Any) -> None:
    _remove_route(runtime, "/v1/chat/completions")
    _remove_route(runtime, "/v1/responses")

    def chat_completions(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        active = _active_provider(runtime)
        # Catalog-backed providers: resolve the requested id against the provider
        # catalog, falling back to the admin pick when the client hardcodes an
        # unknown model (ZCode sends glm-5.3-flash regardless of the provider).
        provider_resolver = getattr(runtime, "resolve_provider_model", None)
        if active != "chatgpt" and provider_resolver is not None:
            requested_model = provider_resolver(active, str(payload.get("model") or ""))
        else:
            requested_model = _resolved_model(runtime, str(payload.get("model") or ""), DEFAULT_PUBLIC_MODEL)
        # OpenAI-native providers: forward the payload as-is, only pinning the model.
        passthrough = {
            "bai": (runtime.bai_request, "B.AI"),
            "openrouter": (runtime.openrouter_request, "OpenRouter"),
            "tokenrouter": (runtime.tokenrouter_request, "TokenRouter"),
            "nim": (runtime.nim_request, "NVIDIA NIM"),
            "generic": (runtime.generic_request, "OpenAI Compatible"),
        }.get(active)
        if passthrough is None and getattr(runtime, "is_dynamic_provider", lambda _provider: False)(active):
            passthrough = (
                lambda path, **kwargs: runtime.dynamic_provider_request(active, path, **kwargs),
                runtime.dynamic_provider_label(active),
            )
        if passthrough is not None:
            requester, provider_label = passthrough
            # Stream upstream only when the client asked for it — curl_cffi
            # responses opened in stream mode cannot be parsed with .json().
            sanitizer = getattr(runtime, "sanitize_chat_payload", None)
            upstream_payload = sanitizer(active, payload, requested_model) if sanitizer else {**payload, "model": requested_model}
            response = requester("/chat/completions", json_payload=upstream_payload, stream=bool(payload.get("stream", False)))
            return _passthrough_response(response, bool(payload.get("stream", False)), provider_label)
        if active == "notion":
            notion_response = runtime.notion_request({**payload, "model": requested_model})
            if bool(payload.get("stream", False)):
                return StreamingResponse(
                    iter_notion_chat_stream(notion_response, requested_model),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )
            return JSONResponse(aggregate_notion_chat(notion_response, requested_model))
        upstream_payload = build_openai_chat_payload(payload, requested_model)
        response = _request(runtime, upstream_payload)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                iter_openai_chat_stream(
                    response,
                    requested_model,
                    retry_request=lambda: _request(runtime, upstream_payload),
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        try:
            return _aggregate_chat(response, requested_model)
        except HTTPException as error:
            if "server_is_overloaded" not in str(error.detail).lower():
                raise
            retry_response = _request(runtime, upstream_payload)
            return _aggregate_chat(retry_response, requested_model)

    def responses(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        active = _active_provider(runtime)
        unsupported_labels = {"openrouter": "OpenRouter", "notion": "Notion AI", "nim": "NVIDIA NIM"}
        if active in unsupported_labels:
            raise HTTPException(
                status_code=503,
                detail=f"{unsupported_labels[active]} does not support /v1/responses. Use /v1/chat/completions.",
            )
        requested_model = str(payload.get("model") or DEFAULT_PUBLIC_MODEL)
        if active == "tokenrouter":
            provider_resolver = getattr(runtime, "resolve_provider_model", None)
            effective_model = provider_resolver(active, requested_model) if provider_resolver else requested_model
            tokenrouter_payload = {**payload, "model": effective_model}
            response = runtime.tokenrouter_request(
                "/responses",
                json_payload=tokenrouter_payload,
                stream=bool(payload.get("stream", False)),
            )
            return _passthrough_response(response, bool(payload.get("stream", False)), "TokenRouter")
        if active == "generic":
            provider_resolver = getattr(runtime, "resolve_provider_model", None)
            effective_model = provider_resolver(active, requested_model) if provider_resolver else requested_model
            generic_payload = {**payload, "model": effective_model}
            response = runtime.generic_request(
                "/responses",
                json_payload=generic_payload,
                stream=bool(payload.get("stream", False)),
            )
            return _passthrough_response(response, bool(payload.get("stream", False)), "OpenAI Compatible")
        if getattr(runtime, "is_dynamic_provider", lambda _provider: False)(active):
            provider_resolver = getattr(runtime, "resolve_provider_model", None)
            effective_model = provider_resolver(active, requested_model) if provider_resolver else requested_model
            dynamic_payload = {**payload, "model": effective_model}
            response = runtime.dynamic_provider_request(
                active,
                "/responses",
                json_payload=dynamic_payload,
                stream=bool(payload.get("stream", False)),
            )
            return _passthrough_response(response, bool(payload.get("stream", False)), runtime.dynamic_provider_label(active))
        if active == "bai":
            bai_payload = {**payload, "model": _resolved_model(runtime, requested_model, DEFAULT_PUBLIC_MODEL)}
            response = runtime.bai_request("/responses", json_payload=bai_payload, stream=bool(payload.get("stream", False)))
            return _passthrough_response(response, bool(payload.get("stream", False)))
        requested_model = _resolved_model(runtime, requested_model, DEFAULT_PUBLIC_MODEL)
        upstream_payload = dict(payload)
        upstream_payload["model"] = normalize_codex_model(requested_model)
        upstream_payload["store"] = False
        upstream_payload["stream"] = True
        response = _request(runtime, upstream_payload)
        if bool(payload.get("stream", False)):
            return StreamingResponse(
                _iter_response_sse_with_retry(runtime, upstream_payload, response),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        try:
            return _aggregate_responses(response, requested_model)
        except HTTPException as error:
            if "server_is_overloaded" not in str(error.detail).lower():
                raise
            retry_response = _request(runtime, upstream_payload)
            return _aggregate_responses(retry_response, requested_model)

    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
    runtime.app.add_api_route("/v1/responses", responses, methods=["POST"])
    # LanAnh and older 9Router-style clients append `/chat/completions` to a
    # bare gateway origin. Keep those clients working while `/v1/*` remains
    # the canonical OpenAI-compatible surface.
    runtime.app.add_api_route("/chat/completions", chat_completions, methods=["POST"], include_in_schema=False)
    runtime.app.add_api_route("/responses", responses, methods=["POST"], include_in_schema=False)


def _remove_route(runtime: Any, path: str) -> None:
    runtime.app.router.routes[:] = [route for route in runtime.app.router.routes if getattr(route, "path", None) != path]
