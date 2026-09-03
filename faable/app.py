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


def authorize(authorization: str | None, x_api_key: str | None) -> None:
    supplied = normalize_gateway_api_key(x_api_key) if x_api_key else ""
    if not supplied and authorization:
        normalized_authorization = authorization.strip()
        scheme, separator, token = normalized_authorization.partition(" ")
        supplied = normalize_gateway_api_key(token) if separator and scheme.lower() == "bearer" else normalized_authorization

    if not GATEWAY_API_KEY or not hmac.compare_digest(supplied, GATEWAY_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key.")
