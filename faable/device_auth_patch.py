from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import HTTPException, Header, Request
from fastapi.responses import StreamingResponse

PENDING_DEVICE_AUTH_CODES = frozenset({
    "deviceauth_authorization_pending",
    "authorization_pending",
    "pending",
})
DEFAULT_CODEX_MODEL = "gpt-5.6-terra"


def parse_json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError) as error:
        content_type = response.headers.get("content-type", "unknown")
        raise ValueError(
            f"Device login returned non-JSON response: HTTP {response.status_code}, content-type={content_type}."
        ) from error
    if not isinstance(payload, dict):
        raise ValueError(f"Device login returned invalid JSON payload: HTTP {response.status_code}.")
    return payload


def classify_device_auth_response(response: Any) -> tuple[str, str | None]:
    content_type = response.headers.get("content-type", "").lower()
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return "failed", "OpenAI authentication endpoint returned a Cloudflare challenge."
    if "text/html" in content_type:
        return "failed", f"OpenAI authentication endpoint returned HTML (HTTP {response.status_code})."

    try:
        payload = parse_json_payload(response)
    except ValueError:
        return "failed", f"OpenAI authentication endpoint returned an invalid response (HTTP {response.status_code})."

    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type") or error.get("error")
        message = error.get("message") or error.get("error_description")
    else:
        code = error or payload.get("error_code") or payload.get("code")
        message = payload.get("error_description") or payload.get("message")

    normalized_code = str(code).strip().lower() if code is not None else ""
    if normalized_code in PENDING_DEVICE_AUTH_CODES:
        return "pending", None
    if response.status_code in (403, 404) and not code and not message:
        return "pending", None
    if code or message:
        return "failed", str(message or code)
    return "failed", f"OpenAI authentication endpoint returned HTTP {response.status_code}."


def _mark_session(runtime: Any, login_id: str, status: str) -> None:
    with runtime.db() as connection:
        connection.execute(
            "UPDATE device_login_sessions SET status=%s, updated_at=%s WHERE id=%s",
            (status, int(time.time() * 1000), login_id),
        )


def _remove_routes(runtime: Any, paths: frozenset[str]) -> None:
    runtime.app.router.routes[:] = [
        route
        for route in runtime.app.router.routes
        if getattr(route, "path", None) not in paths
    ]


def _extract_message_blocks(message: dict[str, Any], role: str) -> list[dict[str, Any]]:
    content = message.get("content", "")
    text_type = "output_text" if role == "assistant" else "input_text"
    blocks: list[dict[str, Any]] = []

    if isinstance(content, str):
        if content:
            blocks.append({"type": text_type, "text": content})
        return blocks

    if not isinstance(content, list):
        return blocks

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
        if part_type in {"input_text", "input_image"}:
            blocks.append(part)

    return blocks


def normalize_codex_model(value: str) -> str:
    model = value.removeprefix("chatgpt-")
    if model == "gpt-5.6":
        return DEFAULT_CODEX_MODEL
    return model


def build_chat_completions_payload(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array.")

    system_chunks: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "system":
            content = message.get("content", "")
            if isinstance(content, str) and content:
                system_chunks.append(content)
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        blocks = _extract_message_blocks(message, role)
        if blocks:
            input_items.append({"role": role, "content": blocks})

    if not input_items:
        input_items = [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]

    model = normalize_codex_model(str(payload.get("model") or DEFAULT_CODEX_MODEL))
    instructions = "\n\n".join(system_chunks) or "You are a helpful assistant."
    return {
        "model": model,
        "instructions": instructions,
        "store": False,
        "stream": True,
        "input": input_items,
    }


def _extract_stream_text(event: dict[str, Any]) -> str:
    if event.get("type") == "response.output_text.delta":
        return str(event.get("delta") or "")
    if isinstance(event.get("delta"), str):
        return event["delta"]
    return ""


def aggregate_chat_completion(response: Any, requested_model: str, provider_model: str) -> dict[str, Any]:
    parts: list[str] = []
    terminal_error: str | None = None
    try:
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") in {"response.error", "response.failed"}:
                terminal_error = str(event.get("error") or event.get("response") or event)[:500]
                break
            text = _extract_stream_text(event)
            if text:
                parts.append(text)
    finally:
        try:
            response.close()
        except Exception:
            pass

    if terminal_error:
        raise HTTPException(status_code=502, detail=f"ChatGPT Responses stream failed: {terminal_error}")

    final_text = "".join(parts).strip()
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
        "provider_model": provider_model,
    }


def upstream_response(runtime: Any, response: Any, requested_model: str | None = None, provider_model: str | None = None) -> Any:
    if response.status_code >= 400:
        try:
            raw_body = b"".join(response.iter_content())
        except Exception:
            raw_body = b""
        content_type = response.headers.get("content-type", "")
        body = raw_body.decode("utf-8", "ignore")[:1000]
        if not body and "text/html" in content_type.lower():
            body = f"ChatGPT upstream returned an HTML block page (HTTP {response.status_code})."
        raise HTTPException(status_code=response.status_code, detail=body or f"ChatGPT upstream returned HTTP {response.status_code}.")

    return StreamingResponse(response.iter_content(chunk_size=4096), media_type="text/event-stream")


