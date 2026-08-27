from typing import Final

from curl_cffi import requests as curl_requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

UPSTREAM_URL: Final[str] = "https://chatgpt.com/robots.txt"
UPSTREAM_TIMEOUT_SECONDS: Final[float] = 15.0

app = FastAPI(title="ChatGPT Gateway", version="0.4.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home() -> dict[str, str]:
    return {"status": "ok", "message": "ChatGPT Gateway"}


@app.get("/auth")
def auth() -> dict[str, str]:
    return {"status": "ok", "message": "Admin authentication endpoint"}


@app.get("/dashboard")
def dashboard() -> dict[str, str]:
    return {"status": "ok", "message": "Dashboard"}


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "runtime": "faable", "transport": "curl_cffi"}


@app.get("/v1/debug/transport")
def debug_transport() -> dict[str, object]:
    response = curl_requests.get(
        UPSTREAM_URL,
        impersonate="chrome120",
        timeout=UPSTREAM_TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    return {
        "ok": response.ok,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "server": response.headers.get("server"),
        "body_prefix": response.text[:300],
    }
