from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias, cast
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from curl_cffi import requests as curl_requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

CHATGPT_AUTH_BASE_URL: Final[str] = "https://auth.openai.com"
CHATGPT_CODEX_BASE_URL: Final[str] = "https://chatgpt.com"
CHATGPT_RESPONSES_PATH: Final[str] = "/backend-api/codex/responses"
CHATGPT_MODELS_PATH: Final[str] = "/backend-api/codex/models"
CHATGPT_ROBOTS_PATH: Final[str] = "/robots.txt"
CHATGPT_OAUTH_CLIENT_ID: Final[str] = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_DEVICE_URL: Final[str] = f"{CHATGPT_AUTH_BASE_URL}/codex/device"
CHATGPT_DEVICE_REDIRECT_URI: Final[str] = f"{CHATGPT_AUTH_BASE_URL}/deviceauth/callback"
UPSTREAM_TIMEOUT_SECONDS: Final[float] = 120.0
DEVICE_LOGIN_TTL_SECONDS: Final[int] = 900
DEFAULT_DEVICE_POLL_SECONDS: Final[int] = 5
DATABASE_PATH: Final[str] = os.getenv("DATABASE_PATH", "/tmp/chatgpt-gateway.sqlite3")
Role: TypeAlias = Literal["system", "developer", "user", "assistant", "tool"]

