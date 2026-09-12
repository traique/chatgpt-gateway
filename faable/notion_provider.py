"""Notion AI provider: browser-assisted/token_v2 login + runInferenceTranscript.

Admins can either paste a ``token_v2`` value together with optional Notion
session identity cookies (``notion_user_id`` / ``notion_users``), or use a local
browser-assisted flow that opens an isolated Chrome/Edge profile on the gateway
machine and captures the minimal Notion web session after a normal sign-in.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .notion_browser_auth import browser_login_capability, capture_notion_session

NOTION_API_BASE = "https://app.notion.com/api/v3"
NOTION_BOOTSTRAP_BASES = (NOTION_API_BASE, "https://www.notion.so/api/v3")
NOTION_IMPERSONATE = "chrome131"
DEFAULT_NOTION_CLIENT_VERSION = "23.13.20260710.0022"
DEFAULT_NOTION_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
DEFAULT_NOTION_MODEL = "ambrosia-tart-high"
NOTION_DEFAULT_TIMEZONE = "America/Los_Angeles"

# Friendly alias -> Notion internal model id (fallback when getAvailableModels is unavailable).
NOTION_MODEL_ALIASES: dict[str, str] = {
    "notion-ai": "ambrosia-tart-high",
    "gpt-4o": "ambrosia-tart-high",
    "gpt-4": "ambrosia-tart-high",
    "gpt-3.5-turbo": "almond-croissant-low",
    "gpt-5.2": "oatmeal-cookie",
    "gpt-5.4": "oval-kumquat-medium",
    "gpt-5.5": "opal-quince-medium",
    "gpt-5.6-terra": "orchid-muffin",
    "gpt-5.6-sol": "orange-mousse",
    "gpt-5.6-luna": "olive-jellyroll",
    "grok-4.5": "strawberry-whoopiepie",
    "grok-4.3": "xigua-mochi-medium",
    "opus-4.8": "ambrosia-tart-high",
    "opus-4.7": "apricot-sorbet-high",
    "opus-4.6": "avocado-froyo-medium",
    "sonnet-5": "angel-cake-high",
    "sonnet-4.6": "almond-croissant-low",
    "haiku-4.5": "anthropic-haiku-4.5",
    "gemini-3.5-flash": "vertex-gemini-3.5-flash",
    "gemini-3-flash": "gingerbread",
    "glm-5.2": "baseten-glm-5.2",
    "kimi-k2.6": "fireworks-kimi-k2.6",
    "deepseek-v4-pro": "baseten-deepseek-v4-pro",
    "minimax-m2.5": "fireworks-minimax-m2.5",
    "fable-5": "acai-budino-high",
}
NOTION_MODEL_CATALOG: tuple[str, ...] = (
    "notion-ai",
    "opus-4.8",
    "sonnet-5",
    "sonnet-4.6",
    "haiku-4.5",
    "gpt-5.6-terra",
    "gemini-3.5-flash",
    "grok-4.5",
    "glm-5.2",
)

_NOTION_XML_TAG_RE = re.compile(r"</?(?:notion|ne|lang|mention|source|external)[^>\s]*[^>]*>")
_NOTION_XML_INCOMPLETE_RE = re.compile(r"<(?:lang|mention|source)\s[^>]*$", re.MULTILINE)

NOTION_MODELS_CACHE_TTL_SECONDS = 300

_memory_notion_accounts: dict[str, dict[str, Any]] = {}
_memory_notion_browser_logins: dict[str, dict[str, Any]] = {}
_notion_table_ready = False
_notion_browser_login_table_ready = False
_notion_models_cache: dict[str, Any] = {"ts": 0.0, "alias_map": {}, "models": []}


def _friendly_alias(model_message: str) -> str:
    return model_message.strip().lower().replace(" ", "-")


def parse_available_models(response: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Return (alias_map, catalog) from Notion's getAvailableModels payload.

    alias_map: friendly alias -> internal Notion model id (e.g. "opus-4.8" -> "ambrosia-tart-high").
    catalog: display names (modelMessage) for the admin dropdown / /v1/models.
    Models flagged isDisabled are dropped; "free" here means included in the
    workspace plan's AI — anything Notion marks unavailable is filtered out.
    """
    alias_map: dict[str, str] = dict(NOTION_MODEL_ALIASES)
    catalog: list[str] = []
    seen_ids: set[str] = set()
    for entry in response.get("models") or []:
        if not isinstance(entry, dict) or entry.get("isDisabled"):
            continue
        message = entry.get("modelMessage")
        model_id = entry.get("model")
        if not isinstance(message, str) or not isinstance(model_id, str) or not message.strip():
            continue
        primary = _friendly_alias(message)
        aliases = {primary, model_id, message.strip()}
        if primary.startswith("claude-"):
            aliases.add(primary.removeprefix("claude-"))
        for alias in aliases:
            alias_map[alias] = model_id
        if model_id not in seen_ids:
            seen_ids.add(model_id)
            catalog.append(message.strip())
    catalog.sort(key=str.lower)
    return alias_map, catalog


