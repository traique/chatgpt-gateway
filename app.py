import os
import time
from typing import Any

from curl_cffi import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

CHATGPT_ENDPOINT = os.getenv("CHATGPT_CODEX_ENDPOINT", "https://chatgpt.com/backend-api/codex/responses")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
CHATGPT_ACCESS_TOKEN = os.getenv("CHATGPT_ACCESS_TOKEN", "")
CHATGPT_ACCOUNT_ID = os.getenv("CHATGPT_ACCOUNT_ID", "")
CODEX_VERSION = os.getenv("CHATGPT_CODEX_CLIENT_VERSION", "0.144.1")
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_ORIGIN = "https://chatgpt.com"
CODEX_REFERER = "https://chatgpt.com/"
CODEX_USER_AGENT = "9Router/3 Codex-Compatible"

app = FastAPI(title="chatgpt-gateway", version="0.3.0")


def authorize(authorization: str | None, x_api_key: str | None) -> None:
    supplied = x_api_key or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if not GATEWAY_API_KEY or supplied != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def upstream_headers() -> dict[str, str]:
    if not CHATGPT_ACCESS_TOKEN or not CHATGPT_ACCOUNT_ID:
        raise HTTPException(status_code=503, detail="ChatGPT access credentials are not configured.")
    return {
        "Authorization": f"Bearer {CHATGPT_ACCESS_TOKEN}",
        "ChatGPT-Account-Id": CHATGPT_ACCOUNT_ID,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": CODEX_USER_AGENT,
        "originator": CODEX_ORIGINATOR,
        "Version": CODEX_VERSION,
        "Origin": CODEX_ORIGIN,
        "Referer": CODEX_REFERER,
    }


def upstream_request(payload: dict[str, Any]) -> Any:
    try:
        return requests.post(
            CHATGPT_ENDPOINT,
            headers=upstream_headers(),
            json=payload,
            impersonate="chrome120",
            timeout=120,
            stream=True,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"ChatGPT transport failed: {error}") from error


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": bool(GATEWAY_API_KEY and CHATGPT_ACCESS_TOKEN and CHATGPT_ACCOUNT_ID),
        "runtime": "faable-curl-cffi",
        "transport": "curl_cffi",
        "impersonate": "chrome120",
    }


@app.get("/v1/models")
def models(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization, x_api_key)
    created = int(time.time())
    return {"object": "list", "data": [{"id": "chatgpt-gpt-5.6", "object": "model", "created": created, "owned_by": "openai-chatgpt"}]}


@app.get("/v1/debug/upstream")
def debug_upstream(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> JSONResponse:
    authorize(authorization, x_api_key)
    try:
        response = requests.get(
            "https://chatgpt.com/robots.txt",
            headers={"User-Agent": CODEX_USER_AGENT},
            impersonate="chrome120",
            timeout=30,
        )
        return JSONResponse({
            "runtime": "faable-curl-cffi",
            "transport": "curl_cffi",
            "impersonate": "chrome120",
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body_prefix": response.text[:300],
        })
    except Exception as error:
        return JSONResponse({"status": 502, "error": str(error)}, status_code=502)


@app.get("/v1/debug/transport")
def debug_transport(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> JSONResponse:
    authorize(authorization, x_api_key)
    try:
        response = requests.get(
            "https://chatgpt.com/robots.txt",
            headers={"User-Agent": CODEX_USER_AGENT},
            impersonate="chrome120",
            timeout=30,
        )
        return JSONResponse({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "runtime": "faable-curl-cffi",
            "checks": [{
                "variant": "curl-cffi-chrome120",
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "body_prefix": response.text[:300],
            }],
        })
    except Exception as error:
        return JSONResponse({"status": 502, "error": str(error)}, status_code=502)


@app.post("/v1/responses")
def responses(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    authorize(authorization, x_api_key)
    upstream_payload = {**payload, "store": False, "stream": True}
    response = upstream_request(upstream_payload)
    if response.status_code >= 400:
        content_type = response.headers.get("content-type", "")
        message = response.text[:1000] if "text/html" not in content_type.lower() else f"ChatGPT upstream returned an HTML block page (HTTP {response.status_code})."
        raise HTTPException(status_code=response.status_code, detail=message)
    return StreamingResponse(response.iter_content(chunk_size=4096), media_type="text/event-stream")


@app.post("/v1/chat/completions")
def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> Any:
    authorize(authorization, x_api_key)
    messages = payload.get("messages", [])
    input_items = [
        {
            "role": message.get("role", "user"),
            "content": [{"type": "input_text", "text": message.get("content", "")}],
        }
        for message in messages
    ]
    upstream_payload = {
        "model": str(payload.get("model", "gpt-5.4")).removeprefix("chatgpt-"),
        "input": input_items,
        "stream": True,
        "store": False,
    }
    response = upstream_request(upstream_payload)
    if response.status_code >= 400:
        content_type = response.headers.get("content-type", "")
        message = response.text[:1000] if "text/html" not in content_type.lower() else f"ChatGPT upstream returned an HTML block page (HTTP {response.status_code})."
        raise HTTPException(status_code=response.status_code, detail=message)
    return StreamingResponse(response.iter_content(chunk_size=4096), media_type="text/event-stream")
