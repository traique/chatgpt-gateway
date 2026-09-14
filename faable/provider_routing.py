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
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_TOKENROUTER = "tokenrouter"
PROVIDER_NOTION = "notion"
PROVIDER_NIM = "nim"
PROVIDER_GENERIC = "generic"
KNOWN_PROVIDERS = (
    PROVIDER_CHATGPT,
    PROVIDER_BAI,
    PROVIDER_OPENROUTER,
    PROVIDER_TOKENROUTER,
    PROVIDER_NOTION,
    PROVIDER_NIM,
    PROVIDER_GENERIC,
)
DEFAULT_BAI_BASE_URL = "https://api.b.ai/v1"
DEFAULT_MODEL_ALIASES = frozenset({"", "chatgpt-gpt-5.6", "gpt-5.6"})
CHATGPT_ADMIN_MODELS = ("chatgpt-gpt-5.6", "gpt-5.6-terra", "gpt-5.6-codex")
PROVIDER_LABELS = {
    PROVIDER_CHATGPT: "ChatGPT / Codex",
    PROVIDER_BAI: "B.AI",
    PROVIDER_OPENROUTER: "OpenRouter",
    PROVIDER_TOKENROUTER: "TokenRouter",
    PROVIDER_NOTION: "Notion AI",
    PROVIDER_NIM: "NVIDIA NIM",
    PROVIDER_GENERIC: "OpenAI Compatible",
}
OPENROUTER_PUBLIC_CATALOG: tuple[str, ...] = (
    "openrouter/auto",
    "deepseek/deepseek-chat-v4:free",
    "meta-llama/llama-4-maverick:free",
    "qwen/qwen3-coder:free",
    "mistralai/mistral-small:free",
)
TOKENROUTER_PUBLIC_CATALOG: tuple[str, ...] = (
    "auto",
    "auto:balance",
    "auto:cost",
    "auto:quality",
    "auto:latency",
    "openai/gpt-5-mini",
    "anthropic/claude-sonnet-4-5",
)
NOTION_PUBLIC_CATALOG: tuple[str, ...] = (
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
NIM_PUBLIC_CATALOG: tuple[str, ...] = (
    "meta/llama-3.3-70b-instruct",
    "deepseek-ai/deepseek-r1",
    "qwen/qwen2.5-coder-32b-instruct",
    "mistralai/mistral-large-2-instruct",
    "google/gemma-3-27b-it",
)
PROVIDER_FALLBACK_CATALOGS: dict[str, tuple[str, ...]] = {
    PROVIDER_OPENROUTER: OPENROUTER_PUBLIC_CATALOG,
    PROVIDER_TOKENROUTER: TOKENROUTER_PUBLIC_CATALOG,
    PROVIDER_NOTION: NOTION_PUBLIC_CATALOG,
    PROVIDER_NIM: NIM_PUBLIC_CATALOG,
}
MODELS_CACHE_TTL_SECONDS = 60
# Small in-process caches are intentionally short lived: they remove the hot-path
# database round trips that hurt small/free instances while keeping admin changes
# effectively immediate via explicit invalidation below.
SETTINGS_CACHE_TTL_SECONDS = max(1, int(os.getenv("GATEWAY_SETTINGS_CACHE_TTL", "30")))
CLIENT_POLICY_CACHE_TTL_SECONDS = max(1, int(os.getenv("GATEWAY_CLIENT_CACHE_TTL", "60")))
CLIENT_POLICY_CACHE_MAX_ENTRIES = max(32, int(os.getenv("GATEWAY_CLIENT_CACHE_MAX", "256")))

_models_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_memory_settings: dict[str, str] = {}
_memory_clients: dict[str, dict[str, Any]] = {}
_settings_cache: dict[tuple[int, str], tuple[float, str]] = {}
_client_policy_cache: dict[tuple[int, str], tuple[float, dict[str, str]]] = {}
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
    cache_key = (id(runtime), key)
    now = time.monotonic()
    cached = _settings_cache.get(cache_key)
    if cached and now - cached[0] < SETTINGS_CACHE_TTL_SECONDS:
        return cached[1]
    global _settings_table_ready
    with runtime.db() as connection:
        if not _settings_table_ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS gateway_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at BIGINT NOT NULL)"
            )
            _settings_table_ready = True
        row = connection.execute("SELECT value FROM gateway_settings WHERE key=%s", (key,)).fetchone()
    value = str(row[0]) if row else ""
    _settings_cache[cache_key] = (now, value)
    return value