def notion_list_models(runtime: Any) -> list[str]:
    """Display catalog from getAvailableModels; falls back to the static catalog."""
    global _notion_models_cache
    now = time.time()
    cached = list(_notion_models_cache["models"])
    if cached and now - float(_notion_models_cache["ts"]) < NOTION_MODELS_CACHE_TTL_SECONDS:
        return cached
    if not notion_configured(runtime):
        return list(NOTION_MODEL_CATALOG)
    account = get_active_notion_account(runtime)
    headers = notion_request_headers(account, accept="application/json")
    try:
        response = runtime.requests.post(
            f"{NOTION_API_BASE}/getAvailableModels",
            headers=headers,
            json={"spaceId": account["space_id"]},
            impersonate=NOTION_IMPERSONATE,
            timeout=6,
        )
        payload = response.json() if response.status_code == 200 else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return cached or list(NOTION_MODEL_CATALOG)
    _, catalog = parse_available_models(payload)
    if catalog:
        _notion_models_cache = {"ts": now, "alias_map": _, "models": catalog}
        return catalog
    return cached or list(NOTION_MODEL_CATALOG)


def _dynamic_alias_map() -> dict[str, str]:
    return dict(_notion_models_cache["alias_map"]) or dict(NOTION_MODEL_ALIASES)


class NotionUpstreamError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def as_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.message)


def parse_browser_cookie(cookie: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        parsed[name.strip()] = value.strip()
    return parsed


def build_cookie_header(account: dict[str, Any]) -> str:
    full_cookie = str(account.get("full_cookie") or "").strip().rstrip(";")
    if full_cookie:
        return full_cookie
    user_id = str(account.get("user_id") or "").strip()
    notion_users = str(account.get("notion_users") or "").strip()
    parts = [
        f"notion_browser_id={account.get('browser_id') or uuid.uuid4()}",
        f"device_id={account.get('device_id') or uuid.uuid4()}",
    ]
    if user_id:
        parts.append(f"notion_user_id={user_id}")
    if notion_users:
        parts.append(f"notion_users={notion_users}")
    elif user_id:
        # Compatibility fallback only. When the real notion_users cookie is
        # available we keep its exact browser value instead of synthesizing it.
        parts.append(f"notion_users=[%22{user_id}%22]")
    parts.extend([
        "notion_check_cookie_consent=false",
        "notion_locale=en-US/autodetect",
        f"token_v2={account.get('token_v2') or ''}",
    ])
    return "; ".join(parts)


def notion_request_headers(account: dict[str, Any], *, accept: str = "application/x-ndjson") -> dict[str, str]:
    user_agent = str(account.get("user_agent") or DEFAULT_NOTION_USER_AGENT)
    major = re.search(r"Chrome/(\d+)", user_agent)
    chrome_major = int(major.group(1)) if major else 150
    headers = {
        "accept": accept,
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "notion-audit-log-platform": "web",
        "notion-client-version": str(account.get("client_version") or DEFAULT_NOTION_CLIENT_VERSION),
        "origin": "https://app.notion.com",
        "referer": "https://app.notion.com/chat",
        "user-agent": user_agent,
        "x-notion-active-user-header": str(account.get("user_id") or ""),
        "x-notion-space-id": str(account.get("space_id") or ""),
        "sec-ch-ua": f'"Not;A=Brand";v="8", "Chromium";v="{chrome_major}", "Google Chrome";v="{chrome_major}"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "cookie": build_cookie_header(account),
    }
    return {key: value for key, value in headers.items() if value}


def _normalize_cookie_value(value: str, name: str, *, required: bool = False) -> str:
    """Accept a cookie value (or ``name=value``) without accepting a full cookie header."""
    normalized = str(value or "").strip()
    prefix = f"{name}="
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix):].strip()
    if required and not normalized:
        raise HTTPException(status_code=400, detail=f"{name} is required.")
    if ";" in normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Paste only the {name} value, not the full Notion cookie string.",
        )
    return normalized


def normalize_token_v2(value: str) -> str:
    return _normalize_cookie_value(value, "token_v2", required=True)


def normalize_notion_user_id(value: str) -> str:
    return _normalize_cookie_value(value, "notion_user_id")


def normalize_notion_users(value: str) -> str:
    return _normalize_cookie_value(value, "notion_users")