app = FastAPI(title="ChatGPT Gateway", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, label TEXT NOT NULL, account_id TEXT NOT NULL, access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, id_token TEXT, expires_at INTEGER NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS admin_sessions (token TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS device_sessions (id TEXT PRIMARY KEY, device_auth_id TEXT NOT NULL, user_code TEXT NOT NULL, interval_seconds INTEGER NOT NULL, expires_at INTEGER NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL)"
    )
    connection.commit()
    return connection


def encryption_key() -> bytes:
    value = os.getenv("CHATGPT_TOKEN_ENCRYPTION_KEY", "").strip()
    if not value:
        raise RuntimeError("CHATGPT_TOKEN_ENCRYPTION_KEY is not configured.")
    try:
        Fernet(value.encode())
    except Exception as exc:
        raise RuntimeError("CHATGPT_TOKEN_ENCRYPTION_KEY is invalid.") from exc
    return value.encode()


def encrypt(value: str) -> str:
    return Fernet(encryption_key()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return Fernet(encryption_key()).decrypt(value.encode()).decode()


def upstream_headers(*, token: str | None = None, account_id: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "originator": "Codex Desktop",
        "user-agent": "Codex Desktop/26.707.31428 (Windows; x64)",
        "accept-language": "en-US,en;q=0.9",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


def json_response(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    response = JSONResponse(payload, status_code=status)
    response.headers["cache-control"] = "no-store"
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


def error_response(error_type: str, message: str, status: int) -> JSONResponse:
    return json_response({"error": {"type": error_type, "message": message}}, status)


def require_gateway_key(request: Request) -> bool:
    configured = os.getenv("GATEWAY_API_KEY", "").strip()
    if not configured:
        return False
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    return hmac.compare_digest(bearer, configured) or hmac.compare_digest(request.headers.get("x-api-key", "").strip(), configured)


def session_secret() -> str:
    value = os.getenv("SESSION_SECRET", "").strip()
    if not value:
        raise RuntimeError("SESSION_SECRET is not configured.")
    return value


def create_admin_session() -> str:
    token = uuid.uuid4().hex
    expires_at = int(time.time()) + 12 * 60 * 60
    connection = db()
    try:
        connection.execute("INSERT INTO admin_sessions (token, expires_at) VALUES (?, ?)", (token, expires_at))
        connection.commit()
    finally:
        connection.close()
    signature = hmac.new(session_secret().encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{signature}"


def admin_session_valid(request: Request) -> bool:
    raw = request.cookies.get("cg_admin_session", "")
    token, separator, signature = raw.partition(".")
    if not separator or not token or not signature:
        return False
    expected = hmac.new(session_secret().encode(), token.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    connection = db()
    try:
        row = connection.execute("SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)).fetchone()
        return row is not None and int(row["expires_at"]) > int(time.time())
    finally:
        connection.close()


def admin_cookie(token: str) -> str:
    return f"cg_admin_session={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=43200"


@dataclass(frozen=True)
class ChatGptAccount:
    id: str
    label: str
    account_id: str
    access_token: str
    refresh_token: str
    expires_at: int


def active_account() -> ChatGptAccount | None:
    connection = db()
    try:
        row = connection.execute(
            "SELECT id, label, account_id, access_token, refresh_token, expires_at FROM accounts WHERE status = 'active' ORDER BY expires_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return ChatGptAccount(
            id=str(row["id"]),
            label=str(row["label"]),
            account_id=str(row["account_id"]),
            access_token=decrypt(str(row["access_token"])),
            refresh_token=decrypt(str(row["refresh_token"])),
            expires_at=int(row["expires_at"]),
        )
    finally:
        connection.close()


def decode_jwt_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        value = json.loads(payload.decode())
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def extract_account_id(token: str) -> str | None:
    payload = decode_jwt_payload(token)
    direct = payload.get("chatgpt_account_id")
    if isinstance(direct, str) and direct:
        return direct
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        nested = auth.get("chatgpt_account_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def start_device_login() -> dict[str, object]:
    response = curl_requests.post(
        f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/usercode",
        headers={"content-type": "application/json", "user-agent": "codex_cli_rs/0.0.0", "originator": "codex_cli_rs"},
        json={"client_id": CHATGPT_OAUTH_CLIENT_ID},
        impersonate="chrome120",
        timeout=UPSTREAM_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Device login initialization failed: HTTP {response.status_code} {response.text[:200]}")
    payload = cast(dict[str, object], response.json())
    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code") or payload.get("usercode")
    interval = payload.get("interval", DEFAULT_DEVICE_POLL_SECONDS)
    if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
        raise RuntimeError("Device login returned an invalid payload.")
    interval_seconds = max(int(interval), 3) if isinstance(interval, (int, str)) else DEFAULT_DEVICE_POLL_SECONDS
    session_id = str(uuid.uuid4())
    now = int(time.time())
    connection = db()
    try:
        connection.execute(
            "INSERT INTO device_sessions (id, device_auth_id, user_code, interval_seconds, expires_at, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (session_id, device_auth_id, user_code, interval_seconds, now + DEVICE_LOGIN_TTL_SECONDS, now),
        )
        connection.commit()
    finally:
        connection.close()
    return {"login_id": session_id, "verification_url": CHATGPT_DEVICE_URL, "user_code": user_code, "interval_seconds": interval_seconds, "expires_at": now + DEVICE_LOGIN_TTL_SECONDS}


def poll_device_login(login_id: str, label: str) -> dict[str, object]:
    connection = db()
    try:
        row = connection.execute("SELECT * FROM device_sessions WHERE id = ?", (login_id,)).fetchone()
        if row is None:
            raise RuntimeError("Login session not found.")
        if str(row["status"]) != "pending":
            return {"login_id": login_id, "status": str(row["status"])}
        if int(row["expires_at"]) <= int(time.time()):
            connection.execute("UPDATE device_sessions SET status = 'expired' WHERE id = ?", (login_id,))
            connection.commit()
            return {"login_id": login_id, "status": "expired"}
        device_auth_id = str(row["device_auth_id"])
        user_code = str(row["user_code"])
    finally:
        connection.close()

    response = curl_requests.post(
        f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/token",
        headers={"content-type": "application/json", "user-agent": "codex_cli_rs/0.0.0", "originator": "codex_cli_rs"},
        json={"device_auth_id": device_auth_id, "user_code": user_code},
        impersonate="chrome120",
        timeout=UPSTREAM_TIMEOUT_SECONDS,
    )
    if response.status_code in (403, 404):
        return {"login_id": login_id, "status": "pending"}
    if not response.ok:
        raise RuntimeError(f"Device login failed: HTTP {response.status_code} {response.text[:200]}")
    payload = cast(dict[str, object], response.json())
    authorization_code = payload.get("authorization_code")
    code_verifier = payload.get("code_verifier")
    if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
        raise RuntimeError("Device login returned an invalid authorization payload.")

    token_response = curl_requests.post(
        f"{CHATGPT_AUTH_BASE_URL}/oauth/token",
        headers={"content-type": "application/x-www-form-urlencoded", "user-agent": "codex_cli_rs/0.0.0"},
        data=urlencode({"grant_type": "authorization_code", "code": authorization_code, "redirect_uri": CHATGPT_DEVICE_REDIRECT_URI, "client_id": CHATGPT_OAUTH_CLIENT_ID, "code_verifier": code_verifier}),
        impersonate="chrome120",
        timeout=UPSTREAM_TIMEOUT_SECONDS,
    )
    if not token_response.ok:
        raise RuntimeError(f"OAuth token exchange failed: HTTP {token_response.status_code} {token_response.text[:200]}")
    tokens = cast(dict[str, object], token_response.json())
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    id_token = tokens.get("id_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise RuntimeError("OAuth response is missing access_token or refresh_token.")
    account_id = extract_account_id(str(id_token)) if isinstance(id_token, str) else extract_account_id(access_token)
    if not account_id:
        raise RuntimeError("ChatGPT token response did not contain an account ID.")
    expires_in = int(tokens.get("expires_in", 3600))
    now = int(time.time())
    connection = db()
    try:
        connection.execute("UPDATE accounts SET status = 'disabled' WHERE status = 'active'")
        connection.execute(
            "INSERT INTO accounts (id, label, account_id, access_token, refresh_token, id_token, expires_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (str(uuid.uuid4()), label.strip() or "ChatGPT", account_id, encrypt(access_token), encrypt(refresh_token), encrypt(str(id_token)) if isinstance(id_token, str) else None, now + expires_in, now),
        )
        connection.execute("UPDATE device_sessions SET status = 'completed' WHERE id = ?", (login_id,))
        connection.commit()
    finally:
        connection.close()
    return {"login_id": login_id, "status": "completed"}


@app.get("/")
def home() -> Response:
    return Response(status_code=307, headers={"location": "/auth"})


@app.get("/health")
def health() -> dict[str, object]:
    configured = bool(os.getenv("GATEWAY_API_KEY", "").strip() and os.getenv("CHATGPT_TOKEN_ENCRYPTION_KEY", "").strip())
    return {"ok": configured, "runtime": "faable", "transport": "curl_cffi", "device_login": True}


@app.get("/auth", response_class=HTMLResponse)
def auth_page() -> str:
    return """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>ChatGPT Gateway</title><style>body{font-family:system-ui;margin:0;background:#111;color:#eee}main{max-width:520px;margin:auto;padding:28px}button{padding:14px 18px;border:0;border-radius:12px;background:#7c5cff;color:#fff;font-weight:700}input{padding:12px;border-radius:10px;border:1px solid #444;background:#222;color:#fff;width:100%;box-sizing:border-box;margin:8px 0}a{color:#9b8cff}.card{background:#1c1c1c;padding:20px;border-radius:18px;margin-top:18px}.hidden{display:none}code{word-break:break-all}</style></head><body><main><h1>ChatGPT Gateway</h1><div id='login' class='card'><h2>Admin Login</h2><input id='username' placeholder='Username'><input id='password' type='password' placeholder='Password'><button onclick='adminLogin()'>Đăng nhập</button></div><div id='gateway' class='card hidden'><h2>ChatGPT</h2><input id='label' placeholder='Tên account, ví dụ: primary'><p id='status'>Bấm bắt đầu để lấy device code.</p><button onclick='startLogin()'>Đăng nhập ChatGPT</button><div id='device' class='hidden'><p>Mở:</p><p><a id='url' target='_blank'></a></p><p>Nhập mã:</p><h2><code id='code'></code></h2></div></div><script>let timer;const $=id=>document.getElementById(id);async function adminLogin(){const r=await fetch('/auth/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:$('username').value,password:$('password').value})});const p=await r.json();if(!r.ok){alert(p.error?.message||'Đăng nhập thất bại');return}showGateway()}async function check(){const r=await fetch('/auth/me');if(r.ok){const p=await r.json();if(p.authenticated)showGateway()}}function showGateway(){$('login').classList.add('hidden');$('gateway').classList.remove('hidden')}async function startLogin(){const r=await fetch('/api/chatgpt/device/start',{method:'POST'});const p=await r.json();if(!r.ok){$('status').textContent=p.error?.message||'Không thể bắt đầu';return}$('device').classList.remove('hidden');$('url').href=p.verification_url;$('url').textContent=p.verification_url;$('code').textContent=p.user_code;$('status').textContent='Đăng nhập ChatGPT rồi quay lại đây.';clearInterval(timer);timer=setInterval(()=>poll(p.login_id),Math.max(p.interval_seconds,3)*1000)}async function poll(id){const r=await fetch('/api/chatgpt/device/poll/'+id,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({label:$('label').value})});const p=await r.json();$('status').textContent=p.status_message||p.status;if(p.status==='completed'){clearInterval(timer);location.href='/dashboard'}}check()</script></main></body></html>"""


@app.post("/auth/login")
async def admin_login(request: Request) -> Response:
    try:
        payload = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return error_response("invalid_request_error", "Request body must be valid JSON.", 400)
    username = payload.get("username") if isinstance(payload, dict) else None
    password = payload.get("password") if isinstance(payload, dict) else None
    configured_username = os.getenv("ADMIN_USERNAME", "").strip()
    configured_password = os.getenv("ADMIN_PASSWORD", "")
    if not isinstance(username, str) or not isinstance(password, str) or not configured_username or not configured_password:
        return error_response("authentication_error", "Admin authentication is not configured.", 503)
    if not hmac.compare_digest(username, configured_username) or not hmac.compare_digest(password, configured_password):
        return error_response("authentication_error", "Sai tài khoản hoặc mật khẩu.", 401)
    token = create_admin_session()
    return json_response({"ok": True}, headers={"set-cookie": admin_cookie(token)})


@app.get("/auth/me")
def admin_me(request: Request) -> dict[str, bool]:
    return {"authenticated": admin_session_valid(request)}


@app.post("/auth/logout")
def admin_logout() -> Response:
    return Response(status_code=204, headers={"set-cookie": "cg_admin_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> Response:
    if not admin_session_valid(request):
        return Response(status_code=307, headers={"location": "/auth"})
    connection = db()
    try:
        rows = connection.execute("SELECT label, account_id, status, expires_at FROM accounts ORDER BY created_at DESC").fetchall()
    finally:
        connection.close()
    items = "".join(f"<li>{row['label']} — {row['status']} — {row['account_id']}</li>" for row in rows) or "<li>Chưa có account</li>"
    return HTMLResponse(f"<html><body style='font-family:system-ui;max-width:700px;margin:auto;padding:28px'><h1>Dashboard</h1><ul>{items}</ul><a href='/auth'>Quản lý ChatGPT</a></body></html>")


@app.post("/api/chatgpt/device/start")
def device_start(request: Request) -> JSONResponse:
    if not admin_session_valid(request):
        return error_response("authentication_error", "Admin login required.", 401)
    try:
        return json_response(start_device_login())
    except Exception as exc:
        return error_response("authentication_error", str(exc), 502)


@app.post("/api/chatgpt/device/poll/{login_id}")
async def device_poll(login_id: str, request: Request) -> JSONResponse:
    if not admin_session_valid(request):
        return error_response("authentication_error", "Admin login required.", 401)
    try:
        payload = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        payload = {}
    label = payload.get("label") if isinstance(payload, dict) and isinstance(payload.get("label"), str) else "ChatGPT"
    try:
        return json_response(poll_device_login(login_id, label))
    except Exception as exc:
        return error_response("authentication_error", str(exc), 502)


@app.get("/v1/debug/transport")
def debug_transport() -> dict[str, object]:
    response = curl_requests.get(f"{CHATGPT_CODEX_BASE_URL}{CHATGPT_ROBOTS_PATH}", impersonate="chrome120", timeout=UPSTREAM_TIMEOUT_SECONDS, allow_redirects=False)
    return {"ok": response.ok, "status": response.status_code, "content_type": response.headers.get("content-type"), "server": response.headers.get("server"), "body_prefix": response.text[:300]}


@app.get("/v1/models")
def models(request: Request) -> Response:
    if not require_gateway_key(request):
        return error_response("authentication_error", "Invalid API key.", 401)
    account = active_account()
    if account is None:
        return error_response("authentication_error", "No active ChatGPT account. Login first.", 401)
    response = curl_requests.get(f"{CHATGPT_CODEX_BASE_URL}{CHATGPT_MODELS_PATH}", headers=upstream_headers(token=account.access_token, account_id=account.account_id), impersonate="chrome120", timeout=UPSTREAM_TIMEOUT_SECONDS)
    return Response(content=response.content, status_code=response.status_code, media_type="application/json")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    if not require_gateway_key(request):
        return error_response("authentication_error", "Invalid API key.", 401)
    try:
        payload = json.loads(await request.body() or b"")
    except json.JSONDecodeError:
        return error_response("invalid_request_error", "Request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return error_response("invalid_request_error", "Request body must be an object.", 400)
    if payload.get("stream") is True:
        return error_response("invalid_request_error", "Streaming is not enabled in the first Faable adapter release.", 400)
    account = active_account()
    if account is None:
        return error_response("authentication_error", "No active ChatGPT account. Open /auth first.", 401)
    messages = payload.get("messages")
    model = payload.get("model", "chatgpt-gpt-5.6")
    if not isinstance(messages, list) or not isinstance(model, str):
        return error_response("invalid_request_error", "model and messages are required.", 400)
    upstream_payload = {"model": model, "input": messages, "store": False, "stream": False}
    if isinstance(payload.get("temperature"), (int, float)):
        upstream_payload["temperature"] = payload["temperature"]
    response = curl_requests.post(f"{CHATGPT_CODEX_BASE_URL}{CHATGPT_RESPONSES_PATH}", headers=upstream_headers(token=account.access_token, account_id=account.account_id), json=upstream_payload, impersonate="chrome120", timeout=UPSTREAM_TIMEOUT_SECONDS)
    if not response.ok:
        return Response(content=response.content, status_code=response.status_code, media_type="application/json")
    try:
        upstream = cast(dict[str, object], response.json())
        text_parts: list[str] = []
        output = upstream.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
        created = int(upstream.get("created_at", time.time()))
        result = {"id": upstream.get("id", f"chatcmpl-{uuid.uuid4().hex}"), "object": "chat.completion", "created": created, "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(text_parts)}, "finish_reason": "stop"}], "usage": upstream.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})}
        return json_response(result)
    except (ValueError, TypeError):
        return error_response("upstream_error", "ChatGPT returned an invalid JSON response.", 502)


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    if not require_gateway_key(request):
        return error_response("authentication_error", "Invalid API key.", 401)
    try:
        payload = json.loads(await request.body() or b"")
    except json.JSONDecodeError:
        return error_response("invalid_request_error", "Request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return error_response("invalid_request_error", "Request body must be an object.", 400)
    account = active_account()
    if account is None:
        return error_response("authentication_error", "No active ChatGPT account. Open /auth first.", 401)
    upstream_payload = dict(payload)
    upstream_payload["stream"] = False
    response = curl_requests.post(f"{CHATGPT_CODEX_BASE_URL}{CHATGPT_RESPONSES_PATH}", headers=upstream_headers(token=account.access_token, account_id=account.account_id), json=upstream_payload, impersonate="chrome120", timeout=UPSTREAM_TIMEOUT_SECONDS)
    return Response(content=response.content, status_code=response.status_code, media_type="application/json")