def _preload_settings(runtime: Any) -> None:
    """Warm all small gateway settings with one DB round trip at process start.

    Provider installers read several independent settings. Without this warm-up a
    cold free-tier instance opens a fresh PostgreSQL connection for each key.
    """
    if not runtime.DATABASE_URL:
        return
    global _settings_table_ready
    with runtime.db() as connection:
        if not _settings_table_ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS gateway_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at BIGINT NOT NULL)"
            )
            _settings_table_ready = True
        rows = connection.execute("SELECT key, value FROM gateway_settings").fetchall()
    now = time.monotonic()
    runtime_id = id(runtime)
    for row in rows:
        _settings_cache[(runtime_id, str(row[0]))] = (now, str(row[1]))


def load_secret_setting(runtime: Any, key: str) -> str:
    """Read an encrypted setting; returns '' when missing/undecryptable."""
    if not runtime.DATABASE_URL:
        return ""
    stored = _get_setting(runtime, key)
    if not stored:
        return ""
    try:
        return runtime.decrypt_token(stored)
    except Exception:
        return ""


def save_secret_setting(runtime: Any, key: str, value: str) -> None:
    if not runtime.DATABASE_URL:
        return
    _set_setting(runtime, key, runtime.encrypt_token(value))


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
    # Write-through makes admin changes visible immediately without another SELECT.
    _settings_cache[(id(runtime), key)] = (time.monotonic(), value)


def provider_exists(runtime: Any, provider: str) -> bool:
    if provider in KNOWN_PROVIDERS:
        return True
    checker = getattr(runtime, "is_dynamic_provider", None)
    return bool(checker and checker(provider))


def get_active_provider(runtime: Any) -> str:
    value = _get_setting(runtime, "active_provider")
    return value if provider_exists(runtime, value) else PROVIDER_CHATGPT


def get_active_model(runtime: Any) -> str:
    return _get_setting(runtime, "active_model")


def set_active_provider_model(runtime: Any, provider: str, model: str = "") -> None:
    if not provider_exists(runtime, provider):
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}.")
    _set_setting(runtime, "active_provider", provider)
    _set_setting(runtime, "active_model", str(model or "").strip()[:200])


def bai_configured(runtime: Any) -> bool:
    return bool(getattr(runtime, "BAI_API_KEY", ""))


def resolve_model(runtime: Any, requested: Any, default: str) -> str:
    """Return the model the client asked for, unless it is empty/an alias —
    then fall back to the client's model, the admin's global pick, or the default."""
    model = str(requested or "").strip()
    policy = get_client_policy()
    global_provider = get_active_provider(runtime)
    effective_provider = policy.get("provider") if policy and policy.get("provider") else global_provider
    # Clients commonly retain a generic default such as `gpt-4o-mini` when
    # pointed at a new base URL. It is not a Codex backend model, so forwarding
    # it makes the ChatGPT route fail. Treat unknown ids as aliases only for
    # the ChatGPT provider; third-party providers retain their own catalogs.
    if effective_provider == PROVIDER_CHATGPT and model and model not in DEFAULT_MODEL_ALIASES and model not in CHATGPT_ADMIN_MODELS:
        if policy and policy.get("model"):
            return policy["model"]
        if not policy or policy.get("provider") == global_provider:
            active = get_active_model(runtime)
            if active:
                return active
        return default
    if model in DEFAULT_MODEL_ALIASES:
        if policy and policy.get("model"):
            return policy["model"]
        if not policy or policy.get("provider") == global_provider:
            active = get_active_model(runtime)
            if active:
                return active
    return model or default


