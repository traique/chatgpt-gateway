from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import HTTPException, Request

PENDING_DEVICE_AUTH_CODES = frozenset({
    "deviceauth_authorization_pending",
    "authorization_pending",
    "pending",
})


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


def install(runtime: Any) -> None:
    original_routes = runtime.app.router.routes
    runtime.app.router.routes[:] = [
        route
        for route in original_routes
        if not (
            getattr(route, "path", None) == "/auth/device/poll"
            and "POST" in getattr(route, "methods", set())
        )
    ]

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
                    str(uuid.uuid4()),
                    label,
                    account_id,
                    runtime.encrypt_token(access_token),
                    runtime.encrypt_token(refresh_token),
                    runtime.encrypt_token(id_token) if isinstance(id_token, str) else None,
                    expires_at,
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE device_login_sessions SET status='completed', updated_at=%s WHERE id=%s",
                (now, login_id),
            )

        return {"login_id": login_id, "status": "completed"}

    runtime.parse_device_auth_payload = parse_json_payload
    runtime.classify_device_auth_response = classify_device_auth_response
    runtime.app.add_api_route("/auth/device/poll", device_poll, methods=["POST"])
