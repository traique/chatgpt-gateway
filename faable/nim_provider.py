"""NVIDIA NIM provider: admin-pasted API key (nvapi-...), OpenAI-native passthrough.

NVIDIA hosts the catalog on integrate.api.nvidia.com as a free tier with rate
limits, so the whole /models list is "free"; the free filter below only drops
models that are not chat-completions capable (embeddings, rerankers, OCR,
retrievers, reward/guard models). Set NIM_MODELS_FILTER_MODE=all to disable.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

from fastapi import HTTPException, Request

DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODELS_CACHE_TTL_SECONDS = 300

# Models that consume no credits and are usable via /chat/completions get kept;
# everything matching these patterns is a non-chat endpoint or special-purpose.
NIM_FREE_EXCLUDE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"embed",
        r"rerank",
        r"retriev",
        r"reward",
        r"guard",
        r"ocr",
        r"deplot",
        r"tokenizer",
        r"safety",
        r"moderation",
        r"diffusion",
        r"recurrentgemma",
    )
)

NIM_FALLBACK_CATALOG: tuple[str, ...] = (
    "meta/llama-3.3-70b-instruct",
    "deepseek-ai/deepseek-r1",
    "qwen/qwen2.5-coder-32b-instruct",
    "mistralai/mistral-large-2-instruct",
    "google/gemma-3-27b-it",
)

_nim_models_cache: dict[str, Any] = {"ts": 0.0, "models": []}


def nim_api_key(runtime: Any) -> str:
    return str(getattr(runtime, "NIM_API_KEY", "") or "").strip()


def nim_configured(runtime: Any) -> bool:
    return bool(nim_api_key(runtime))


def _filter_mode() -> str:
    return os.getenv("NIM_MODELS_FILTER_MODE", "free").strip().lower() or "free"


def _extra_excludes() -> list[str]:
    raw = os.getenv("NIM_FREE_EXCLUDE", "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def is_free_chat_model(model_id: str) -> bool:
    combined = model_id.lower()
    for pattern in NIM_FREE_EXCLUDE_PATTERNS:
        if pattern.search(combined):
            return False
    for extra in _extra_excludes():
        if extra.lower() in combined:
            return False
    return True


def nim_list_models(runtime: Any) -> list[str]:
    """Fetch the NIM catalog; in 'free' mode keep only chat-capable models."""
    global _nim_models_cache
    now = time.time()
    cached = list(_nim_models_cache["models"])
    if cached and now - float(_nim_models_cache["ts"]) < NIM_MODELS_CACHE_TTL_SECONDS:
        return cached
    api_key = nim_api_key(runtime)
    if not api_key:
        return []
    try:
        response = runtime.requests.get(
            f"{runtime.NIM_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
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
            if _filter_mode() == "all" or is_free_chat_model(model_id):
                ids.append(model_id)
    ids.sort()
    if ids:
        _nim_models_cache = {"ts": now, "models": ids}
        return ids
    return cached


def nim_request(
    runtime: Any,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> Any:
    api_key = nim_api_key(runtime)
    if not api_key:
        raise HTTPException(status_code=503, detail="NIM_API_KEY is not configured. Set it in /auth.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    try:
        return runtime.requests.post(
            f"{runtime.NIM_BASE_URL}{path}",
            headers=headers,
            **({"json": json_payload} if json_payload is not None else {}),
            timeout=timeout,
            stream=stream,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"NVIDIA NIM transport failed: {error}") from error


def save_nim_key(runtime: Any, api_key: str) -> None:
    from .provider_routing import save_secret_setting

    api_key = api_key.strip()
    save_secret_setting(runtime, "nim_api_key_enc", api_key)
    runtime.NIM_API_KEY = api_key


def load_nim_key(runtime: Any) -> None:
    if runtime.DATABASE_URL:
        from .provider_routing import load_secret_setting

        runtime.NIM_API_KEY = load_secret_setting(runtime, "nim_api_key_enc")


def install(runtime: Any) -> None:
    runtime.NIM_API_KEY = os.getenv("NIM_API_KEY", "").strip()
    runtime.NIM_BASE_URL = os.getenv("NIM_BASE_URL", DEFAULT_NIM_BASE_URL).strip().rstrip("/") or DEFAULT_NIM_BASE_URL
    load_nim_key(runtime)
    runtime.nim_configured = lambda: nim_configured(runtime)
    runtime.nim_request = lambda path, **kwargs: nim_request(runtime, path, **kwargs)
    runtime.nim_list_models = lambda: nim_list_models(runtime)

    def save_key(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        runtime.require_admin(request)
        api_key = str(payload.get("api_key") or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required.")
        save_nim_key(runtime, api_key)
        return {"ok": True, "configured": True}

    def key_status(request: Request) -> dict[str, Any]:
        runtime.require_admin(request)
        return {"configured": nim_configured(runtime), "models": nim_list_models(runtime)}

    runtime.app.add_api_route("/auth/nim/key", save_key, methods=["POST"])
    runtime.app.add_api_route("/auth/nim/key", key_status, methods=["GET"])