def _record_value(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    value = record.get("value")
    if not isinstance(value, dict):
        return {}
    nested = value.get("value")
    return nested if isinstance(nested, dict) else value


def _bootstrap_headers(account: dict[str, Any], base_url: str) -> dict[str, str]:
    headers = notion_request_headers(account, accept="application/json")
    if "notion.so" in base_url:
        headers["origin"] = "https://www.notion.so"
        headers["referer"] = "https://www.notion.so/"
    else:
        headers["origin"] = "https://app.notion.com"
        headers["referer"] = "https://app.notion.com/"
    return headers


def bootstrap_notion_account(
    runtime: Any,
    token_v2: str,
    *,
    session_cookie: str = "",
    user_id: str = "",
    notion_users: str = "",
    browser_id: str = "",
    device_id: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """Resolve user/workspace metadata from a Notion web session.

    Manual login may provide only token_v2. Browser-assisted login passes the
    real browser/session identifiers as well, which is more reliable with
    Notion's current private API trust checks.
    """
    token_v2 = normalize_token_v2(token_v2)
    parsed_cookie = parse_browser_cookie(session_cookie) if session_cookie else {}
    normalized_user_id = normalize_notion_user_id(user_id or parsed_cookie.get("notion_user_id") or "")
    normalized_notion_users = normalize_notion_users(notion_users or parsed_cookie.get("notion_users") or "")
    account: dict[str, Any] = {
        "token_v2": token_v2,
        "full_cookie": str(session_cookie or "").strip().rstrip(";"),
        "user_id": normalized_user_id,
        "notion_users": normalized_notion_users,
        "browser_id": str(browser_id or parsed_cookie.get("notion_browser_id") or uuid.uuid4()),
        "device_id": str(device_id or parsed_cookie.get("device_id") or uuid.uuid4()),
        "user_agent": str(user_agent or DEFAULT_NOTION_USER_AGENT),
        "timezone": NOTION_DEFAULT_TIMEZONE,
    }

    attempts: list[str] = []
    data: dict[str, Any] | None = None
    for base_url in dict.fromkeys(NOTION_BOOTSTRAP_BASES):
        headers = _bootstrap_headers(account, base_url)
        try:
            response = runtime.requests.post(
                f"{base_url}/loadUserContent",
                headers=headers,
                json={"cursor": {"stack": []}, "limit": 100},
                impersonate=NOTION_IMPERSONATE,
                timeout=30,
            )
        except Exception as error:
            attempts.append(f"{base_url}: transport {error}")
            continue
        if response.status_code == 200:
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                data = payload
                break
            attempts.append(f"{base_url}: HTTP 200 but invalid JSON")
            continue
        body = str(getattr(response, "text", "") or "").strip().replace("\n", " ")[:180]
        suffix = f" ({body})" if body else ""
        attempts.append(f"{base_url}: HTTP {response.status_code}{suffix}")

    if data is None:
        joined = "; ".join(attempts) or "no response"
        if any("HTTP 401" in item for item in attempts):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Notion rejected the web session (HTTP 401). This does not always mean token_v2 expired: "
                    "a token copied without the matching active-user/session cookies can be rejected. Use Browser "
                    "Login, or paste token_v2 + notion_user_id + notion_users from the same Notion session. "
                    f"Attempts: {joined}"
                ),
            )
        if any("HTTP 403" in item for item in attempts):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Notion rejected the session (HTTP 403). The browser session/IP trust check may not match the "
                    "gateway machine. Use Browser Login on the gateway machine/network when possible. "
                    f"Attempts: {joined}"
                ),
            )
        raise HTTPException(status_code=502, detail=f"loadUserContent failed. Attempts: {joined}")

    record_map = data.get("recordMap") or {}
    if not isinstance(record_map, dict):
        raise HTTPException(status_code=502, detail="Notion loadUserContent returned an invalid recordMap.")
    users = record_map.get("notion_user") or {}
    resolved_user_id = account["user_id"] or (next(iter(users), "") if isinstance(users, dict) else "")
    if not resolved_user_id:
        raise HTTPException(status_code=502, detail="Could not determine Notion user_id from the authenticated session.")
    account["user_id"] = str(resolved_user_id)
    user_value = _record_value((users.get(resolved_user_id) if isinstance(users, dict) else {}) or {})
    name_value = user_value.get("name") or []
    if isinstance(name_value, str):
        account["user_name"] = name_value
    else:
        account["user_name"] = name_value[0][0] if name_value and isinstance(name_value[0], list) and name_value[0] else ""
    account["user_email"] = str(user_value.get("email") or "")

    space_id = ""
    space_name = ""
    space_view_id = ""
    space_map = record_map.get("space") or {}
    view_map = record_map.get("space_view") or {}
    if isinstance(view_map, dict):
        for view_id, record in view_map.items():
            view_value = _record_value(record)
            candidate_space = str(view_value.get("space_id") or view_value.get("parent_id") or "")
            if not candidate_space:
                continue
            space_id = candidate_space
            space_view_id = str(view_value.get("id") or view_id or "")
            if isinstance(space_map, dict):
                space_value = _record_value(space_map.get(space_id) or {})
                raw_name = space_value.get("name") or ""
                if isinstance(raw_name, list):
                    space_name = raw_name[0][0] if raw_name and isinstance(raw_name[0], list) and raw_name[0] else ""
                else:
                    space_name = str(raw_name)
            break
    if not space_id and isinstance(space_map, dict):
        for key, record in space_map.items():
            space_value = _record_value(record)
            candidate = str(space_value.get("id") or key or "")
            if not candidate:
                continue
            space_id = candidate
            raw_name = space_value.get("name") or ""
            if isinstance(raw_name, list):
                space_name = raw_name[0][0] if raw_name and isinstance(raw_name[0], list) and raw_name[0] else ""
            else:
                space_name = str(raw_name)
            break
    if not space_id:
        raise HTTPException(status_code=502, detail="No Notion workspace found for the authenticated session.")
    account["space_id"] = space_id
    account["space_name"] = space_name
    account["space_view_id"] = space_view_id
    return account


def notion_configured(runtime: Any) -> bool:
    try:
        return bool(_active_notion_row(runtime))
    except HTTPException:
        return False


def _ensure_notion_browser_login_table(connection: Any) -> None:
    global _notion_browser_login_table_ready
    if not _notion_browser_login_table_ready:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notion_browser_login_sessions ("
            "id TEXT PRIMARY KEY, label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
            "error TEXT NOT NULL DEFAULT '', account_id TEXT NOT NULL DEFAULT '', "
            "expires_at BIGINT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)"
        )
        _notion_browser_login_table_ready = True


def _create_notion_browser_login(runtime: Any, label: str, timeout_seconds: int = 300) -> dict[str, Any]:
    now = int(time.time() * 1000)
    login_id = str(uuid.uuid4())
    row = {
        "id": login_id,
        "label": label,
        "status": "pending",
        "error": "",
        "account_id": "",
        "expires_at": now + timeout_seconds * 1000,
        "created_at": now,
        "updated_at": now,
    }
    if not runtime.DATABASE_URL:
        _memory_notion_browser_logins[login_id] = row
        return dict(row)
    with runtime.db() as connection:
        _ensure_notion_browser_login_table(connection)
        connection.execute(
            "INSERT INTO notion_browser_login_sessions "
            "(id,label,status,error,account_id,expires_at,created_at,updated_at) "
            "VALUES (%s,%s,'pending','','',%s,%s,%s)",
            (login_id, label, row["expires_at"], now, now),
        )
    return dict(row)


