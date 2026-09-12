"""OpenRouter provider: admin-pasted API key, OpenAI-native passthrough."""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_CATALOG: tuple[str, ...] = (
    "openrouter/auto",
    "openai/gpt-5.6",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.8",
    "google/gemini-3-flash",
    "google/gemini-3.5-flash",
    "deepseek/deepseek-v4-pro",
    "x-ai/grok-4.5",
    "meta-llama/llama-4-maverick",
    "mistralai/mistral-large",
)
OPENROUTER_MODELS_CACHE_TTL_SECONDS = 300

# "Free" filter: OpenRouter marks zero-cost models with a ":free" suffix
# (e.g. "deepseek/deepseek-chat-v4:free"). Set OPENROUTER_MODELS_FILTER_MODE=all
# to list the whole catalog instead.
_openrouter_models_cache: dict[str, Any] = {"ts": 0.0, "models": []}


def _openrouter_filter_mode() -> str:
    return os.getenv("OPENROUTER_MODELS_FILTER_MODE", "free").strip().lower() or "free"


def is_free_model(model_id: str) -> bool:
    return model_id.lower().rstrip().endswith(":free")


def openrouter_api_key(runtime: Any) -> str:
    key = str(getattr(runtime, "OPENROUTER_API_KEY", "") or "").strip()
    return key


def openrouter_configured(runtime: Any) -> bool:
    return bool(openrouter_api_key(runtime))


def openrouter_request(
    runtime: Any,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    api_key = openrouter_api_key(runtime)
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not configured. Set it in /auth.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/traique/chatgpt-gateway",
        "X-Title": "chatgpt-gateway",
    }
    try:
        return runtime.requests.post(
            f"{runtime.OPENROUTER_BASE_URL}{path}",
            headers=headers,
            **({"json": json_payload} if json_payload is not None else {}),
            timeout=timeout,
            stream=stream,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"OpenRouter transport failed: {error}") from error


def openrouter_list_models(runtime: Any) -> list[str]:
    global _openrouter_models_cache
    now = time.time()
    cached = list(_openrouter_models_cache["models"])
    if cached and now - float(_openrouter_models_cache["ts"]) < OPENROUTER_MODELS_CACHE_TTL_SECONDS:
        return cached
    api_key = openrouter_api_key(runtime)
    if not api_key:
        return []
    try:
        response = runtime.requests.get(
            f"{runtime.OPENROUTER_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=6,
        )
        payload = response.json()
    except Exception:
        return cached
    ids: list[str] = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            if _openrouter_filter_mode() == "all" or is_free_model(model_id):
                ids.append(model_id)
    ids.sort()
    if ids:
        _openrouter_models_cache = {"ts": now, "models": ids}
        return ids
    return cached


def save_openrouter_key(runtime: Any, api_key: str) -> None:
    """Persist the key so it survives restarts (DB when available, memory otherwise)."""
    from .provider_routing import save_secret_setting

    api_key = api_key.strip()
    save_secret_setting(runtime, "openrouter_api_key_enc", api_key)
    runtime.OPENROUTER_API_KEY = api_key


def load_openrouter_key(runtime: Any) -> None:
    if runtime.DATABASE_URL:
        from .provider_routing import load_secret_setting

        runtime.OPENROUTER_API_KEY = load_secret_setting(runtime, "openrouter_api_key_enc")


def install(runtime: Any) -> None:
    runtime.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    runtime.OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip().rstrip("/") or DEFAULT_OPENROUTER_BASE_URL
    load_openrouter_key(runtime)
    runtime.openrouter_configured = lambda: openrouter_configured(runtime)
    runtime.openrouter_request = lambda path, **kwargs: openrouter_request(runtime, path, **kwargs)
    runtime.openrouter_list_models = lambda: openrouter_list_models(runtime)

    def save_key(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        api_key = str(payload.get("api_key") or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required.")
        save_openrouter_key(runtime, api_key)
        return {"ok": True, "configured": True}

    def key_status(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"configured": openrouter_configured(runtime)}

    runtime.app.add_api_route("/auth/openrouter/key", save_key, methods=["POST"])
    runtime.app.add_api_route("/auth/openrouter/key", key_status, methods=["GET"])
