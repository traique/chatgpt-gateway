from __future__ import annotations

import contextvars
import hashlib
import hmac
import os
import secrets
import time
import uuid
from typing import Any

from fastapi import Header, HTTPException, Request

PROVIDER_CHATGPT = "chatgpt"
PROVIDER_BAI = "bai"
KNOWN_PROVIDERS = (PROVIDER_CHATGPT, PROVIDER_BAI)
DEFAULT_BAI_BASE_URL = "https://api.b.ai/v1"
DEFAULT_MODEL_ALIASES = frozenset({"", "chatgpt-gpt-5.6", "gpt-5.6"})
CHATGPT_ADMIN_MODELS = ("chatgpt-gpt-5.6", "gpt-5.6-terra", "gpt-5.6-codex")
MODELS_CACHE_TTL_SECONDS = 60

_models_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_memory_settings: dict[str, str] = {}
_memory_clients: dict[str, dict[str, Any]] = {}
_settings_table_ready = False
_client_table_ready = False
_client_policy: contextvars.ContextVar = contextvars.ContextVar("client_provider_policy", default=None)


def get_client_policy() -> dict[str, str] | None:
    return _client_policy.get()


def set_client_policy(policy: dict[str, str] | None) -> None:
    _client_policy.set(policy)


def hash_client_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def generate_client_key() -> str:
    return f"gwc-{secrets.token_hex(20)}"


def mask_client_key(value: str) -> str:
    if len(value) <= 10:
        return value[:2] + "…"
    return f"{value[:6]}…{value[-4:]}"


def _get_setting(runtime: Any, key: str) -> str:
    if not runtime.DATABASE_URL:
        return _memory_settings.get(key, "")
    global _settings_table_ready
    with runtime.db() as connection:
        if not _settings_table_ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS gateway_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at BIGINT NOT NULL)"
            )
            _settings_table_ready = True
        row = connection.execute("SELECT value FROM gateway_settings WHERE key=%s", (key,)).fetchone()
    return str(row[0]) if row else ""


def _set_setting(runtime: Any, key: str, value: str) -> None:
    if not runtime.DATABASE_URL:
        _memory_settings[key] = value
        return
    global _settings_table_ready
    with runtime.db() as connection:
        if not _settings_table_ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS gateway_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at BIGINT NOT NULL)"
            )
            _settings_table_ready = True
        connection.execute(
            "INSERT INTO gateway_settings (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            (key, value, int(time.time())),
        )


def get_active_provider(runtime: Any) -> str:
    value = _get_setting(runtime, "active_provider")
    return value if value in KNOWN_PROVIDERS else PROVIDER_CHATGPT


def get_active_model(runtime: Any) -> str:
    return _get_setting(runtime, "active_model")


def set_active_provider_model(runtime: Any, provider: str, model: str = "") -> None:
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}.")
    _set_setting(runtime, "active_provider", provider)
    _set_setting(runtime, "active_model", str(model or "").strip()[:200])


def bai_configured(runtime: Any) -> bool:
    return bool(getattr(runtime, "BAI_API_KEY", ""))


def resolve_model(runtime: Any, requested: Any, default: str) -> str:
    """Return the model the client asked for, unless it is empty/an alias —
    then fall back to the client's model, the admin's global pick, or the default."""
    model = str(requested or "").strip()
    if model in DEFAULT_MODEL_ALIASES:
        policy = get_client_policy()
        if policy and policy.get("model"):
            return policy["model"]
        active = get_active_model(runtime)
        if active:
            return active
    return model or default


def _ensure_client_table(connection: Any) -> None:
    global _client_table_ready
    if not _client_table_ready:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS gateway_api_keys ("
            "id TEXT PRIMARY KEY, label TEXT NOT NULL, key_enc TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, "
            "provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', "
            "created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)"
        )
        _client_table_ready = True


def _lookup_client_policy(runtime: Any, supplied: str) -> dict[str, str] | None:
    key = supplied.strip()
    if not key:
        return None
    if not runtime.DATABASE_URL:
        for entry in _memory_clients.values():
            if entry["status"] == "active" and hmac.compare_digest(entry["key"], key):
                return {"provider": entry["provider"], "model": entry["model"]}
        return None
    digest = hash_client_key(key)
    with runtime.db() as connection:
        _ensure_client_table(connection)
        row = connection.execute(
            "SELECT provider, model, key_enc FROM gateway_api_keys WHERE key_hash=%s AND status='active'",
            (digest,),
        ).fetchone()
    if not row:
        return None
    if not hmac.compare_digest(runtime.decrypt_token(str(row[2])), key):
        return None
    return {"provider": str(row[0]), "model": str(row[1] or "")}