def _update_notion_browser_login(runtime: Any, login_id: str, *, status: str, error: str = "", account_id: str = "") -> None:
    now = int(time.time() * 1000)
    if not runtime.DATABASE_URL:
        row = _memory_notion_browser_logins.get(login_id)
        if row:
            row.update({"status": status, "error": error[:1000], "account_id": account_id, "updated_at": now})
        return
    with runtime.db() as connection:
        _ensure_notion_browser_login_table(connection)
        connection.execute(
            "UPDATE notion_browser_login_sessions SET status=%s,error=%s,account_id=%s,updated_at=%s WHERE id=%s",
            (status, error[:1000], account_id, now, login_id),
        )


def _get_notion_browser_login(runtime: Any, login_id: str) -> dict[str, Any] | None:
    if not runtime.DATABASE_URL:
        row = _memory_notion_browser_logins.get(login_id)
        return dict(row) if row else None
    with runtime.db() as connection:
        _ensure_notion_browser_login_table(connection)
        row = connection.execute(
            "SELECT id,label,status,error,account_id,expires_at,created_at,updated_at "
            "FROM notion_browser_login_sessions WHERE id=%s",
            (login_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]), "label": str(row[1]), "status": str(row[2]),
        "error": str(row[3] or ""), "account_id": str(row[4] or ""),
        "expires_at": int(row[5]), "created_at": int(row[6]), "updated_at": int(row[7]),
    }


def _run_notion_browser_login(runtime: Any, login_id: str, label: str, timeout_seconds: int = 300) -> None:
    try:
        _update_notion_browser_login(runtime, login_id, status="browser_open")
        session = capture_notion_session(timeout_seconds=timeout_seconds)
        account = bootstrap_notion_account(
            runtime,
            session["token_v2"],
            session_cookie=session.get("cookie", ""),
            user_id=session.get("notion_user_id", ""),
            notion_users=session.get("notion_users", ""),
            browser_id=session.get("notion_browser_id", ""),
            device_id=session.get("device_id", ""),
            user_agent=session.get("user_agent", ""),
        )
        account_id = save_notion_account(runtime, label, account)
        _update_notion_browser_login(runtime, login_id, status="completed", account_id=account_id)
    except TimeoutError as error:
        _update_notion_browser_login(runtime, login_id, status="expired", error=str(error))
    except Exception as error:
        _update_notion_browser_login(runtime, login_id, status="failed", error=str(error))


def start_notion_browser_login(runtime: Any, label: str, timeout_seconds: int = 300) -> dict[str, Any]:
    capable, reason = browser_login_capability()
    if not capable:
        raise HTTPException(status_code=503, detail=reason + " Bạn vẫn có thể đăng nhập bằng token_v2.")
    row = _create_notion_browser_login(runtime, label, timeout_seconds=timeout_seconds)
    thread = threading.Thread(
        target=_run_notion_browser_login,
        args=(runtime, row["id"], label, timeout_seconds),
        name=f"notion-login-{row['id'][:8]}",
        daemon=True,
    )
    thread.start()
    return row


def poll_notion_browser_login(runtime: Any, login_id: str) -> dict[str, Any]:
    row = _get_notion_browser_login(runtime, login_id)
    if not row:
        raise HTTPException(status_code=404, detail="Notion browser login session not found.")
    now = int(time.time() * 1000)
    if row["status"] in {"pending", "browser_open"} and int(row["expires_at"]) <= now:
        _update_notion_browser_login(runtime, login_id, status="expired", error="Hết thời gian chờ đăng nhập Notion.")
        row = _get_notion_browser_login(runtime, login_id) or row
    return row


def _ensure_notion_table(connection: Any) -> None:
    global _notion_table_ready
    if not _notion_table_ready:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notion_accounts ("
            "id TEXT PRIMARY KEY, label TEXT NOT NULL, cookie_enc TEXT NOT NULL, "
            "user_id TEXT NOT NULL, space_id TEXT NOT NULL, space_name TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'active', created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)"
        )
        _notion_table_ready = True


def _active_notion_row(runtime: Any) -> dict[str, Any] | None:
    if not runtime.DATABASE_URL:
        for entry in _memory_notion_accounts.values():
            if entry["status"] == "active":
                return entry
        return None
    with runtime.db() as connection:
        _ensure_notion_table(connection)
        row = connection.execute(
            "SELECT id, label, cookie_enc, user_id, space_id, space_name FROM notion_accounts "
            "WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "label": str(row[1]),
        "cookie_enc": str(row[2]),
        "user_id": str(row[3]),
        "space_id": str(row[4]),
        "space_name": str(row[5] or ""),
    }


