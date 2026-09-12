"""TokenRouter provider: admin-pasted API key, OpenAI-native passthrough."""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request

DEFAULT_TOKENROUTER_BASE_URL = "https://api.tokenrouter.io/v1"
TOKENROUTER_MODEL_CATALOG: tuple[str, ...] = (
    "auto",
    "auto:balance",
    "auto:cost",
    "auto:quality",
    "auto:latency",
    "openai/gpt-5-mini",
    "anthropic/claude-sonnet-4-5",
)
TOKENROUTER_MODELS_CACHE_TTL_SECONDS = 300

_tokenrouter_models_cache: dict[str, Any] = {"ts": 0.0, "models": []}


def tokenrouter_api_key(runtime: Any) -> str:
    return str(getattr(runtime, "TOKENROUTER_API_KEY", "") or "").strip()


def tokenrouter_configured(runtime: Any) -> bool:
    return bool(tokenrouter_api_key(runtime))


def tokenrouter_request(
    runtime: Any,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    api_key = tokenrouter_api_key(runtime)
    if not api_key:
        raise HTTPException(status_code=503, detail="TOKENROUTER_API_KEY is not configured. Set it in /auth.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        return runtime.requests.post(
            f"{runtime.TOKENROUTER_BASE_URL}{path}",
            headers=headers,
            **({"json": json_payload} if json_payload is not None else {}),
            timeout=timeout,
            stream=stream,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"TokenRouter transport failed: {error}") from error


def tokenrouter_list_models(runtime: Any) -> list[str]:
    global _tokenrouter_models_cache
    now = time.time()
    cached = list(_tokenrouter_models_cache["models"])
    if cached and now - float(_tokenrouter_models_cache["ts"]) < TOKENROUTER_MODELS_CACHE_TTL_SECONDS:
        return cached
    api_key = tokenrouter_api_key(runtime)
    if not api_key:
        return []
    try:
        response = runtime.requests.get(
            f"{runtime.TOKENROUTER_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=6,
        )
        payload = response.json()
    except Exception:
        return cached
    ids: list[str] = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        ids = sorted(
            str(item["id"])
            for item in data
            if isinstance(item, dict) and item.get("id")
        )
    if ids:
        _tokenrouter_models_cache = {"ts": now, "models": ids}
        return ids
    return cached


def save_tokenrouter_key(runtime: Any, api_key: str) -> None:
    from .provider_routing import save_secret_setting

    api_key = api_key.strip()
    save_secret_setting(runtime, "tokenrouter_api_key_enc", api_key)
    runtime.TOKENROUTER_API_KEY = api_key


def load_tokenrouter_key(runtime: Any) -> None:
    if runtime.DATABASE_URL:
        from .provider_routing import load_secret_setting

        stored = load_secret_setting(runtime, "tokenrouter_api_key_enc")
        if stored:
            runtime.TOKENROUTER_API_KEY = stored


def install(runtime: Any) -> None:
    runtime.TOKENROUTER_API_KEY = os.getenv("TOKENROUTER_API_KEY", "").strip()
    runtime.TOKENROUTER_BASE_URL = (
        os.getenv("TOKENROUTER_BASE_URL", DEFAULT_TOKENROUTER_BASE_URL).strip().rstrip("/")
        or DEFAULT_TOKENROUTER_BASE_URL
    )
    load_tokenrouter_key(runtime)
    runtime.tokenrouter_configured = lambda: tokenrouter_configured(runtime)
    runtime.tokenrouter_request = lambda path, **kwargs: tokenrouter_request(runtime, path, **kwargs)
    runtime.tokenrouter_list_models = lambda: tokenrouter_list_models(runtime)

    def save_key(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        api_key = str(payload.get("api_key") or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required.")
        save_tokenrouter_key(runtime, api_key)
        return {"ok": True, "configured": True}

    def key_status(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {
            "configured": tokenrouter_configured(runtime),
            "base_url": runtime.TOKENROUTER_BASE_URL,
        }

    runtime.app.add_api_route("/auth/tokenrouter/key", save_key, methods=["POST"])
    runtime.app.add_api_route("/auth/tokenrouter/key", key_status, methods=["GET"])