def bai_request(
    runtime: Any,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    if not bai_configured(runtime):
        raise HTTPException(status_code=503, detail="BAI_API_KEY is not configured.")
    headers = {"Authorization": f"Bearer {runtime.BAI_API_KEY}", "Content-Type": "application/json"}
    try:
        return runtime.requests.post(
            f"{runtime.BAI_BASE_URL}{path}",
            headers=headers,
            **({"json": json_payload} if json_payload is not None else {}),
            impersonate="chrome120",
            timeout=timeout,
            stream=stream,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"B.AI transport failed: {error}") from error


def bai_list_models(runtime: Any) -> list[str]:
    global _models_cache
    now = time.time()
    cached = list(_models_cache["models"])
    if cached and now - float(_models_cache["ts"]) < MODELS_CACHE_TTL_SECONDS:
        return cached
    if not bai_configured(runtime):
        return []
    try:
        response = runtime.requests.get(
            f"{runtime.BAI_BASE_URL}/models",
            headers={"Authorization": f"Bearer {runtime.BAI_API_KEY}"},
            impersonate="chrome120",
            timeout=15,
        )
        payload = response.json()
    except Exception:
        return cached
    ids: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        ids = [str(item["id"]) for item in payload["data"] if isinstance(item, dict) and item.get("id")]
    if ids:
        _models_cache = {"ts": now, "models": ids}
        return ids
    return cached


def _client_rows(runtime: Any) -> list[dict[str, Any]]:
    if not runtime.DATABASE_URL:
        entries = sorted(_memory_clients.values(), key=lambda entry: int(entry["created_at"]), reverse=True)
        return [
            {
                "id": entry["id"],
                "label": entry["label"],
                "key_masked": mask_client_key(entry["key"]),
                "provider": entry["provider"],
                "model": entry["model"],
                "status": entry["status"],
            }
            for entry in entries
        ]
    with runtime.db() as connection:
        _ensure_client_table(connection)
        rows = connection.execute(
            "SELECT id, label, key_enc, provider, model, status FROM gateway_api_keys ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "label": str(row[1]),
            "key_masked": mask_client_key(runtime.decrypt_token(str(row[2]))),
            "provider": str(row[3]),
            "model": str(row[4] or ""),
            "status": str(row[5]),
        }
        for row in rows
    ]


def _create_client(runtime: Any, label: str, key: str, provider: str, model: str) -> str:
    now = int(time.time() * 1000)
    client_id = str(uuid.uuid4())
    if not runtime.DATABASE_URL:
        for entry in _memory_clients.values():
            if hmac.compare_digest(entry["key"], key):
                raise HTTPException(status_code=400, detail="This API key is already registered.")
        _memory_clients[client_id] = {
            "id": client_id, "label": label, "key": key,
            "provider": provider, "model": model, "status": "active",
            "created_at": now, "updated_at": now,
        }
        return client_id
    digest = hash_client_key(key)
    with runtime.db() as connection:
        _ensure_client_table(connection)
        if connection.execute("SELECT 1 FROM gateway_api_keys WHERE key_hash=%s", (digest,)).fetchone():
            raise HTTPException(status_code=400, detail="This API key is already registered.")
        connection.execute(
            "INSERT INTO gateway_api_keys (id, label, key_enc, key_hash, provider, model, status, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s)",
            (client_id, label, runtime.encrypt_token(key), digest, provider, model, now, now),
        )
    return client_id