def get_active_notion_account(runtime: Any) -> dict[str, Any]:
    row = _active_notion_row(runtime)
    if not row:
        raise HTTPException(status_code=503, detail="No active Notion account. Open /auth and add token_v2 first.")
    stored = row["cookie_enc"]
    if runtime.DATABASE_URL:
        stored = runtime.decrypt_token(stored)
    # Backward compatible with rows that store either token_v2 only or a minimal browser session cookie.
    parsed = parse_browser_cookie(stored) if "=" in stored else {}
    token_v2 = normalize_token_v2(parsed.get("token_v2") or stored)
    return {
        **row,
        "full_cookie": stored if parsed else "",
        "token_v2": token_v2,
        "browser_id": parsed.get("notion_browser_id", ""),
        "device_id": parsed.get("device_id", ""),
        "user_id": row.get("user_id") or parsed.get("notion_user_id", ""),
        "notion_users": parsed.get("notion_users", ""),
    }


def save_notion_account(runtime: Any, label: str, account: dict[str, Any]) -> str:
    account_id = str(uuid.uuid4())
    token_v2 = normalize_token_v2(str(account.get("token_v2") or ""))
    session_cookie = str(account.get("full_cookie") or "").strip().rstrip(";")
    # Persist a stable minimal session. Manual token_v2 login gets generated
    # browser/device ids plus the resolved user id; browser login keeps the real values.
    stored_credential = session_cookie if session_cookie and "token_v2=" in session_cookie else build_cookie_header(account)
    encrypted = runtime.encrypt_token(stored_credential) if runtime.DATABASE_URL else stored_credential
    now = int(time.time() * 1000)
    if not runtime.DATABASE_URL:
        for entry in _memory_notion_accounts.values():
            if entry["status"] == "active":
                entry["status"] = "disabled"
        _memory_notion_accounts[account_id] = {
            "id": account_id,
            "label": label,
            "cookie_enc": encrypted,
            "user_id": account["user_id"],
            "space_id": account["space_id"],
            "space_name": account.get("space_name", ""),
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        return account_id
    with runtime.db() as connection:
        _ensure_notion_table(connection)
        connection.execute(
            "UPDATE notion_accounts SET status='disabled', updated_at=%s WHERE status='active'",
            (now,),
        )
        connection.execute(
            "INSERT INTO notion_accounts (id, label, cookie_enc, user_id, space_id, space_name, status, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s)",
            (account_id, label, encrypted, account["user_id"], account["space_id"], account.get("space_name", ""), now, now),
        )
    return account_id


def notion_account_rows(runtime: Any) -> list[dict[str, Any]]:
    if not runtime.DATABASE_URL:
        entries = sorted(_memory_notion_accounts.values(), key=lambda entry: int(entry["created_at"]), reverse=True)
        return [
            {"id": entry["id"], "label": entry["label"], "user_id": entry["user_id"],
             "space_id": entry["space_id"], "space_name": entry.get("space_name", ""), "status": entry["status"]}
            for entry in entries
        ]
    with runtime.db() as connection:
        _ensure_notion_table(connection)
        rows = connection.execute(
            "SELECT id, label, user_id, space_id, space_name, status FROM notion_accounts ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"id": str(row[0]), "label": str(row[1]), "user_id": str(row[2]),
         "space_id": str(row[3]), "space_name": str(row[4] or ""), "status": str(row[5])}
        for row in rows
    ]


