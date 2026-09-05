from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import time
import uuid
from typing import Any

import psycopg
from cryptography.fernet import Fernet
from curl_cffi import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

CHATGPT_AUTH_BASE_URL = os.getenv("CHATGPT_AUTH_BASE_URL", "https://auth.openai.com")
CHATGPT_ENDPOINT = os.getenv("CHATGPT_CODEX_ENDPOINT", "https://chatgpt.com/backend-api/codex/responses")
CHATGPT_OAUTH_CLIENT_ID = os.getenv("CHATGPT_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()
CHATGPT_ACCESS_TOKEN = os.getenv("CHATGPT_ACCESS_TOKEN", "")
CHATGPT_ACCOUNT_ID = os.getenv("CHATGPT_ACCOUNT_ID", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
TOKEN_ENCRYPTION_KEY = os.getenv("CHATGPT_TOKEN_ENCRYPTION_KEY", "")
CODEX_VERSION = os.getenv("CHATGPT_CODEX_CLIENT_VERSION", "0.144.1")
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_ORIGIN = "https://chatgpt.com"
CODEX_REFERER = "https://chatgpt.com/"
CODEX_USER_AGENT = "codex_cli_rs/0.144.1"
DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"

app = FastAPI(title="chatgpt-gateway", version="0.4.0", docs_url=None, redoc_url=None)
if SESSION_SECRET:
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=43200, same_site="lax", https_only=True)


def normalize_gateway_api_key(value: str) -> str:
    return value.strip()


def database_required() -> None:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured.")


def db() -> psycopg.Connection[Any]:
    database_required()
    return psycopg.connect(DATABASE_URL, autocommit=True)


def initialize_database() -> None:
    if not DATABASE_URL:
        return
    with db() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS chatgpt_accounts (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                account_id TEXT NOT NULL,
                access_token_enc TEXT NOT NULL,
                refresh_token_enc TEXT NOT NULL,
                id_token_enc TEXT,
                expires_at BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                last_error TEXT,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS device_login_sessions (
                id TEXT PRIMARY KEY,
                device_auth_id TEXT NOT NULL,
                user_code TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL,
                expires_at BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL
            )
        """)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def require_admin(request: Request) -> None:
    if not SESSION_SECRET:
        raise HTTPException(status_code=503, detail="SESSION_SECRET is not configured.")
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Admin login required.")


lookup_client_policy: Any = None  # attached by faable.provider_routing.install
set_client_policy: Any = None  # attached by faable.provider_routing.install


def authorize(authorization: str | None, x_api_key: str | None) -> None:
    supplied = normalize_gateway_api_key(x_api_key) if x_api_key else ""
    if not supplied and authorization:
        normalized_authorization = authorization.strip()
        scheme, separator, token = normalized_authorization.partition(" ")
        supplied = normalize_gateway_api_key(token) if separator and scheme.lower() == "bearer" else normalized_authorization

    if GATEWAY_API_KEY and hmac.compare_digest(supplied, GATEWAY_API_KEY):
        if set_client_policy:
            set_client_policy(None)
        return
    policy = lookup_client_policy(supplied) if (lookup_client_policy and supplied) else None
    if policy is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    if set_client_policy:
        set_client_policy(policy)


def token_cipher() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        raise HTTPException(status_code=503, detail="CHATGPT_TOKEN_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode())
    except Exception as error:
        raise HTTPException(status_code=503, detail="CHATGPT_TOKEN_ENCRYPTION_KEY is invalid.") from error


def encrypt_token(value: str) -> str:
    return token_cipher().encrypt(value.encode()).decode()


def decrypt_token(value: str) -> str:
    return token_cipher().decrypt(value.encode()).decode()


def upstream_headers(access_token: str, account_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "ChatGPT-Account-Id": account_id,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": CODEX_USER_AGENT,
        "originator": CODEX_ORIGINATOR,
        "Version": CODEX_VERSION,
        "Origin": CODEX_ORIGIN,
        "Referer": CODEX_REFERER,
    }


def get_active_token() -> tuple[str, str]:
    if not DATABASE_URL:
        if not CHATGPT_ACCESS_TOKEN or not CHATGPT_ACCOUNT_ID:
            raise HTTPException(status_code=503, detail="ChatGPT access credentials are not configured.")
        return CHATGPT_ACCESS_TOKEN, CHATGPT_ACCOUNT_ID

    with db() as connection:
        row = connection.execute("SELECT id, account_id, access_token_enc, refresh_token_enc, id_token_enc, expires_at FROM chatgpt_accounts WHERE status = 'active' ORDER BY expires_at DESC LIMIT 1").fetchone()
    if not row:
        raise HTTPException(status_code=503, detail="No active ChatGPT account. Open /auth and sign in first.")
    account_id = str(row[1])
    if int(row[5]) > int(time.time() * 1000) + 300_000:
        return decrypt_token(str(row[2])), account_id
    return refresh_account(row)


def refresh_account(row: tuple[Any, ...]) -> tuple[str, str]:
    refresh_token = decrypt_token(str(row[3]))
    response = requests.post(
        f"{CHATGPT_AUTH_BASE_URL}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CHATGPT_OAUTH_CLIENT_ID},
        headers={"content-type": "application/x-www-form-urlencoded", "user-agent": CODEX_USER_AGENT},
        impersonate="chrome120",
        timeout=30,
    )
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"ChatGPT token refresh failed: HTTP {response.status_code}.")
    payload = response.json()
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=502, detail="ChatGPT token refresh returned no access_token.")
    new_refresh_token = payload.get("refresh_token") or refresh_token
    expires_at = int(time.time() * 1000) + int(payload.get("expires_in", 3600)) * 1000
    with db() as connection:
        connection.execute("UPDATE chatgpt_accounts SET access_token_enc = %s, refresh_token_enc = %s, expires_at = %s, last_error = NULL, updated_at = %s WHERE id = %s", (encrypt_token(access_token), encrypt_token(new_refresh_token), expires_at, int(time.time() * 1000), row[0]))
    return access_token, str(row[1])


def upstream_request(payload: dict[str, Any]) -> Any:
    access_token, account_id = get_active_token()
    try:
        return requests.post(CHATGPT_ENDPOINT, headers=upstream_headers(access_token, account_id), json=payload, impersonate="chrome120", timeout=120, stream=True)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"ChatGPT transport failed: {error}") from error


def device_auth_headers() -> dict[str, str]:
    return {"content-type": "application/json", "user-agent": CODEX_USER_AGENT, "originator": CODEX_ORIGINATOR}


def read_error(response: Any) -> str:
    try:
        payload = response.json()
        return str(payload.get("error_description") or payload.get("error") or f"HTTP {response.status_code}")
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:200]}"


def extract_account_id(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        decoded = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    direct = payload.get("chatgpt_account_id")
    if isinstance(direct, str) and direct:
        return direct
    account_id = payload.get("account_id")
    if isinstance(account_id, str) and account_id:
        return account_id
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        nested = auth.get("chatgpt_account_id")
        if isinstance(nested, str) and nested:
            return nested
    organizations = payload.get("organizations")
    if isinstance(organizations, list):
        for organization in organizations:
            if isinstance(organization, dict):
                organization_id = organization.get("id")
                if isinstance(organization_id, str) and organization_id:
                    return organization_id
    return None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": bool(GATEWAY_API_KEY and (DATABASE_URL or (CHATGPT_ACCESS_TOKEN and CHATGPT_ACCOUNT_ID))), "runtime": "faable-curl-cffi", "transport": "curl_cffi", "impersonate": "chrome120", "database_configured": bool(DATABASE_URL), "chatgpt_login_enabled": bool(DATABASE_URL and SESSION_SECRET and TOKEN_ENCRYPTION_KEY)}


@app.get("/auth", response_class=HTMLResponse)
def admin_page() -> str:
    return ADMIN_HTML


@app.get("/auth/me")
def admin_me(request: Request) -> dict[str, bool]:
    return {"authenticated": bool(request.session.get("admin_authenticated")) if SESSION_SECRET else False}


@app.post("/auth/login")
def admin_login(request: Request, payload: dict[str, Any]) -> dict[str, bool]:
    if not SESSION_SECRET or not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured.")
    if payload.get("username") != ADMIN_USERNAME or payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu.")
    request.session["admin_authenticated"] = True
    return {"ok": True}


@app.post("/auth/logout")
def admin_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.post("/auth/device/start")
def device_start(request: Request) -> dict[str, Any]:
    require_admin(request)
    database_required()
    response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/usercode", headers=device_auth_headers(), json={"client_id": CHATGPT_OAUTH_CLIENT_ID}, impersonate="chrome120", timeout=30)
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Device login initialization failed: {read_error(response)}")
    payload = response.json()
    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code") or payload.get("usercode")
    if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
        raise HTTPException(status_code=502, detail="Device login returned an invalid payload.")
    interval = max(int(payload.get("interval", 5)), 3)
    now = int(time.time() * 1000)
    session_id = str(uuid.uuid4())
    expires_at = now + 15 * 60 * 1000
    with db() as connection:
        connection.execute("INSERT INTO device_login_sessions (id, device_auth_id, user_code, interval_seconds, expires_at, status, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)", (session_id, device_auth_id, user_code, interval, expires_at, now, now))
    return {"login_id": session_id, "user_code": user_code, "interval_seconds": interval, "expires_at": expires_at, "verification_url": DEVICE_VERIFICATION_URL}


@app.post("/auth/device/poll")
def device_poll(request: Request, payload: dict[str, Any]) -> dict[str, str]:
    require_admin(request)
    database_required()
    login_id = payload.get("login_id")
    if not isinstance(login_id, str):
        raise HTTPException(status_code=400, detail="login_id is required.")
    with db() as connection:
        row = connection.execute("SELECT id, device_auth_id, user_code, expires_at, status FROM device_login_sessions WHERE id=%s", (login_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Login session not found.")
    if row[4] != "pending":
        return {"login_id": login_id, "status": str(row[4])}
    if int(row[3]) <= int(time.time() * 1000):
        with db() as connection:
            connection.execute("UPDATE device_login_sessions SET status='expired', updated_at=%s WHERE id=%s", (int(time.time() * 1000), login_id))
        return {"login_id": login_id, "status": "expired"}
    response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/api/accounts/deviceauth/token", headers=device_auth_headers(), json={"device_auth_id": row[1], "user_code": row[2]}, impersonate="chrome120", timeout=30)
    if response.status_code in (403, 404):
        return {"login_id": login_id, "status": "pending"}
    if not response.ok:
        with db() as connection:
            connection.execute("UPDATE device_login_sessions SET status='failed', updated_at=%s WHERE id=%s", (int(time.time() * 1000), login_id))
        raise HTTPException(status_code=502, detail=f"Device login failed: {read_error(response)}")
    auth_payload = response.json()
    authorization_code = auth_payload.get("authorization_code")
    code_verifier = auth_payload.get("code_verifier")
    if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
        raise HTTPException(status_code=502, detail="Device login returned an invalid authorization payload.")
    token_response = requests.post(f"{CHATGPT_AUTH_BASE_URL}/oauth/token", data={"grant_type": "authorization_code", "code": authorization_code, "redirect_uri": "https://auth.openai.com/deviceauth/callback", "client_id": CHATGPT_OAUTH_CLIENT_ID, "code_verifier": code_verifier}, headers={"content-type": "application/x-www-form-urlencoded", "user-agent": CODEX_USER_AGENT}, impersonate="chrome120", timeout=30)
    if not token_response.ok:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {read_error(token_response)}")
    tokens = token_response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    id_token = tokens.get("id_token")
    account_id = extract_account_id(id_token or "") or extract_account_id(access_token or "")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or not account_id:
        raise HTTPException(status_code=502, detail="OAuth response is missing required ChatGPT credentials.")
    now = int(time.time() * 1000)
    label = str(payload.get("label") or f"ChatGPT {time.strftime('%Y-%m-%d %H:%M')}")[:100]
    with db() as connection:
        connection.execute("INSERT INTO chatgpt_accounts (id,label,account_id,access_token_enc,refresh_token_enc,id_token_enc,expires_at,status,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)", (str(uuid.uuid4()), label, account_id, encrypt_token(access_token), encrypt_token(refresh_token), encrypt_token(id_token) if isinstance(id_token, str) else None, now + int(tokens.get("expires_in", 3600)) * 1000, now, now))
        connection.execute("UPDATE device_login_sessions SET status='completed', updated_at=%s WHERE id=%s", (now, login_id))
    return {"login_id": login_id, "status": "completed"}


@app.get("/auth/accounts")
def accounts(request: Request) -> dict[str, Any]:
    require_admin(request)
    database_required()
    with db() as connection:
        rows = connection.execute("SELECT id,label,account_id,status,expires_at FROM chatgpt_accounts ORDER BY created_at DESC").fetchall()
    return {"data": [{"id": str(row[0]), "label": str(row[1]), "account_id": str(row[2]), "status": str(row[3]), "expires_at": int(row[4])} for row in rows]}


@app.delete("/auth/accounts/{account_id}")
def disable_account(account_id: str, request: Request) -> dict[str, bool]:
    require_admin(request)
    database_required()
    with db() as connection:
        connection.execute("UPDATE chatgpt_accounts SET status='disabled', updated_at=%s WHERE id=%s", (int(time.time() * 1000), account_id))
    return {"ok": True}


@app.get("/v1/models")
def models(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization, x_api_key)
    created = int(time.time())
    return {"object": "list", "data": [{"id": "chatgpt-gpt-5.6", "object": "model", "created": created, "owned_by": "openai-chatgpt"}]}


@app.get("/v1/debug/transport")
def debug_transport(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> JSONResponse:
    authorize(authorization, x_api_key)
    response = requests.get("https://chatgpt.com/robots.txt", headers={"User-Agent": CODEX_USER_AGENT}, impersonate="chrome120", timeout=30)
    return JSONResponse({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runtime": "faable-curl-cffi", "checks": [{"variant": "curl-cffi-chrome120", "status": response.status_code, "content_type": response.headers.get("content-type"), "body_prefix": response.text[:300]}]})


@app.post("/v1/responses")
def responses(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    authorize(authorization, x_api_key)
    upstream_payload = {**payload, "store": False, "stream": True}
    response = upstream_request(upstream_payload)
    return upstream_response(response)


@app.post("/v1/chat/completions")
def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    authorize(authorization, x_api_key)
    messages = payload.get("messages", [])
    input_items = [{"role": message.get("role", "user"), "content": [{"type": "input_text", "text": message.get("content", "")}]} for message in messages]
    upstream_payload = {"model": str(payload.get("model", "gpt-5.4")).removeprefix("chatgpt-"), "input": input_items, "stream": True, "store": False}
    return upstream_response(upstream_request(upstream_payload))


def upstream_response(response: Any) -> Any:
    if response.status_code >= 400:
        content_type = response.headers.get("content-type", "")
        message = response.text[:1000] if "text/html" not in content_type.lower() else f"ChatGPT upstream returned an HTML block page (HTTP {response.status_code})."
        raise HTTPException(status_code=response.status_code, detail=message)
    return StreamingResponse(response.iter_content(chunk_size=4096), media_type="text/event-stream")


ADMIN_HTML = """<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#111827'><title>ChatGPT Gateway</title><style>:root{font-family:system-ui,-apple-system,sans-serif;color:#111827;background:#f3f4f6}*{box-sizing:border-box}body{margin:0;padding:18px}.app{max-width:560px;margin:auto}.card{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;margin-bottom:14px;box-shadow:0 4px 16px #0000000a}h1{margin:0 0 5px;font-size:24px}h2{font-size:17px;margin:0 0 10px}.muted{font-size:14px;color:#6b7280;line-height:1.5}label{display:block;font-size:13px;font-weight:650;margin:14px 0 6px}input,button{width:100%;min-height:48px;border-radius:12px;font:inherit}input{border:1px solid #d1d5db;padding:12px}button{border:0;background:#111827;color:#fff;font-weight:650;padding:12px;margin-top:10px}button.secondary{background:#e5e7eb;color:#111827}.status{margin-top:12px;padding:12px;background:#f3f4f6;border-radius:12px;font-size:14px;white-space:pre-wrap}.code{margin-top:10px;padding:14px;background:#f9fafb;border-radius:12px;text-align:center;font-size:25px;font-weight:800;letter-spacing:2px}.hidden{display:none}.account{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #eee}.account:last-child{border:0}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#16a34a;margin-right:7px}</style></head><body><main class='app'><section class='card'><h1>ChatGPT Gateway</h1><div class='muted'>Quản lý tài khoản ChatGPT và gateway</div></section><section id='login-card' class='card'><h2>Đăng nhập quản trị</h2><label>Tên đăng nhập</label><input id='username' autocomplete='username'><label>Mật khẩu</label><input id='password' type='password' autocomplete='current-password'><button onclick='login()'>Đăng nhập</button><div id='login-status' class='status hidden'></div></section><section id='dashboard' class='hidden'><section class='card'><h2>Quản trị</h2><div class='status'>Phiên quản trị đang hoạt động.</div><button class='secondary' onclick='logout()'>Đăng xuất</button></section><section class='card'><h2>Provider &amp; Model</h2><div id='providers'>Chưa tải.</div><label>Model</label><select id='model-select' onchange='selectModel(this.value)'><option value=''>Mặc định</option></select><div id='provider-status' class='status'></div></section><section class='card'><h2>Client Keys</h2><div class='muted'>Mỗi API key client có thể dùng provider/model riêng. Key master (GATEWAY_API_KEY) dùng lựa chọn chung phía trên.</div><label>Tên client</label><input id='client-label' placeholder='VD: Bot Zalo'><label>API key</label><input id='client-key' placeholder='Để trống để tự sinh'><label>Provider</label><select id='client-provider'><option value='chatgpt'>ChatGPT / Codex</option><option value='bai'>B.AI</option></select><label>Model</label><input id='client-model' placeholder='Để trống = mặc định'><button onclick='addClient()'>Thêm client</button><button class='secondary' onclick='loadClients()'>Làm mới</button><div id='client-created' class='status hidden'></div><div id='clients' class='status'>Chưa tải.</div></section><section class='card'><h2>Đăng nhập ChatGPT</h2><div class='muted'>Không cần nhập access token. Gateway sẽ dùng Device Login của ChatGPT và lưu refresh token được mã hóa trong database.</div><button onclick='startLogin()'>Đăng nhập ChatGPT</button><div id='device-status' class='status hidden'></div><div id='code' class='code hidden'></div><button id='open' class='secondary hidden'>Mở trang xác nhận</button></section><section class='card'><h2>Tài khoản ChatGPT</h2><button class='secondary' onclick='loadAccounts()'>Làm mới</button><div id='accounts' class='status'>Chưa tải.</div></section></section></main><script>const $=id=>document.getElementById(id);const show=(id,text)=>{$(id).textContent=text;$(id).classList.remove('hidden')};async function api(path,options={}){const r=await fetch(path,{...options,headers:{'content-type':'application/json',...(options.headers||{})}});const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||b.error?.message||'HTTP '+r.status);return b}function showDashboard(){ $('login-card').classList.add('hidden');$('dashboard').classList.remove('hidden');loadAccounts();loadProviders();loadClients()}function showLogin(){ $('login-card').classList.remove('hidden');$('dashboard').classList.add('hidden')}async function check(){try{const r=await api('/auth/me');r.authenticated?showDashboard():showLogin()}catch{showLogin()}}async function login(){try{await api('/auth/login',{method:'POST',body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})});$('password').value='';showDashboard()}catch(e){show('login-status',e.message)}}async function logout(){await api('/auth/logout',{method:'POST'});showLogin()}async function startLogin(){try{const s=await api('/auth/device/start',{method:'POST'});$('code').textContent=s.user_code;$('code').classList.remove('hidden');$('open').classList.remove('hidden');$('open').onclick=()=>window.open(s.verification_url,'_blank');show('device-status','Mở trang xác nhận và nhập mã ở trên. Đang chờ ChatGPT xác nhận…');poll(s.login_id,s.interval_seconds)}catch(e){show('device-status',e.message)}}async function poll(id,interval){for(;;){await new Promise(r=>setTimeout(r,interval*1000));try{const s=await api('/auth/device/poll',{method:'POST',body:JSON.stringify({login_id:id,label:'ChatGPT'})});if(s.status==='completed'){show('device-status','✓ Đăng nhập ChatGPT thành công.');await loadAccounts();return}if(s.status==='expired'||s.status==='failed'){show('device-status','Phiên đăng nhập: '+s.status);return}show('device-status','Đang chờ xác nhận đăng nhập…')}catch(e){show('device-status',e.message);return}}}async function loadAccounts(){try{const r=await api('/auth/accounts');$('accounts').innerHTML=r.data.length?r.data.map(a=>`<div class='account'><span><span class='dot'></span>${a.label}</span><span>${a.status}</span></div>`).join(''):'Chưa có tài khoản.'}catch(e){$('accounts').textContent=e.message}}let providersData=null;async function loadProviders(){try{const r=await api('/auth/providers');providersData=r;renderProviders(r)}catch(e){$('providers').textContent=e.message}}function renderProviders(r){$('providers').innerHTML=r.providers.map(p=>`<button class='${p.id===r.active_provider?'':'secondary'}' ${p.configured?'':"disabled title='Chưa cấu hình BAI_API_KEY'"} onclick='selectProvider("${p.id}")'>${p.id==='bai'?'B.AI':'ChatGPT / Codex'}${p.configured?'':' (chưa có key)'}</button>`).join('');const active=r.providers.find(p=>p.id===r.active_provider);const models=active&&active.models.length?active.models:[''];$('model-select').innerHTML=models.map(m=>`<option value='${m}' ${m===r.active_model?'selected':''}>${m||'Mặc định'}</option>`).join('');$('provider-status').textContent='Đang dùng: '+(r.active_provider==='bai'?'B.AI':'ChatGPT / Codex')+(r.active_model?' · model '+r.active_model:' · model mặc định')}async function selectProvider(id){try{await api('/auth/providers/select',{method:'POST',body:JSON.stringify({provider:id})});await loadProviders()}catch(e){$('provider-status').textContent=e.message}}async function selectModel(m){if(!providersData)return;try{await api('/auth/providers/select',{method:'POST',body:JSON.stringify({provider:providersData.active_provider,model:m})});await loadProviders()}catch(e){$('provider-status').textContent=e.message}}async function loadClients(){try{const r=await api('/auth/clients');$('clients').innerHTML=r.data.length?r.data.map(c=>`<div class='account'><span><span class='dot'></span>${c.label}<br><small>${c.key_masked} · ${c.provider}${c.model?' · '+c.model:''}</small></span><span>${c.status==='active'?`<button class='secondary' style='min-height:36px;width:auto;padding:6px 12px;margin:2px' onclick='clientAction("${c.id}","disabled")'>Tắt</button>`:`<button class='secondary' style='min-height:36px;width:auto;padding:6px 12px;margin:2px' onclick='clientAction("${c.id}","active")'>Bật</button><button class='secondary' style='min-height:36px;width:auto;padding:6px 12px;margin:2px' onclick='clientAction("${c.id}","delete")'>Xóa</button>`}</span></div>`).join(''):'Chưa có client key.'}catch(e){$('clients').textContent=e.message}}async function clientAction(id,action){try{if(action==='delete'){await api('/auth/clients/'+id,{method:'DELETE'})}else{await api('/auth/clients/'+id,{method:'POST',body:JSON.stringify({status:action})})}await loadClients()}catch(e){show('client-created',e.message)}}async function addClient(){try{const r=await api('/auth/clients',{method:'POST',body:JSON.stringify({label:$('client-label').value.trim(),key:$('client-key').value.trim(),provider:$('client-provider').value,model:$('client-model').value.trim()})});$('client-key').value='';$('client-model').value='';show('client-created','✓ Đã tạo. API key client: '+r.key);await loadClients()}catch(e){show('client-created',e.message)}}check();</script></body></html>"""
