import base64
import html
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from curl_cffi import requests
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

CHATGPT_AUTH_BASE_URL = os.getenv("CHATGPT_AUTH_BASE_URL", "https://auth.openai.com").rstrip("/")
CHATGPT_ENDPOINT = os.getenv("CHATGPT_CODEX_ENDPOINT", "https://chatgpt.com/backend-api/codex/responses")
CHATGPT_CLIENT_ID = os.getenv("CHATGPT_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
CHATGPT_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
CODEX_VERSION = os.getenv("CHATGPT_CODEX_CLIENT_VERSION", "0.144.1")
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_ORIGIN = "https://chatgpt.com"
CODEX_REFERER = "https://chatgpt.com/"
CODEX_USER_AGENT = f"codex_cli_rs/{CODEX_VERSION}"
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
TOKEN_ENCRYPTION_KEY = os.getenv("CHATGPT_TOKEN_ENCRYPTION_KEY", "")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/tmp/chatgpt-gateway.sqlite3"))
DEVICE_LOGIN_TTL_SECONDS = 900
MIN_DEVICE_POLL_INTERVAL_SECONDS = 3

app = FastAPI(title="ChatGPT Gateway", version="0.4.1")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET or secrets.token_urlsafe(32), max_age=86400, same_site="lax", https_only=True)


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, account_id TEXT NOT NULL,
            access_token_enc TEXT NOT NULL, refresh_token_enc TEXT, id_token_enc TEXT,
            expires_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_sessions (
            id TEXT PRIMARY KEY, device_auth_id TEXT NOT NULL, user_code TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
    """)
    return connection


def encryption() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        raise HTTPException(status_code=503, detail="CHATGPT_TOKEN_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode())
    except ValueError as error:
        raise HTTPException(status_code=503, detail="CHATGPT_TOKEN_ENCRYPTION_KEY is invalid.") from error


def admin_required(request: Request) -> None:
    if request.session.get("admin_authenticated") is not True:
        raise HTTPException(status_code=401, detail="Authentication required.")


def api_authorize(authorization: str | None, x_api_key: str | None) -> None:
    supplied = x_api_key or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if not GATEWAY_API_KEY or not hmac.compare_digest(supplied, GATEWAY_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key.")


def auth_headers() -> dict[str, str]:
    return {"content-type": "application/json", "user-agent": CODEX_USER_AGENT, "originator": CODEX_ORIGINATOR}


def upstream_headers(access_token: str, account_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "ChatGPT-Account-Id": account_id, "Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": CODEX_USER_AGENT, "originator": CODEX_ORIGINATOR, "Version": CODEX_VERSION, "Origin": CODEX_ORIGIN, "Referer": CODEX_REFERER}


def decode_account_id(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("chatgpt_account_id"), str):
        return payload["chatgpt_account_id"]
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict) and isinstance(auth.get("chatgpt_account_id"), str):
        return auth["chatgpt_account_id"]
    organizations = payload.get("organizations")
    if isinstance(organizations, list) and organizations and isinstance(organizations[0], dict) and isinstance(organizations[0].get("id"), str):
        return organizations[0]["id"]
    return None


def read_upstream_error(response: Any) -> str:
    body = response.text[:500]
    return f"HTTP {response.status_code}: {body}" if body else f"HTTP {response.status_code}."


def render_page(title: str, body: str) -> HTMLResponse:
    document = f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#111827;color:#f9fafb;margin:0}}main{{max-width:760px;margin:48px auto;padding:24px}}.card{{background:#1f2937;border:1px solid #374151;border-radius:16px;padding:24px;margin-bottom:16px}}input,button{{font:inherit;border-radius:10px;padding:12px}}input{{width:100%;box-sizing:border-box;background:#111827;color:#fff;border:1px solid #4b5563;margin:8px 0 14px}}button{{border:0;cursor:pointer;background:#fff;color:#111827;font-weight:600}}a{{color:#93c5fd}}.muted{{color:#9ca3af}}code{{background:#111827;padding:4px 6px;border-radius:6px}}</style></head><body><main><h1>ChatGPT Gateway</h1>{body}</main></body></html>"
    return HTMLResponse(document)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse | RedirectResponse:
    return RedirectResponse("/dashboard" if request.session.get("admin_authenticated") is True else "/auth", status_code=302)


@app.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request) -> HTMLResponse | RedirectResponse:
    if request.session.get("admin_authenticated") is True:
        return RedirectResponse("/dashboard", status_code=302)
    return render_page("Login", "<section class='card'><h2>Admin login</h2><form method='post' action='/api/auth/login'><label>Username</label><input name='username' autocomplete='username' required><label>Password</label><input name='password' type='password' autocomplete='current-password' required><button type='submit'>Sign in</button></form></section>")


@app.post("/api/auth/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD is not configured.")
    if not hmac.compare_digest(username, ADMIN_USERNAME) or not hmac.compare_digest(password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    request.session.clear()
    request.session["admin_authenticated"] = True
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/api/auth/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    if request.session.get("admin_authenticated") is not True:
        return RedirectResponse("/auth", status_code=302)
    connection = database()
    accounts = connection.execute("SELECT id,label,account_id,status,expires_at FROM accounts ORDER BY created_at DESC").fetchall()
    account_rows = "".join(f"<li>{html.escape(row['label'])} · <code>{html.escape(row['account_id'])}</code> · {html.escape(row['status'])}</li>" for row in accounts) or "<li class='muted'>No ChatGPT accounts connected.</li>"
    body = f"<section class='card'><h2>ChatGPT accounts</h2><ul>{account_rows}</ul><button onclick='startDeviceLogin()'>Login ChatGPT</button><p id='status' class='muted'></p></section><section class='card'><h2>Gateway</h2><p class='muted'>Transport: curl_cffi / Chrome 120</p><p><a href='/v1/debug/transport' target='_blank'>Open transport diagnostics</a></p><form method='post' action='/api/auth/logout'><button type='submit'>Sign out</button></form></section><script>async function startDeviceLogin(){{const response=await fetch('/api/chatgpt/device/start',{{method:'POST'}});const payload=await response.json();if(!response.ok){{document.querySelector('#status').textContent=payload.detail||'Login failed';return}}document.querySelector('#status').innerHTML='Code: <strong>'+payload.user_code+'</strong> · <a href="'+payload.verification_url+'" target="_blank">Open ChatGPT login</a>';poll(payload.session_id,payload.interval_seconds)}}async function poll(id,interval){{await new Promise(r=>setTimeout(r,interval*1000));const response=await fetch('/api/chatgpt/device/poll/'+id,{{method:'POST'}});const payload=await response.json();document.querySelector('#status').textContent=payload.status_message||payload.status;if(payload.status==='pending')return poll(id,interval);if(payload.status==='completed')location.reload()}}</script>"
    return render_page("Dashboard", body)


@app.post("/api/chatgpt/device/start")
def start_device_login(request: Request) -> JSONResponse:
    admin_required(request)
    response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/usercode", headers=auth_headers(), json={"client_id": CHATGPT_CLIENT_ID}, impersonate="chrome120", timeout=30)
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Device login initialization failed: {read_upstream_error(response)}")
    payload = response.json()
    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code") or payload.get("usercode")
    if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
        raise HTTPException(status_code=502, detail="Device login returned an invalid payload.")
    interval_seconds = max(int(payload.get("interval", 5)), MIN_DEVICE_POLL_INTERVAL_SECONDS)
    session_id = str(uuid.uuid4())
    now = int(time.time())
    connection = database()
    connection.execute("INSERT INTO login_sessions VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)", (session_id, device_auth_id, user_code, interval_seconds, now + DEVICE_LOGIN_TTL_SECONDS, now, now))
    connection.commit()
    return JSONResponse({"session_id": session_id, "user_code": user_code, "interval_seconds": interval_seconds, "expires_at": now + DEVICE_LOGIN_TTL_SECONDS, "verification_url": "https://auth.openai.com/codex/device"})


@app.post("/api/chatgpt/device/poll/{session_id}")
def poll_device_login(request: Request, session_id: str) -> JSONResponse:
    admin_required(request)
    connection = database()
    session = connection.execute("SELECT * FROM login_sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Login session not found.")
    if session["status"] != "pending":
        return JSONResponse({"status": session["status"], "status_message": f"Login {session['status']}."})
    if int(time.time()) >= session["expires_at"]:
        connection.execute("UPDATE login_sessions SET status='expired',updated_at=? WHERE id=?", (int(time.time()), session_id))
        connection.commit()
        return JSONResponse({"status": "expired", "status_message": "Device code expired."})
    response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/token", headers=auth_headers(), json={"device_auth_id": session["device_auth_id"], "user_code": session["user_code"]}, impersonate="chrome120", timeout=30)
    if response.status_code in (403, 404):
        return JSONResponse({"status": "pending", "status_message": "Waiting for ChatGPT login..."})
    if not response.ok:
        connection.execute("UPDATE login_sessions SET status='failed',updated_at=? WHERE id=?", (int(time.time()), session_id))
        connection.commit()
        raise HTTPException(status_code=502, detail=f"Device login failed: {read_upstream_error(response)}")
    payload = response.json()
    authorization_code = payload.get("authorization_code")
    code_verifier = payload.get("code_verifier")
    if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
        raise HTTPException(status_code=502, detail="Device login returned an invalid authorization payload.")
    token_response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/oauth/token", headers={"content-type": "application/x-www-form-urlencoded", "user-agent": CODEX_USER_AGENT}, data={"grant_type": "authorization_code", "code": authorization_code, "redirect_uri": CHATGPT_REDIRECT_URI, "client_id": CHATGPT_CLIENT_ID, "code_verifier": code_verifier}, impersonate="chrome120", timeout=30)
    if not token_response.ok:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {read_upstream_error(token_response)}")
    tokens = token_response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    id_token = tokens.get("id_token")
    account_id = decode_account_id(id_token or access_token or "")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or not account_id:
        raise HTTPException(status_code=502, detail="OAuth token response is missing required ChatGPT account data.")
    now = int(time.time())
    cipher = encryption()
    connection.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)", (str(uuid.uuid4()), f"ChatGPT {account_id[:8]}", account_id, cipher.encrypt(access_token).decode(), cipher.encrypt(refresh_token).decode(), cipher.encrypt(id_token).decode() if isinstance(id_token, str) else None, now + int(tokens.get("expires_in", 3600)), now, now))
    connection.execute("UPDATE login_sessions SET status='completed',updated_at=? WHERE id=?", (now, session_id))
    connection.commit()
    return JSONResponse({"status": "completed", "status_message": "ChatGPT account connected."})


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": bool(GATEWAY_API_KEY and ADMIN_PASSWORD and TOKEN_ENCRYPTION_KEY), "runtime": "faable-curl-cffi", "transport": "curl_cffi", "impersonate": "chrome120"}


def active_account() -> tuple[str, str]:
    connection = database()
    row = connection.execute("SELECT access_token_enc,account_id FROM accounts WHERE status='active' ORDER BY expires_at DESC LIMIT 1").fetchone()
    if not row:
        raise HTTPException(status_code=503, detail="No active ChatGPT account is configured.")
    return encryption().decrypt(row["access_token_enc"].encode()).decode(), row["account_id"]


def upstream_request(payload: dict[str, Any]) -> Any:
    access_token, account_id = active_account()
    try:
        return requests.post(CHATGPT_ENDPOINT, headers=upstream_headers(access_token, account_id), json=payload, impersonate="chrome120", timeout=120, stream=True)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"ChatGPT transport failed: {error}") from error


def upstream_response(response: Any) -> StreamingResponse:
    if response.status_code >= 400:
        content_type = response.headers.get("content-type", "")
        message = f"ChatGPT upstream returned an HTML block page (HTTP {response.status_code})." if "text/html" in content_type.lower() else read_upstream_error(response)
        raise HTTPException(status_code=response.status_code, detail=message)
    return StreamingResponse(response.iter_content(chunk_size=4096), media_type="text/event-stream")


@app.get("/v1/models")
def models(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    api_authorize(authorization, x_api_key)
    return {"object": "list", "data": [{"id": "chatgpt-gpt-5.6", "object": "model", "created": int(time.time()), "owned_by": "openai-chatgpt"}]}


@app.get("/v1/debug/transport")
def debug_transport(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> JSONResponse:
    api_authorize(authorization, x_api_key)
    response = requests.get("https://chatgpt.com/robots.txt", headers={"User-Agent": CODEX_USER_AGENT}, impersonate="chrome120", timeout=30)
    return JSONResponse({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runtime": "faable-curl-cffi", "checks": [{"variant": "curl-cffi-chrome120", "status": response.status_code, "content_type": response.headers.get("content-type"), "body_prefix": response.text[:300]}]})


@app.post("/v1/responses")
def responses(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    api_authorize(authorization, x_api_key)
    return upstream_response(upstream_request({**payload, "store": False, "stream": True}))


@app.post("/v1/chat/completions")
def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    api_authorize(authorization, x_api_key)
    messages = payload.get("messages", [])
    input_items = [{"role": message.get("role", "user"), "content": [{"type": "input_text", "text": str(message.get("content", ""))}]} for message in messages]
    return upstream_response(upstream_request({"model": str(payload.get("model", "gpt-5.4")).removeprefix("chatgpt-"), "input": input_items, "stream": True, "store": False}))
