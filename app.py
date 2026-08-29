from __future__ import annotations

import base64
import json
import time
import uuid

from curl_cffi import requests
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from faable.app import app
from faable import app as gateway


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/auth", status_code=307)


def extract_account_id(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except Exception:
        return None

    direct = payload.get("chatgpt_account_id") or payload.get("account_id")
    if isinstance(direct, str) and direct:
        return direct

    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id") or auth.get("account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
        organizations = auth.get("organizations")
        if isinstance(organizations, list) and organizations:
            first = organizations[0]
            if isinstance(first, dict) and isinstance(first.get("id"), str) and first["id"]:
                return first["id"]

    organizations = payload.get("organizations")
    if isinstance(organizations, list) and organizations:
        first = organizations[0]
        if isinstance(first, dict) and isinstance(first.get("id"), str) and first["id"]:
            return first["id"]

    return None


async def device_poll_override(request: Request) -> JSONResponse:
    gateway.require_admin(request)
    gateway.database_required()
    payload = await request.json()
    login_id = payload.get("login_id")
    if not isinstance(login_id, str):
        return JSONResponse({"detail": "login_id is required."}, status_code=400)

    with gateway.db() as connection:
        row = connection.execute(
            "SELECT id, device_auth_id, user_code, expires_at, status FROM device_login_sessions WHERE id=%s",
            (login_id,),
        ).fetchone()

    if not row:
        return JSONResponse({"detail": "Login session not found."}, status_code=404)
    if row[4] != "pending":
        return JSONResponse({"login_id": login_id, "status": str(row[4])})
    if int(row[3]) <= int(time.time() * 1000):
        with gateway.db() as connection:
            connection.execute(
                "UPDATE device_login_sessions SET status='expired', updated_at=%s WHERE id=%s",
                (int(time.time() * 1000), login_id),
            )
        return JSONResponse({"login_id": login_id, "status": "expired"})

    response = requests.post(
        f"{gateway.CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/token",
        headers=gateway.device_auth_headers(),
        json={"device_auth_id": row[1], "user_code": row[2]},
        impersonate="chrome120",
        timeout=30,
    )
    if response.status_code in (403, 404):
        return JSONResponse({"login_id": login_id, "status": "pending"})
    if not response.ok:
        with gateway.db() as connection:
            connection.execute(
                "UPDATE device_login_sessions SET status='failed', updated_at=%s WHERE id=%s",
                (int(time.time() * 1000), login_id),
            )
        return JSONResponse({"detail": f"Device login failed: {gateway.read_error(response)}"}, status_code=502)

    auth_payload = response.json()
    authorization_code = auth_payload.get("authorization_code")
    code_verifier = auth_payload.get("code_verifier")
    if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
        return JSONResponse({"detail": "Device login returned an invalid authorization payload."}, status_code=502)

    token_response = requests.post(
        f"{gateway.CHATGPT_AUTH_BASE_URL}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": "https://auth.openai.com/deviceauth/callback",
            "client_id": gateway.CHATGPT_OAUTH_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"content-type": "application/x-www-form-urlencoded", "user-agent": gateway.CODEX_USER_AGENT},
        impersonate="chrome120",
        timeout=30,
    )
    if not token_response.ok:
        return JSONResponse({"detail": f"OAuth token exchange failed: {gateway.read_error(token_response)}"}, status_code=502)

    tokens = token_response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    id_token = tokens.get("id_token")
    account_id = extract_account_id(id_token or "") or extract_account_id(access_token or "")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or not account_id:
        return JSONResponse({"detail": "OAuth response is missing ChatGPT account ID or required credentials."}, status_code=502)

    now = int(time.time() * 1000)
    label = str(payload.get("label") or f"ChatGPT {time.strftime('%Y-%m-%d %H:%M')}")[:100]
    with gateway.db() as connection:
        connection.execute(
            "INSERT INTO chatgpt_accounts (id,label,account_id,access_token_enc,refresh_token_enc,id_token_enc,expires_at,status,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)",
            (
                str(uuid.uuid4()), label, account_id,
                gateway.encrypt_token(access_token), gateway.encrypt_token(refresh_token),
                gateway.encrypt_token(id_token) if isinstance(id_token, str) else None,
                now + int(tokens.get("expires_in", 3600)) * 1000, now, now,
            ),
        )
        connection.execute(
            "UPDATE device_login_sessions SET status='completed', updated_at=%s WHERE id=%s",
            (now, login_id),
        )
    return JSONResponse({"login_id": login_id, "status": "completed"})


@app.middleware("http")
async def auth_device_poll_compat(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/auth/device/poll":
        try:
            return await device_poll_override(request)
        except Exception as error:
            return JSONResponse({"detail": f"Device login processing failed: {error}"}, status_code=502)
    return await call_next(request)


__all__ = ["app"]