def resolve_provider_model(runtime: Any, provider: str, requested: Any) -> str:
    """Resolve the model for a catalog-backed provider. ZCode-style clients often
    hardcode a model id (e.g. glm-5.3-flash) that the active provider does not
    carry; forwarding it verbatim makes the upstream fail. If the requested id is
    unknown to the provider, fall back to the client key's model, the admin's
    global pick, or the first entry of the provider catalog."""
    model = str(requested or "").strip()
    is_dynamic = bool(getattr(runtime, "is_dynamic_provider", lambda _provider: False)(provider))
    if provider == PROVIDER_GENERIC and not runtime.generic_configured():
        raise HTTPException(
            status_code=503,
            detail="Generic OpenAI-compatible provider is not configured. Set base_url, api_key, and model in /admin.",
        )
    if is_dynamic and not runtime.dynamic_provider_configured(provider):
        raise HTTPException(status_code=503, detail="Custom OpenAI-compatible provider is not configured or no longer exists.")
    if provider == PROVIDER_BAI:
        catalog = bai_list_models(runtime)
    elif provider == PROVIDER_OPENROUTER:
        catalog = runtime.openrouter_list_models()
    elif provider == PROVIDER_TOKENROUTER:
        catalog = runtime.tokenrouter_list_models()
    elif provider == PROVIDER_NOTION:
        catalog = runtime.notion_list_models()
    elif provider == PROVIDER_NIM:
        catalog = runtime.nim_list_models()
    elif provider == PROVIDER_GENERIC:
        catalog = runtime.generic_list_models()
    elif is_dynamic:
        catalog = runtime.dynamic_provider_list_models(provider)
    else:
        catalog = []
    if catalog and model and model not in DEFAULT_MODEL_ALIASES and model in catalog:
        return model
    policy = get_client_policy()
    if policy and policy.get("model"):
        return policy["model"]
    # A client key pinned to a different provider must not inherit the global
    # model chosen for another provider. Prefer that client's provider default.
    global_provider = get_active_provider(runtime)
    if policy and policy.get("provider") and policy.get("provider") != global_provider and catalog:
        return catalog[0]
    active = get_active_model(runtime)
    if active:
        return active
    if catalog:
        return catalog[0]
    fallback = PROVIDER_FALLBACK_CATALOGS.get(provider, ())
    if fallback:
        return fallback[0]
    # B.AI has no trustworthy public catalog. Do not silently send a model id
    # copied from another client (for example ZCode's GLM default) to it.
    if provider == PROVIDER_BAI:
        raise HTTPException(
            status_code=503,
            detail="B.AI model catalog is unavailable. Select a B.AI model in /admin before sending requests.",
        )
    raise HTTPException(status_code=503, detail=f"No usable model is configured for provider {provider}.")


def sanitize_chat_payload(provider: str, payload: dict[str, Any], model: str) -> dict[str, Any]:
    """Remove client-library envelopes that OpenAI-compatible upstreams reject.

    ZCode and a few SDKs put provider options in ``extra_body``. That field is
    not part of the Chat Completions schema and notably causes NIM to reject an
    otherwise valid request. Keep standard OpenAI fields intact and apply only
    the small provider-specific compatibility filter needed by strict APIs.
    """
    sanitized = dict(payload)
    sanitized.pop("extra_body", None)
    sanitized.pop("extra_headers", None)
    if provider == PROVIDER_NIM:
        for field in ("reasoning_effort", "service_tier", "verbosity", "store"):
            sanitized.pop(field, None)
    sanitized["model"] = model
    return sanitized


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


def _clear_client_policy_cache(runtime: Any) -> None:
    runtime_id = id(runtime)
    for cache_key in [item for item in _client_policy_cache if item[0] == runtime_id]:
        _client_policy_cache.pop(cache_key, None)


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
    cache_key = (id(runtime), digest)
    now = time.monotonic()
    cached = _client_policy_cache.get(cache_key)
    if cached and now - cached[0] < CLIENT_POLICY_CACHE_TTL_SECONDS:
        return dict(cached[1])
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
    policy = {"provider": str(row[0]), "model": str(row[1] or "")}
    if len(_client_policy_cache) >= CLIENT_POLICY_CACHE_MAX_ENTRIES:
        _client_policy_cache.clear()
    _client_policy_cache[cache_key] = (now, policy)
    return dict(policy)


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
            timeout=6,
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
        _clear_client_policy_cache(runtime)
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
    _clear_client_policy_cache(runtime)
    return client_id