def _update_client(runtime: Any, client_id: str, payload: dict[str, Any]) -> None:
    updates: list[tuple[str, Any]] = []
    if isinstance(payload.get("provider"), str):
        if payload["provider"] not in KNOWN_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload['provider']}.")
        updates.append(("provider", payload["provider"]))
    if isinstance(payload.get("model"), str):
        updates.append(("model", payload["model"].strip()[:200]))
    if isinstance(payload.get("label"), str) and payload["label"].strip():
        updates.append(("label", payload["label"].strip()[:100]))
    if isinstance(payload.get("status"), str):
        if payload["status"] not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status must be active or disabled.")
        updates.append(("status", payload["status"]))
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    updates.append(("updated_at", int(time.time())))
    if not runtime.DATABASE_URL:
        entry = _memory_clients.get(client_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Client key not found.")
        for field, value in updates:
            if field == "provider":
                entry["provider"] = value
            elif field == "model":
                entry["model"] = value
            elif field == "label":
                entry["label"] = value
            elif field == "status":
                entry["status"] = value
            elif field == "updated_at":
                entry["updated_at"] = value
        return
    assignments = ", ".join(f"{field}=%s" for field, _ in updates)
    values = [value for _, value in updates] + [client_id]
    with runtime.db() as connection:
        _ensure_client_table(connection)
        if connection.execute(f"UPDATE gateway_api_keys SET {assignments} WHERE id=%s", tuple(values)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Client key not found.")


def _delete_client(runtime: Any, client_id: str) -> None:
    if not runtime.DATABASE_URL:
        if _memory_clients.pop(client_id, None) is None:
            raise HTTPException(status_code=404, detail="Client key not found.")
        return
    with runtime.db() as connection:
        _ensure_client_table(connection)
        if connection.execute("DELETE FROM gateway_api_keys WHERE id=%s", (client_id,)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Client key not found.")


def install(runtime: Any) -> None:
    runtime.BAI_API_KEY = os.getenv("BAI_API_KEY", "").strip()
    runtime.BAI_BASE_URL = os.getenv("BAI_BASE_URL", DEFAULT_BAI_BASE_URL).strip().rstrip("/") or DEFAULT_BAI_BASE_URL
    runtime.get_active_provider = lambda: get_active_provider(runtime)
    runtime.get_active_model = lambda: get_active_model(runtime)
    runtime.set_active_provider_model = lambda provider, model="": set_active_provider_model(runtime, provider, model)
    runtime.bai_configured = lambda: bai_configured(runtime)
    runtime.resolve_model = lambda requested, default: resolve_model(runtime, requested, default)
    runtime.bai_request = lambda path, **kwargs: bai_request(runtime, path, **kwargs)
    runtime.bai_list_models = lambda: bai_list_models(runtime)
    runtime.lookup_client_policy = lambda supplied: _lookup_client_policy(runtime, supplied)
    runtime.set_client_policy = set_client_policy
    runtime.get_client_policy = get_client_policy

    runtime.app.router.routes[:] = [
        route for route in runtime.app.router.routes if getattr(route, "path", None) != "/v1/models"
    ]

    def models_endpoint(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        runtime.authorize(authorization, x_api_key)
        created = int(time.time())
        if get_active_provider(runtime) == PROVIDER_BAI:
            catalog = bai_list_models(runtime)
            owned_by = "b-ai"
        else:
            catalog = list(getattr(runtime, "PUBLIC_MODEL_CATALOG", ("chatgpt-gpt-5.6",)))
            owned_by = "openai-chatgpt"
        return {
            "object": "list",
            "data": [{"id": model_id, "object": "model", "created": created, "owned_by": owned_by} for model_id in catalog],
        }

    def providers(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        configured = bai_configured(runtime)
        return {
            "active_provider": get_active_provider(runtime),
            "active_model": get_active_model(runtime),
            "providers": [
                {"id": PROVIDER_CHATGPT, "label": "ChatGPT / Codex", "configured": True, "models": list(CHATGPT_ADMIN_MODELS)},
                {"id": PROVIDER_BAI, "label": "B.AI", "configured": configured, "models": bai_list_models(runtime) if configured else []},
            ],
        }

    def select_provider(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        provider = payload.get("provider")
        if not isinstance(provider, str):
            raise HTTPException(status_code=400, detail="provider is required.")
        model = payload.get("model") if isinstance(payload.get("model"), str) else ""
        set_active_provider_model(runtime, provider, model)
        return {"ok": True, "active_provider": get_active_provider(runtime), "active_model": get_active_model(runtime)}

    runtime.app.add_api_route("/v1/models", models_endpoint, methods=["GET"])
    runtime.app.add_api_route("/auth/providers", providers, methods=["GET"])
    runtime.app.add_api_route("/auth/providers/select", select_provider, methods=["POST"])

    def list_clients(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"data": _client_rows(runtime)}

    def create_client(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        label = str(payload.get("label") or "Client").strip()[:100] or "Client"
        provider = payload.get("provider")
        if provider not in KNOWN_PROVIDERS:
            raise HTTPException(status_code=400, detail="provider must be 'chatgpt' or 'bai'.")
        model = str(payload.get("model") or "").strip()[:200]
        key = str(payload.get("key") or "").strip()
        if not key:
            key = generate_client_key()
        client_id = _create_client(runtime, label, key, provider, model)
        return {"ok": True, "id": client_id, "key": key, "data": _client_rows(runtime)}

    def update_client(request: Request, client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        _update_client(runtime, client_id, payload)
        return {"ok": True, "data": _client_rows(runtime)}

    def delete_client(request: Request, client_id: str) -> dict[str, Any]:
        runtime.require_admin(request)
        _delete_client(runtime, client_id)
        return {"ok": True, "data": _client_rows(runtime)}

    runtime.app.add_api_route("/auth/clients", list_clients, methods=["GET"])
    runtime.app.add_api_route("/auth/clients", create_client, methods=["POST"])
    runtime.app.add_api_route("/auth/clients/{client_id}", update_client, methods=["POST"])
    runtime.app.add_api_route("/auth/clients/{client_id}", delete_client, methods=["DELETE"])
