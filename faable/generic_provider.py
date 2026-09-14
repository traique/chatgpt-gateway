"""Reusable OpenAI-compatible provider adapter.

The legacy ``generic`` provider remains available for backwards compatibility.
This module also owns a dynamic provider registry so administrators can add any
number of OpenAI-compatible upstreams without creating provider-specific Python
files. Every dynamic provider only needs a display name, base URL, API key, and
model id.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

DYNAMIC_PROVIDER_PREFIX = "custom-"
_memory_dynamic_providers: dict[str, dict[str, Any]] = {}
_dynamic_provider_table_ready = False
_dynamic_provider_cache: dict[str, tuple[float, dict[str, Any]]] = {}
DYNAMIC_PROVIDER_CACHE_TTL_SECONDS = max(5, int(os.getenv("GATEWAY_PROVIDER_CACHE_TTL", "120")))


def normalize_base_url(value: str) -> str:
    base_url = str(value or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="base_url must be an absolute http(s) URL.")
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="base_url must not contain a query string or fragment.")
    return base_url


def _normalize_name(value: str) -> str:
    name = str(value or "").strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    return name


def _normalize_model(value: str) -> str:
    model = str(value or "").strip()[:200]
    if not model:
        raise HTTPException(status_code=400, detail="model is required.")
    return model


def _normalize_api_key(value: str, *, required: bool = True) -> str:
    api_key = str(value or "").strip()
    if required and not api_key:
        raise HTTPException(status_code=400, detail="api_key is required.")
    return api_key


def _ensure_dynamic_provider_table(connection: Any) -> None:
    global _dynamic_provider_table_ready
    if not _dynamic_provider_table_ready:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS gateway_dynamic_providers ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, api_key_enc TEXT NOT NULL, "
            "model TEXT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)"
        )
        _dynamic_provider_table_ready = True


def _public_dynamic(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(entry["id"]),
        "name": str(entry["name"]),
        "base_url": str(entry["base_url"]),
        "model": str(entry["model"]),
        "configured": bool(entry.get("api_key")),
        "created_at": int(entry.get("created_at") or 0),
        "updated_at": int(entry.get("updated_at") or 0),
    }


def list_dynamic_providers(runtime: Any) -> list[dict[str, Any]]:
    if not runtime.DATABASE_URL:
        entries = sorted(
            _memory_dynamic_providers.values(),
            key=lambda item: int(item.get("created_at") or 0),
        )
        return [_public_dynamic(entry) for entry in entries]
    with runtime.db() as connection:
        _ensure_dynamic_provider_table(connection)
        rows = connection.execute(
            "SELECT id, name, base_url, api_key_enc, model, created_at, updated_at "
            "FROM gateway_dynamic_providers ORDER BY created_at ASC"
        ).fetchall()
    result: list[dict[str, Any]] = []
    now = time.time()
    for row in rows:
        try:
            api_key = runtime.decrypt_token(str(row[3]))
        except Exception:
            api_key = ""
        entry = {
            "id": str(row[0]), "name": str(row[1]), "base_url": str(row[2]),
            "api_key": api_key, "model": str(row[4]), "created_at": int(row[5]), "updated_at": int(row[6]),
        }
        _dynamic_provider_cache[entry["id"]] = (now, entry)
        result.append(_public_dynamic(entry))
    return result


def get_dynamic_provider(runtime: Any, provider_id: str) -> dict[str, Any] | None:
    provider_id = str(provider_id or "").strip()
    if not provider_id.startswith(DYNAMIC_PROVIDER_PREFIX):
        return None
    if not runtime.DATABASE_URL:
        entry = _memory_dynamic_providers.get(provider_id)
        return dict(entry) if entry else None
    cached = _dynamic_provider_cache.get(provider_id)
    now = time.time()
    if cached and now - cached[0] < DYNAMIC_PROVIDER_CACHE_TTL_SECONDS:
        return dict(cached[1])
    with runtime.db() as connection:
        _ensure_dynamic_provider_table(connection)
        row = connection.execute(
            "SELECT id, name, base_url, api_key_enc, model, created_at, updated_at "
            "FROM gateway_dynamic_providers WHERE id=%s",
            (provider_id,),
        ).fetchone()
    if not row:
        return None
    try:
        api_key = runtime.decrypt_token(str(row[3]))
    except Exception:
        api_key = ""
    entry = {
        "id": str(row[0]), "name": str(row[1]), "base_url": str(row[2]),
        "api_key": api_key, "model": str(row[4]), "created_at": int(row[5]), "updated_at": int(row[6]),
    }
    _dynamic_provider_cache[provider_id] = (now, entry)
    return dict(entry)


def create_dynamic_provider(runtime: Any, name: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    normalized_name = _normalize_name(name)
    normalized_url = normalize_base_url(base_url)
    normalized_key = _normalize_api_key(api_key)
    normalized_model = _normalize_model(model)
    now = int(time.time() * 1000)
    provider_id = DYNAMIC_PROVIDER_PREFIX + uuid.uuid4().hex
    entry = {
        "id": provider_id, "name": normalized_name, "base_url": normalized_url,
        "api_key": normalized_key, "model": normalized_model,
        "created_at": now, "updated_at": now,
    }
    if not runtime.DATABASE_URL:
        _memory_dynamic_providers[provider_id] = entry
        return _public_dynamic(entry)
    with runtime.db() as connection:
        _ensure_dynamic_provider_table(connection)
        connection.execute(
            "INSERT INTO gateway_dynamic_providers "
            "(id, name, base_url, api_key_enc, model, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (provider_id, normalized_name, normalized_url, runtime.encrypt_token(normalized_key), normalized_model, now, now),
        )
    _dynamic_provider_cache[provider_id] = (time.time(), entry)
    return _public_dynamic(entry)


def update_dynamic_provider(runtime: Any, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = get_dynamic_provider(runtime, provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Custom provider not found.")
    name = _normalize_name(payload.get("name", existing["name"]))
    base_url = normalize_base_url(payload.get("base_url", existing["base_url"]))
    model = _normalize_model(payload.get("model", existing["model"]))
    supplied_key = _normalize_api_key(payload.get("api_key", ""), required=False)
    api_key = supplied_key or str(existing.get("api_key") or "")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required.")
    now = int(time.time() * 1000)
    updated = {
        **existing, "name": name, "base_url": base_url, "api_key": api_key,
        "model": model, "updated_at": now,
    }
    if not runtime.DATABASE_URL:
        _memory_dynamic_providers[provider_id] = updated
        return _public_dynamic(updated)
    with runtime.db() as connection:
        _ensure_dynamic_provider_table(connection)
        connection.execute(
            "UPDATE gateway_dynamic_providers SET name=%s, base_url=%s, api_key_enc=%s, model=%s, updated_at=%s WHERE id=%s",
            (name, base_url, runtime.encrypt_token(api_key), model, now, provider_id),
        )
    _dynamic_provider_cache[provider_id] = (time.time(), updated)
    return _public_dynamic(updated)


def delete_dynamic_provider(runtime: Any, provider_id: str) -> None:
    if not runtime.DATABASE_URL:
        if _memory_dynamic_providers.pop(provider_id, None) is None:
            raise HTTPException(status_code=404, detail="Custom provider not found.")
        _dynamic_provider_cache.pop(provider_id, None)
        return
    with runtime.db() as connection:
        _ensure_dynamic_provider_table(connection)
        result = connection.execute("DELETE FROM gateway_dynamic_providers WHERE id=%s", (provider_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Custom provider not found.")
    _dynamic_provider_cache.pop(provider_id, None)


def dynamic_provider_exists(runtime: Any, provider_id: str) -> bool:
    return get_dynamic_provider(runtime, provider_id) is not None


def dynamic_provider_label(runtime: Any, provider_id: str) -> str:
    entry = get_dynamic_provider(runtime, provider_id)
    return str(entry["name"]) if entry else "OpenAI Compatible"


def dynamic_provider_configured(runtime: Any, provider_id: str) -> bool:
    entry = get_dynamic_provider(runtime, provider_id)
    return bool(entry and entry.get("base_url") and entry.get("api_key") and entry.get("model"))


def dynamic_provider_list_models(runtime: Any, provider_id: str) -> list[str]:
    entry = get_dynamic_provider(runtime, provider_id)
    model = str(entry.get("model") or "").strip() if entry else ""
    return [model] if model else []


def _openai_compatible_request(
    runtime: Any,
    *,
    base_url: str,
    api_key: str,
    provider_label: str,
    path: str,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    try:
        return runtime.requests.post(
            f"{base_url.rstrip('/')}{path}",
            headers=headers,
            **({"json": json_payload} if json_payload is not None else {}),
            timeout=timeout,
            stream=stream,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"{provider_label} transport failed: {error}") from error


def dynamic_provider_request(
    runtime: Any,
    provider_id: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    entry = get_dynamic_provider(runtime, provider_id)
    if not entry or not dynamic_provider_configured(runtime, provider_id):
        raise HTTPException(status_code=503, detail="Custom OpenAI-compatible provider is not configured or no longer exists.")
    return _openai_compatible_request(
        runtime,
        base_url=str(entry["base_url"]),
        api_key=str(entry["api_key"]),
        provider_label=str(entry["name"]),
        path=path,
        json_payload=json_payload,
        stream=stream,
        timeout=timeout,
    )


# Legacy single generic slot -------------------------------------------------

def generic_api_key(runtime: Any) -> str:
    return str(getattr(runtime, "GENERIC_API_KEY", "") or "").strip()


def generic_model(runtime: Any) -> str:
    return str(getattr(runtime, "GENERIC_MODEL", "") or "").strip()


def generic_configured(runtime: Any) -> bool:
    return bool(str(getattr(runtime, "GENERIC_BASE_URL", "") or "").strip() and generic_api_key(runtime) and generic_model(runtime))


def generic_list_models(runtime: Any) -> list[str]:
    model = generic_model(runtime)
    return [model] if model else []


def generic_request(runtime: Any, path: str, *, json_payload: dict[str, Any] | None = None, stream: bool = False, timeout: int = 120) -> Any:
    if not generic_configured(runtime):
        raise HTTPException(status_code=503, detail="Generic OpenAI-compatible provider is not configured. Set base_url, api_key, and model in /admin.")
    return _openai_compatible_request(
        runtime,
        base_url=runtime.GENERIC_BASE_URL,
        api_key=generic_api_key(runtime),
        provider_label="Generic provider",
        path=path,
        json_payload=json_payload,
        stream=stream,
        timeout=timeout,
    )


def save_generic_config(runtime: Any, base_url: str, api_key: str, model: str) -> None:
    from .provider_routing import _set_setting, save_secret_setting

    normalized_url = normalize_base_url(base_url)
    normalized_key = _normalize_api_key(api_key)
    normalized_model = _normalize_model(model)
    _set_setting(runtime, "generic_base_url", normalized_url)
    _set_setting(runtime, "generic_model", normalized_model)
    save_secret_setting(runtime, "generic_api_key_enc", normalized_key)
    runtime.GENERIC_BASE_URL = normalized_url
    runtime.GENERIC_API_KEY = normalized_key
    runtime.GENERIC_MODEL = normalized_model


def load_generic_config(runtime: Any) -> None:
    if not runtime.DATABASE_URL:
        return
    from .provider_routing import _get_setting, load_secret_setting

    stored_base_url = _get_setting(runtime, "generic_base_url").strip()
    stored_model = _get_setting(runtime, "generic_model").strip()
    stored_api_key = load_secret_setting(runtime, "generic_api_key_enc")
    if stored_base_url:
        runtime.GENERIC_BASE_URL = stored_base_url.rstrip("/")
    if stored_model:
        runtime.GENERIC_MODEL = stored_model
    if stored_api_key:
        runtime.GENERIC_API_KEY = stored_api_key


def install(runtime: Any) -> None:
    runtime.GENERIC_BASE_URL = os.getenv("GENERIC_BASE_URL", "").strip().rstrip("/")
    runtime.GENERIC_API_KEY = os.getenv("GENERIC_API_KEY", "").strip()
    runtime.GENERIC_MODEL = os.getenv("GENERIC_MODEL", "").strip()
    load_generic_config(runtime)

    runtime.generic_configured = lambda: generic_configured(runtime)
    runtime.generic_request = lambda path, **kwargs: generic_request(runtime, path, **kwargs)
    runtime.generic_list_models = lambda: generic_list_models(runtime)
    runtime.list_dynamic_providers = lambda: list_dynamic_providers(runtime)
    runtime.get_dynamic_provider = lambda provider_id: get_dynamic_provider(runtime, provider_id)
    runtime.is_dynamic_provider = lambda provider_id: dynamic_provider_exists(runtime, provider_id)
    runtime.dynamic_provider_configured = lambda provider_id: dynamic_provider_configured(runtime, provider_id)
    runtime.dynamic_provider_list_models = lambda provider_id: dynamic_provider_list_models(runtime, provider_id)
    runtime.dynamic_provider_label = lambda provider_id: dynamic_provider_label(runtime, provider_id)
    runtime.dynamic_provider_request = lambda provider_id, path, **kwargs: dynamic_provider_request(runtime, provider_id, path, **kwargs)

    def save_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        save_generic_config(runtime, str(payload.get("base_url") or ""), str(payload.get("api_key") or ""), str(payload.get("model") or ""))
        return {"ok": True, "configured": True, "base_url": runtime.GENERIC_BASE_URL, "model": runtime.GENERIC_MODEL}

    def config_status(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"configured": generic_configured(runtime), "base_url": str(getattr(runtime, "GENERIC_BASE_URL", "") or ""), "model": generic_model(runtime)}

    def dynamic_list(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"data": list_dynamic_providers(runtime)}

    def dynamic_create(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        data = create_dynamic_provider(
            runtime,
            str(payload.get("name") or ""),
            str(payload.get("base_url") or ""),
            str(payload.get("api_key") or ""),
            str(payload.get("model") or ""),
        )
        return {"ok": True, "provider": data, "data": list_dynamic_providers(runtime)}

    def dynamic_update(request: Request, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        data = update_dynamic_provider(runtime, provider_id, payload)
        return {"ok": True, "provider": data, "data": list_dynamic_providers(runtime)}

    runtime.app.add_api_route("/auth/generic/config", save_config, methods=["POST"])
    runtime.app.add_api_route("/auth/generic/config", config_status, methods=["GET"])
    runtime.app.add_api_route("/auth/custom-providers", dynamic_list, methods=["GET"])
    runtime.app.add_api_route("/auth/custom-providers", dynamic_create, methods=["POST"])
    runtime.app.add_api_route("/auth/custom-providers/{provider_id}", dynamic_update, methods=["POST"])