def disable_notion_account(runtime: Any, account_id: str) -> None:
    if not runtime.DATABASE_URL:
        entry = _memory_notion_accounts.get(account_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Notion account not found.")
        entry["status"] = "disabled"
        return
    with runtime.db() as connection:
        _ensure_notion_table(connection)
        if connection.execute("UPDATE notion_accounts SET status='disabled', updated_at=%s WHERE id=%s", (int(time.time() * 1000), account_id)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Notion account not found.")


def resolve_notion_model(model: str) -> str:
    normalized = str(model or "").strip().lower().replace(" ", "-")
    if not normalized:
        return DEFAULT_NOTION_MODEL
    alias_map = _dynamic_alias_map()
    if normalized in alias_map:
        return alias_map[normalized]
    return NOTION_MODEL_ALIASES.get(normalized, normalized)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def _build_config_value(notion_model: str, *, is_subsequent_turn: bool = False) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "type": "workflow",
        "modelFromUser": True,
        "enableAgentAutomations": False,
        "enableAgentIntegrations": False,
        "enableCustomAgents": False,
        "enableExperimentalIntegrations": False,
        "enableAgentDiffs": False,
        "enableCsvAttachmentSupport": False,
        "showDatabaseAgentsDiscoverability": False,
        "enableAgentThreadTools": False,
        "enableCrdtOperations": False,
        "enableAgentCardCustomization": False,
        "enableSystemPromptAsPage": False,
        "enableUserSessionContext": False,
        "enableLargeToolResultComputerOffload": False,
        "enableScriptAgentAdvanced": False,
        "enableScriptAgent": False,
        "enableScriptAgentSearchConnectorsInCustomAgent": False,
        "enableScriptAgentGoogleDriveInCustomAgent": False,
        "enableScriptAgentGoogleDriveOAuthInCustomAgent": False,
        "enableScriptAgentSlack": False,
        "enableScriptAgentMcpServers": False,
        "enableScriptAgentGtm": False,
        "enableScriptAgentCustomToolCalling": False,
        "enableComputer": False,
        "enableCreateAndRunThread": False,
        "enableSoftwareFactoryPage": False,
        "enableAgentGenerateImage": False,
        "enableSpeculativeSearch": False,
        "enableQueryCalendar": False,
        "enableQueryMail": False,
        "enableMailExplicitToolCalls": False,
        "enableMailNotificationPreferences": False,
        "enableMailAgentMultiProviderSupport": False,
        "useRulePrioritization": True,
        "availableConnectors": [],
        "customConnectorInfo": [],
        "searchScopes": [{"type": "everything"}],
        "useWebSearch": False,
        "isHipaa": False,
        "internetAccess": False,
        "useReadOnlyMode": False,
        "writerMode": False,
        "isCustomAgent": False,
        "model": notion_model,
        "isCustomAgentBuilder": False,
        "isAgentResearchRequest": False,
        "useCustomAgentDraft": False,
        "use_draft_actor_pointer": False,
        "enableUpdatePageAutofixer": False,
        "enableMarkdownVNext": False,
        "enableEmbedBlocks": False,
        "updatePageStaleViewGuardEnabled": False,
        "enableAgentSupportPropertyReorder": False,
        "agentShortUpdatePageResult": False,
        "enableAgentAskSurvey": False,
        "databaseAgentConfigMode": False,
        "isOnboardingAgent": False,
        "isMobile": False,
    }
    if is_subsequent_turn:
        cfg["isThreadStartedByAdmin"] = True
    return cfg


def build_inference_payload(account: dict[str, Any], *, prompt: str, notion_model: str) -> dict[str, Any]:
    now = _now_iso()
    transcript = [
        {"id": str(uuid.uuid4()), "type": "config", "value": _build_config_value(notion_model)},
        {
            "id": str(uuid.uuid4()),
            "type": "context",
            "value": {
                "timezone": account.get("timezone") or NOTION_DEFAULT_TIMEZONE,
                "userName": account.get("user_name", ""),
                "userId": account["user_id"],
                "userEmail": account.get("user_email", ""),
                "spaceName": account.get("space_name", ""),
                "spaceId": account["space_id"],
                "spaceViewId": account.get("space_view_id", ""),
                "currentDatetime": now,
                "surface": "ai_module",
            },
        },
        {
            "id": str(uuid.uuid4()),
            "type": "user",
            "value": [[prompt]],
            "userId": account["user_id"],
            "createdAt": now,
        },
    ]
    return {
        "traceId": str(uuid.uuid4()),
        "spaceId": account["space_id"],
        "transcript": transcript,
        "threadId": str(uuid.uuid4()),
        "createThread": True,
        "isPartialTranscript": False,
        "generateTitle": False,
        "saveAllThreadOperations": False,
        "setUnreadState": False,
        "threadType": "workflow",
        "asPatchResponse": True,
        "patchResponseVersion": 2,
        "hasHeartbeat": False,
        "createdSource": "ai_module",
        "isUserInAnySalesAssistedSpace": False,
        "isSpaceSalesAssisted": False,
        "debugOverrides": {
            "emitAgentSearchExtractedResults": True,
            "cachedInferences": {},
            "annotationInferences": {},
            "emitInferences": False,
        },
        "threadParentPointer": {"table": "space", "id": account["space_id"], "spaceId": account["space_id"]},
    }


def messages_to_prompt(messages: Any) -> str:
    """Flatten OpenAI chat messages into a single Notion user prompt."""
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array.")
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        text = content if isinstance(content, str) else "\n".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
        if not text:
            continue
        if role == "system":
            parts.append(text)
        elif role == "assistant":
            parts.append(f"[assistant]: {text}")
        elif role == "tool":
            parts.append(f"[tool result]: {text}")
        else:
            parts.append(text)
    joined = "\n\n".join(part for part in parts if part.strip())
    if not joined.strip():
        raise HTTPException(status_code=400, detail="messages must contain non-empty text.")
    return joined


def clean_notion_output_text(text: str, *, finalize: bool = True) -> str:
    if not text:
        return text
    text = _NOTION_XML_INCOMPLETE_RE.sub("", text)
    text = _NOTION_XML_TAG_RE.sub("", text)
    return text


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class NDJSONStreamParser:
    """State-aware parser for Notion's patchResponseVersion=2 NDJSON stream."""

    def __init__(self) -> None:
        self._block_contents: dict[str, str] = {}
        self._value_types: dict[str, str] = {}
        self._value_counts: dict[str, int] = {}
        self._section_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.notion_model: str | None = None
        self.line_count = 0

    @property
    def text(self) -> str:
        parts: list[str] = []
        for s_idx in range(self._section_count):
            prefix = f"/s/{s_idx}"
            for v_idx in range(self._value_counts.get(prefix, 0)):
                path = f"{prefix}/value/{v_idx}"
                if self._value_types.get(path, "text") == "text":
                    parts.append(self._block_contents.get(path, ""))
        return "".join(parts)

    def feed_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self.line_count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "error":
            message = event.get("message") or event.get("data") or "unknown Notion error"
            raise NotionUpstreamError(f"Notion error: {message}")
        if event_type == "premium-feature-unavailable":
            raise NotionUpstreamError("Notion AI credits exhausted or model not available on this plan.", status_code=402)
        if event_type == "patch":
            for op in event.get("v") or []:
                if isinstance(op, dict):
                    self._handle_patch_op(op)
        elif event_type in ("patch-start", "patch-sync"):
            data = event.get("data") or {}
            sections = data.get("s")
            if isinstance(sections, list):
                for entry in sections:
                    if isinstance(entry, dict):
                        if entry.get("type") == "error":
                            message = entry.get("message") or "Notion rejected the inference request"
                            raise NotionUpstreamError(f"Notion error ({entry.get('subType') or 'unknown'}): {message}")
                        if entry.get("type") == "premium-feature-unavailable":
                            raise NotionUpstreamError("Notion AI credits exhausted or model not available on this plan.", status_code=402)
                self._section_count = len(sections)
                for i, section in enumerate(sections):
                    self._value_counts.setdefault(f"/s/{i}", 0)
                    if isinstance(section, dict):
                        self._absorb_inline_section(i, section)
        elif event_type == "agent-inference":
            self._handle_agent_inference(event)

    def _absorb_inline_section(self, section_idx: int, section: dict[str, Any]) -> None:
        if section.get("type") not in ("agent-inference", "agent-reply", "assistant-reply"):
            return
        values = section.get("value")
        if not isinstance(values, list):
            return
        prefix = f"/s/{section_idx}"
        for i, entry in enumerate(values):
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            entry_path = f"{prefix}/value/{i}"
            if isinstance(entry_type, str):
                self._value_types[entry_path] = entry_type
            content = entry.get("content")
            if entry_type in ("text", "thinking") and isinstance(content, str):
                self._block_contents[entry_path] = content
        self._value_counts[prefix] = len(values)

    def _handle_agent_inference(self, event: dict[str, Any]) -> None:
        values = event.get("value")
        if isinstance(values, list):
            for entry in values:
                if not isinstance(entry, dict):
                    continue
                content = entry.get("content")
                if entry.get("type") == "text" and isinstance(content, str):
                    self._block_contents[f"/legacy/{self.line_count}"] = content
                    self._value_counts[f"/legacy/{self.line_count}"] = 0
        if _is_int(event.get("inputTokens")):
            self.input_tokens += int(event["inputTokens"])
        if _is_int(event.get("outputTokens")):
            self.output_tokens += int(event["outputTokens"])
        if isinstance(event.get("model"), str):
            self.notion_model = event["model"]

    def _handle_patch_op(self, op: dict[str, Any]) -> None:
        operation = op.get("o")
        path = op.get("p")
        value = op.get("v")
        if not isinstance(operation, str) or not isinstance(path, str):
            return
        if operation == "a" and path == "/s/-" and isinstance(value, dict):
            if value.get("type") == "error":
                message = value.get("message") or "Notion rejected the inference request"
                raise NotionUpstreamError(f"Notion error ({value.get('subType') or 'unknown'}): {message}")
            self._section_count += 1
            self._absorb_inline_section(self._section_count - 1, value)
            return
        if operation in ("a", "p") and "/value/" in path and isinstance(value, dict):
            prefix = path[: path.index("/value/")]
            val_part = path[path.index("/value/") + 7:]
            if "/" in val_part:
                return
            if val_part == "-":
                idx = self._value_counts.get(prefix, 0)
            else:
                try:
                    idx = int(val_part)
                except ValueError:
                    idx = self._value_counts.get(prefix, 0)
            entry_path = f"{prefix}/value/{idx}"
            entry_type = value.get("type")
            if isinstance(entry_type, str):
                self._value_types[entry_path] = entry_type
            self._value_counts[prefix] = max(self._value_counts.get(prefix, 0), idx + 1)
            content = value.get("content")
            if isinstance(entry_type, str) and entry_type in ("text", "thinking") and isinstance(content, str):
                self._block_contents[entry_path] = content
            return
        if "content" not in path or not isinstance(value, str):
            if operation == "a" and path.endswith("/inputTokens") and _is_int(value):
                self.input_tokens += int(value)
            elif operation == "a" and path.endswith("/outputTokens") and _is_int(value):
                self.output_tokens += int(value)
            elif operation == "a" and path.endswith("/model") and isinstance(value, str):
                self.notion_model = value
            return
        idx = path.rfind("/content")
        block_path = path[:idx] if idx >= 0 else path
        entry_type = self._value_types.get(block_path, "text")
        if entry_type not in ("text", "thinking"):
            return
        if operation == "x":
            self._block_contents[block_path] = self._block_contents.get(block_path, "") + value
        elif operation == "p":
            self._block_contents[block_path] = value

    def finalize(self) -> dict[str, Any]:
        return {
            "text": clean_notion_output_text(self.text).strip(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "notion_model": self.notion_model,
            "line_count": self.line_count,
        }


def notion_inference_request(runtime: Any, payload: dict[str, Any]) -> Any:
    account = get_active_notion_account(runtime)
    notion_model = resolve_notion_model(str(payload.get("model") or ""))
    prompt = messages_to_prompt(payload.get("messages"))
    body = build_inference_payload(account, prompt=prompt, notion_model=notion_model)
    headers = notion_request_headers(account)
    try:
        response = runtime.requests.post(
            f"{NOTION_API_BASE}/runInferenceTranscript",
            headers=headers,
            json=body,
            impersonate=NOTION_IMPERSONATE,
            timeout=300,
            stream=True,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Notion transport failed: {error}") from error
    if response.status_code >= 400:
        try:
            detail = response.text[:500]
        except Exception:
            detail = f"HTTP {response.status_code}"
        if response.status_code in (401, 403):
            raise HTTPException(status_code=401, detail=f"Notion auth failed ({response.status_code}). Refresh the Notion cookie in /auth. {detail}")
        raise HTTPException(status_code=502, detail=f"Notion API {response.status_code}: {detail}")
    return response


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _chunk(completion_id: str, created: int, requested_model: str, delta: dict[str, Any], finish_reason: str | None = None) -> str:
    return _sse({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": requested_model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    })


def iter_notion_chat_stream(response: Any, requested_model: str):
    """Convert the Notion NDJSON stream into OpenAI chat.completion.chunk SSE."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    parser = NDJSONStreamParser()
    last_emitted = ""
    first_delta = True
    error: NotionUpstreamError | None = None
    try:
        for line in response.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            try:
                parser.feed_line(line)
            except NotionUpstreamError as upstream_error:
                error = upstream_error
                break
            cleaned = clean_notion_output_text(parser.text, finalize=False)
            if not cleaned or cleaned == last_emitted:
                continue
            if cleaned.startswith(last_emitted):
                delta_text = cleaned[len(last_emitted):]
            else:
                # Notion rewrote an earlier block — resync with a full snapshot.
                delta_text = f"\n{cleaned}"
            last_emitted = cleaned
            delta: dict[str, Any] = {"content": delta_text}
            if first_delta:
                delta["role"] = "assistant"
                first_delta = False
            yield _chunk(completion_id, created, requested_model, delta)
    finally:
        try:
            response.close()
        except Exception:
            pass
    if error is not None:
        yield _sse({"error": {"message": error.message, "type": "upstream_error", "code": error.status_code}})
        yield "data: [DONE]\n\n"
        return
    result = parser.finalize()
    final_text = result["text"]
    if final_text and not final_text.startswith(last_emitted.rstrip("\n")):
        if not first_delta:
            yield _chunk(completion_id, created, requested_model, {"content": "\n"})
        yield _chunk(completion_id, created, requested_model, {"content": final_text})
    final_chunk: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": requested_model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    if result["input_tokens"] or result["output_tokens"]:
        final_chunk["usage"] = {
            "prompt_tokens": result["input_tokens"],
            "completion_tokens": result["output_tokens"],
            "total_tokens": result["input_tokens"] + result["output_tokens"],
        }
    yield _sse(final_chunk)
    yield "data: [DONE]\n\n"


def aggregate_notion_chat(response: Any, requested_model: str) -> dict[str, Any]:
    parser = NDJSONStreamParser()
    error: NotionUpstreamError | None = None
    try:
        for line in response.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            try:
                parser.feed_line(line)
            except NotionUpstreamError as upstream_error:
                error = upstream_error
                break
    finally:
        try:
            response.close()
        except Exception:
            pass
    if error is not None:
        raise error.as_http_exception()
    result = parser.finalize()
    if not result["text"]:
        if not result["line_count"]:
            raise HTTPException(status_code=502, detail="Notion returned no stream data. The Notion cookie may be stale — sign in again in /auth.")
        raise HTTPException(status_code=502, detail="Notion returned empty assistant text. AI credits may be exhausted or the response format changed.")
    completion: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result["text"]}, "finish_reason": "stop"}],
    }
    if result["input_tokens"] or result["output_tokens"]:
        completion["usage"] = {
            "prompt_tokens": result["input_tokens"],
            "completion_tokens": result["output_tokens"],
            "total_tokens": result["input_tokens"] + result["output_tokens"],
        }
    return completion


def install(runtime: Any) -> None:
    runtime.notion_bootstrap = lambda token_v2, **kwargs: bootstrap_notion_account(runtime, token_v2, **kwargs)
    runtime.notion_configured = lambda: notion_configured(runtime)
    runtime.notion_request = lambda payload: notion_inference_request(runtime, payload)
    runtime.resolve_notion_model = resolve_notion_model
    runtime.notion_list_models = lambda: notion_list_models(runtime)

    def notion_login(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        token_v2 = normalize_token_v2(str(payload.get("token_v2") or ""))
        notion_user_id = normalize_notion_user_id(str(payload.get("notion_user_id") or ""))
        notion_users = normalize_notion_users(str(payload.get("notion_users") or ""))
        label = str(payload.get("label") or "").strip()[:100] or f"Notion {time.strftime('%Y-%m-%d %H:%M')}"
        account = bootstrap_notion_account(
            runtime,
            token_v2,
            user_id=notion_user_id,
            notion_users=notion_users,
        )
        account_id = save_notion_account(runtime, label, account)
        return {"ok": True, "id": account_id, "data": notion_account_rows(runtime)}

    def notion_browser_start(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime.require_admin(request)
        payload = payload or {}
        label = str(payload.get("label") or "").strip()[:100] or f"Notion {time.strftime('%Y-%m-%d %H:%M')}"
        login = start_notion_browser_login(runtime, label)
        return {
            "login_id": login["id"],
            "status": login["status"],
            "expires_at": login["expires_at"],
            "interval_seconds": 2,
        }

    def notion_browser_poll(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        login_id = str(payload.get("login_id") or "").strip()
        if not login_id:
            raise HTTPException(status_code=400, detail="login_id is required.")
        login = poll_notion_browser_login(runtime, login_id)
        return {
            "login_id": login["id"],
            "status": login["status"],
            "error": login["error"],
            "account_id": login["account_id"],
            "expires_at": login["expires_at"],
        }

    def notion_accounts(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"data": notion_account_rows(runtime)}

    def notion_disable(request: Request, account_id: str) -> dict[str, Any]:
        runtime.require_admin(request)
        disable_notion_account(runtime, account_id)
        return {"ok": True, "data": notion_account_rows(runtime)}

    runtime.app.add_api_route("/auth/notion/login", notion_login, methods=["POST"])
    runtime.app.add_api_route("/auth/notion/browser/start", notion_browser_start, methods=["POST"])
    runtime.app.add_api_route("/auth/notion/browser/poll", notion_browser_poll, methods=["POST"])
    runtime.app.add_api_route("/auth/notion/accounts", notion_accounts, methods=["GET"])
    runtime.app.add_api_route("/auth/notion/accounts/{account_id}", notion_disable, methods=["DELETE"])
