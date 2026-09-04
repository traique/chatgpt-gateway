from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse


def build_openai_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    upstream = build_chat_completions_payload(payload)

    for source_key, target_key in (("temperature", "temperature"), ("top_p", "top_p")):
        value = payload.get(source_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            upstream[target_key] = value

    max_tokens = payload.get("max_tokens")
    if not isinstance(max_tokens, int):
        max_tokens = payload.get("max_completion_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        upstream["max_output_tokens"] = max_tokens

    return upstream


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def iter_openai_chat_stream(response: Any, requested_model: str) -> Iterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    first_delta = True

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


def install(runtime: Any) -> None:
    runtime.app.router.routes[:] = [
        route
        for route in runtime.app.router.routes
        if getattr(route, "path", None) != "/v1/chat/completions"
    ]

    def chat_completions(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Any:
        runtime.authorize(authorization, x_api_key)
        upstream_payload = build_openai_chat_payload(payload)
        response = runtime.upstream_request(upstream_payload)
        requested_model = str(payload.get("model") or "chatgpt-gpt-5.6")

        if bool(payload.get("stream", False)):
            return StreamingResponse(
                iter_openai_chat_stream(response, requested_model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        return runtime.aggregate_chat_completion(
            response,
            requested_model,
            str(upstream_payload["model"]),
        )

    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])


build_chat_completions_payload = lambda payload: payload