def install(runtime: Any) -> None:
    _remove_routes(runtime, frozenset({"/auth/device/poll", "/v1/chat/completions", "/v1/responses"}))

    def device_poll(request: Request, payload: dict[str, Any]) -> dict[str, str]:
        runtime.require_admin(request)
        runtime.database_required()

        login_id = payload.get("login_id")
        if not isinstance(login_id, str):
            raise HTTPException(status_code=400, detail="login_id is required.")

        with runtime.db() as connection:
            row = connection.execute(
                "SELECT id, device_auth_id, user_code, expires_at, status "
                "FROM device_login_sessions WHERE id=%s",
                (login_id,),
            ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Login session not found.")
        if row[4] != "pending":
            return {"login_id": login_id, "status": str(row[4])}

        if int(row[3]) <= int(time.time() * 1000):
            _mark_session(runtime, login_id, "expired")
            return {"login_id": login_id, "status": "expired"}

        response = runtime.requests.post(
            f"{runtime.CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/token",
            headers={**runtime.device_auth_headers(), "Accept": "application/json"},
            json={"device_auth_id": row[1], "user_code": row[2]},
            impersonate="chrome120",
            timeout=30,
        )

        if response.status_code in (403, 404):
            state, message = classify_device_auth_response(response)
            if state == "pending":
                return {"login_id": login_id, "status": "pending"}
            _mark_session(runtime, login_id, "failed")
            raise HTTPException(status_code=502, detail=message or "Device authorization failed.")

        if not response.ok:
            _mark_session(runtime, login_id, "failed")
            raise HTTPException(status_code=502, detail=f"Device login failed: {runtime.read_error(response)}")

        try:
            auth_payload = parse_json_payload(response)
        except ValueError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        authorization_code = auth_payload.get("authorization_code")
        code_verifier = auth_payload.get("code_verifier")
        if not isinstance(authorization_code, str) or not authorization_code:
            raise HTTPException(status_code=502, detail="Device login response is missing authorization_code.")
        if not isinstance(code_verifier, str) or not code_verifier:
            raise HTTPException(status_code=502, detail="Device login response is missing code_verifier.")

        token_response = runtime.requests.post(
            f"{runtime.CHATGPT_AUTH_BASE_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                "client_id": runtime.CHATGPT_OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "user-agent": runtime.CODEX_USER_AGENT,
            },
            impersonate="chrome120",
            timeout=30,
        )
        if not token_response.ok:
            _mark_session(runtime, login_id, "failed")
            raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {runtime.read_error(token_response)}")

        try:
            tokens = parse_json_payload(token_response)
        except ValueError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        id_token = tokens.get("id_token")
        account_id = runtime.extract_account_id(id_token or "") or runtime.extract_account_id(access_token or "")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status_code=502, detail="OAuth response is missing access_token.")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise HTTPException(status_code=502, detail="OAuth response is missing refresh_token.")
        if not account_id:
            raise HTTPException(status_code=502, detail="OAuth response is missing ChatGPT account_id.")

        now = int(time.time() * 1000)
        label = str(payload.get("label") or f"ChatGPT {time.strftime('%Y-%m-%d %H:%M')}")[:100]
        expires_at = now + int(tokens.get("expires_in", 3600)) * 1000
        with runtime.db() as connection:
            connection.execute(
                "INSERT INTO chatgpt_accounts "
                "(id,label,account_id,access_token_enc,refresh_token_enc,id_token_enc,expires_at,status,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)",
                (
                    str(uuid.uuid4()), label, account_id,
                    runtime.encrypt_token(access_token), runtime.encrypt_token(refresh_token),
                    runtime.encrypt_token(id_token) if isinstance(id_token, str) else None,
                    expires_at, now, now,
                ),
            )
            connection.execute(
                "UPDATE device_login_sessions SET status='completed', updated_at=%s WHERE id=%s",
                (now, login_id),
            )
        return {"login_id": login_id, "status": "completed"}

    def responses(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
        runtime.authorize(authorization, x_api_key)
        upstream_payload = {**payload, "store": False, "stream": True}
        response = runtime.upstream_request(upstream_payload)
        return upstream_response(runtime, response)

    def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
        runtime.authorize(authorization, x_api_key)
        upstream_payload = build_chat_completions_payload(payload)
        response = runtime.upstream_request(upstream_payload)
        if bool(payload.get("stream", False)):
            return upstream_response(runtime, response)
        return aggregate_chat_completion(response, str(payload.get("model") or "gpt-5.4"), str(upstream_payload["model"]))

    runtime.parse_device_auth_payload = parse_json_payload
    runtime.classify_device_auth_response = classify_device_auth_response
    runtime.normalize_codex_model = normalize_codex_model
    runtime.build_chat_completions_payload = build_chat_completions_payload
    runtime.aggregate_chat_completion = aggregate_chat_completion
    runtime.upstream_response = lambda response: upstream_response(runtime, response)
    runtime.app.add_api_route("/auth/device/poll", device_poll, methods=["POST"])
    runtime.app.add_api_route("/v1/responses", responses, methods=["POST"])
    runtime.app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