def _update_client(runtime: Any, client_id: str, payload: dict[str, Any]) -> None:
    updates: list[tuple[str, Any]] = []
    if isinstance(payload.get("provider"), str):
        if not provider_exists(runtime, payload["provider"]):
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
        _clear_client_policy_cache(runtime)
        return
    assignments = ", ".join(f"{field}=%s" for field, _ in updates)
    values = [value for _, value in updates] + [client_id]
    with runtime.db() as connection:
        _ensure_client_table(connection)
        if connection.execute(f"UPDATE gateway_api_keys SET {assignments} WHERE id=%s", tuple(values)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Client key not found.")
    _clear_client_policy_cache(runtime)


def _delete_client(runtime: Any, client_id: str) -> None:
    if not runtime.DATABASE_URL:
        if _memory_clients.pop(client_id, None) is None:
            raise HTTPException(status_code=404, detail="Client key not found.")
        _clear_client_policy_cache(runtime)
        return
    with runtime.db() as connection:
        _ensure_client_table(connection)
        if connection.execute("DELETE FROM gateway_api_keys WHERE id=%s", (client_id,)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Client key not found.")
    _clear_client_policy_cache(runtime)


def _client_provider_usage(runtime: Any, provider: str) -> int:
    if not runtime.DATABASE_URL:
        return sum(1 for entry in _memory_clients.values() if entry.get("provider") == provider)
    with runtime.db() as connection:
        _ensure_client_table(connection)
        row = connection.execute("SELECT COUNT(*) FROM gateway_api_keys WHERE provider=%s", (provider,)).fetchone()
    return int(row[0]) if row else 0


def install(runtime: Any) -> None:
    runtime.BAI_API_KEY = os.getenv("BAI_API_KEY", "").strip()
    runtime.BAI_BASE_URL = os.getenv("BAI_BASE_URL", DEFAULT_BAI_BASE_URL).strip().rstrip("/") or DEFAULT_BAI_BASE_URL
    runtime.get_active_provider = lambda: get_active_provider(runtime)
    runtime.get_active_model = lambda: get_active_model(runtime)
    runtime.provider_exists = lambda provider: provider_exists(runtime, provider)
    runtime.set_active_provider_model = lambda provider, model="": set_active_provider_model(runtime, provider, model)
    runtime.bai_configured = lambda: bai_configured(runtime)
    runtime.resolve_model = lambda requested, default: resolve_model(runtime, requested, default)
    runtime.resolve_provider_model = lambda provider, requested: resolve_provider_model(runtime, provider, requested)
    runtime.sanitize_chat_payload = lambda provider, payload, model: sanitize_chat_payload(provider, payload, model)
    runtime.bai_request = lambda path, **kwargs: bai_request(runtime, path, **kwargs)
    runtime.bai_list_models = lambda: bai_list_models(runtime)
    runtime.lookup_client_policy = lambda supplied: _lookup_client_policy(runtime, supplied)
    runtime.set_client_policy = set_client_policy
    runtime.get_client_policy = get_client_policy

    # Warm persisted provider/admin settings in one query so each provider installer
    # does not open its own PostgreSQL connection during a free-tier cold start.
    _preload_settings(runtime)

    # Lazy import to avoid a circular dependency (openrouter_provider reads settings helpers).
    from faable.generic_provider import install as install_generic_provider
    from faable.nim_provider import install as install_nim_provider
    from faable.notion_provider import install as install_notion_provider
    from faable.openrouter_provider import install as install_openrouter_provider
    from faable.tokenrouter_provider import install as install_tokenrouter_provider

    install_notion_provider(runtime)
    install_generic_provider(runtime)
    install_openrouter_provider(runtime)
    install_tokenrouter_provider(runtime)
    install_nim_provider(runtime)

    runtime.app.router.routes[:] = [
        route for route in runtime.app.router.routes if getattr(route, "path", None) != "/v1/models"
    ]

    def models_endpoint(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        runtime.authorize(authorization, x_api_key)
        created = int(time.time())
        policy = get_client_policy()
        active = policy["provider"] if policy and policy.get("provider") else get_active_provider(runtime)
        if active == PROVIDER_BAI:
            catalog = bai_list_models(runtime)
            owned_by = "b-ai"
        elif active == PROVIDER_OPENROUTER:
            catalog = runtime.openrouter_list_models() or list(OPENROUTER_PUBLIC_CATALOG)
            owned_by = "openrouter"
        elif active == PROVIDER_TOKENROUTER:
            catalog = runtime.tokenrouter_list_models() or list(TOKENROUTER_PUBLIC_CATALOG)
            owned_by = "tokenrouter"
        elif active == PROVIDER_NOTION:
            catalog = runtime.notion_list_models() or list(NOTION_PUBLIC_CATALOG)
            owned_by = "notion"
        elif active == PROVIDER_NIM:
            catalog = runtime.nim_list_models() or list(NIM_PUBLIC_CATALOG)
            owned_by = "nvidia-nim"
        elif active == PROVIDER_GENERIC:
            catalog = runtime.generic_list_models()
            owned_by = "openai-compatible"
        elif getattr(runtime, "is_dynamic_provider", lambda _provider: False)(active):
            catalog = runtime.dynamic_provider_list_models(active)
            owned_by = active
        else:
            catalog = list(getattr(runtime, "PUBLIC_MODEL_CATALOG", ("chatgpt-gpt-5.6",)))
            owned_by = "openai-chatgpt"
        return {
            "object": "list",
            "data": [{"id": model_id, "object": "model", "created": created, "owned_by": owned_by} for model_id in catalog],
        }

    def provider_configured(provider: str) -> bool:
        if provider == PROVIDER_CHATGPT:
            return True
        if provider == PROVIDER_BAI:
            return bai_configured(runtime)
        if provider == PROVIDER_OPENROUTER:
            return runtime.openrouter_configured()
        if provider == PROVIDER_TOKENROUTER:
            return runtime.tokenrouter_configured()
        if provider == PROVIDER_NOTION:
            return runtime.notion_configured()
        if provider == PROVIDER_NIM:
            return runtime.nim_configured()
        if provider == PROVIDER_GENERIC:
            return runtime.generic_configured()
        if getattr(runtime, "is_dynamic_provider", lambda _provider: False)(provider):
            return runtime.dynamic_provider_configured(provider)
        return False

    def fallback_models(provider: str) -> list[str]:
        if provider == PROVIDER_CHATGPT:
            return list(CHATGPT_ADMIN_MODELS)
        if provider == PROVIDER_OPENROUTER:
            return list(OPENROUTER_PUBLIC_CATALOG)
        if provider == PROVIDER_TOKENROUTER:
            return list(TOKENROUTER_PUBLIC_CATALOG)
        if provider == PROVIDER_NOTION:
            return list(NOTION_PUBLIC_CATALOG)
        if provider == PROVIDER_NIM:
            return list(NIM_PUBLIC_CATALOG)
        if provider == PROVIDER_GENERIC:
            return runtime.generic_list_models()
        if provider == PROVIDER_BAI:
            # Never make a network request while rendering /auth. Reuse a warm
            # cache when available; the UI fetches the live catalog lazily.
            return list(_models_cache.get("models") or [])
        if getattr(runtime, "is_dynamic_provider", lambda _provider: False)(provider):
            return runtime.dynamic_provider_list_models(provider)
        return []

    def live_models(provider: str) -> list[str]:
        if provider == PROVIDER_CHATGPT:
            return list(CHATGPT_ADMIN_MODELS)
        if provider == PROVIDER_BAI:
            return bai_list_models(runtime)
        if provider == PROVIDER_OPENROUTER:
            return runtime.openrouter_list_models()
        if provider == PROVIDER_TOKENROUTER:
            return runtime.tokenrouter_list_models()
        if provider == PROVIDER_NOTION:
            return runtime.notion_list_models()
        if provider == PROVIDER_NIM:
            return runtime.nim_list_models()
        if provider == PROVIDER_GENERIC:
            return runtime.generic_list_models()
        if getattr(runtime, "is_dynamic_provider", lambda _provider: False)(provider):
            return runtime.dynamic_provider_list_models(provider)
        return []

    def providers(request: Request) -> dict[str, Any]:
        """Fast admin bootstrap: local state only, never waits on provider APIs."""
        runtime.require_admin(request)
        active_provider = get_active_provider(runtime)
        return {
            "active_provider": active_provider,
            "active_model": get_active_model(runtime),
            "providers": [
                *[
                    {
                        "id": provider,
                        "label": PROVIDER_LABELS[provider],
                        "configured": provider_configured(provider),
                        "models": fallback_models(provider),
                        "kind": "builtin",
                        "editable": False,
                    }
                    for provider in KNOWN_PROVIDERS
                ],
                *[
                    {
                        "id": item["id"],
                        "label": item["name"],
                        "configured": item["configured"],
                        "models": [item["model"]] if item.get("model") else [],
                        "kind": "custom",
                        "editable": True,
                        "base_url": item["base_url"],
                    }
                    for item in runtime.list_dynamic_providers()
                ],
            ],
        }

    def provider_models(request: Request, provider: str) -> dict[str, Any]:
        """Fetch one provider catalog on demand after the admin UI is visible."""
        runtime.require_admin(request)
        if not provider_exists(runtime, provider):
            raise HTTPException(status_code=404, detail=f"Unsupported provider: {provider}.")
        configured = provider_configured(provider)
        fallback = fallback_models(provider)
        if provider != PROVIDER_CHATGPT and not configured:
            return {"provider": provider, "configured": False, "models": fallback, "source": "fallback"}
        models = live_models(provider)
        return {
            "provider": provider,
            "configured": configured,
            "models": models or fallback,
            "source": "live" if models else "fallback",
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
    runtime.app.add_api_route("/models", models_endpoint, methods=["GET"], include_in_schema=False)
    runtime.app.add_api_route("/auth/providers", providers, methods=["GET"])
    runtime.app.add_api_route("/auth/providers/{provider}/models", provider_models, methods=["GET"])
    runtime.app.add_api_route("/auth/providers/select", select_provider, methods=["POST"])

    def list_clients(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"data": _client_rows(runtime)}

    def create_client(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        label = str(payload.get("label") or "Client").strip()[:100] or "Client"
        provider = payload.get("provider")
        if not isinstance(provider, str) or not provider_exists(runtime, provider):
            raise HTTPException(status_code=400, detail="provider is unknown or no longer exists.")
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

    def delete_custom_provider(request: Request, provider_id: str) -> dict[str, Any]:
        runtime.require_admin(request)
        if not getattr(runtime, "is_dynamic_provider", lambda _provider: False)(provider_id):
            raise HTTPException(status_code=404, detail="Custom provider not found.")
        if get_active_provider(runtime) == provider_id:
            raise HTTPException(status_code=409, detail="Provider is currently selected globally. Switch provider before deleting it.")
        usage = _client_provider_usage(runtime, provider_id)
        if usage:
            raise HTTPException(status_code=409, detail=f"Provider is assigned to {usage} client key(s). Reassign or delete those clients first.")
        from faable.generic_provider import delete_dynamic_provider
        delete_dynamic_provider(runtime, provider_id)
        return {"ok": True, "data": runtime.list_dynamic_providers()}

    runtime.app.add_api_route("/auth/custom-providers/{provider_id}", delete_custom_provider, methods=["DELETE"])

    # Mirror admin JSON endpoints under /admin-api. This gives deployments a
    # neutral management path when enterprise web filters aggressively classify
    # generic /auth URLs, while preserving every existing /auth route.
    existing_aliases = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", None) or ())))
        for route in runtime.app.router.routes
    }
    for route in list(runtime.app.router.routes):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path.startswith("/auth/") or not methods or endpoint is None:
            continue
        alias = "/admin-api" + path[len("/auth"):]
        route_methods = sorted(method for method in methods if method not in {"HEAD", "OPTIONS"})
        if not route_methods:
            continue
        signature = (alias, tuple(route_methods))
        if signature in existing_aliases:
            continue
        runtime.app.add_api_route(alias, endpoint, methods=route_methods, include_in_schema=False)
        existing_aliases.add(signature)
