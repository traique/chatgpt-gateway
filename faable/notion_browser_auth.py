"""Local browser-assisted Notion login.

This helper launches an isolated Chrome/Edge profile on the same machine that
runs the gateway, waits for the user to finish a normal Notion sign-in, then
reads the small set of Notion session cookies needed by the private web API through
the local Chrome DevTools Protocol. It never receives or stores the user's Notion
password.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from websocket import create_connection

NOTION_LOGIN_URL = "https://www.notion.com/login"
NOTION_APP_URL = "https://app.notion.com/"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 300


def find_browser_executable() -> str | None:
    configured = str(os.getenv("CHROME_PATH") or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return str(candidate)

    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
        "chrome.exe",
        "msedge.exe",
    ):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    conventional = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]
    for root_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.getenv(root_name)
        if not root:
            continue
        conventional.extend(
            [
                Path(root) / "Google/Chrome/Application/chrome.exe",
                Path(root) / "Microsoft/Edge/Application/msedge.exe",
            ]
        )
    for candidate in conventional:
        if candidate.exists():
            return str(candidate)
    return None


def browser_login_capability() -> tuple[bool, str]:
    browser = find_browser_executable()
    if not browser:
        return False, "Không tìm thấy Chrome/Edge trên máy đang chạy gateway."
    if sys.platform.startswith("linux") and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
        return False, "Máy chạy gateway không có desktop/display để mở cửa sổ Chrome/Edge."
    if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
        return False, "Browser-assisted login không chạy với quyền root; hãy chạy gateway bằng user thường."
    return True, browser


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_from_url(url: str, timeout: float = 2.0) -> Any:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback-only URL
        return json.loads(response.read().decode("utf-8", errors="replace"))


class _CDP:
    def __init__(self, websocket_url: str) -> None:
        self._ws = create_connection(websocket_url, timeout=5, suppress_origin=True)
        self._next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(self._ws.recv())
            if payload.get("id") != message_id:
                continue
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            result = payload.get("result")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def _browser_websocket_url(port: int, timeout_seconds: float = 15.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = _json_from_url(f"http://127.0.0.1:{port}/json/version")
            websocket_url = payload.get("webSocketDebuggerUrl") if isinstance(payload, dict) else None
            if isinstance(websocket_url, str) and websocket_url:
                return websocket_url
        except Exception as error:
            last_error = error
        time.sleep(0.25)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"Chrome DevTools không khởi động được{detail}")


_SESSION_COOKIE_NAMES = (
    "notion_browser_id",
    "device_id",
    "notion_user_id",
    "notion_users",
    "notion_check_cookie_consent",
    "notion_locale",
    "token_v2",
)


def _notion_domain_rank(domain: str) -> int:
    domain = domain.lower().lstrip(".")
    if domain.endswith("notion.com"):
        return 20 + (2 if domain.startswith("app.") else 1)
    if domain.endswith("notion.so"):
        return 10
    return 0


def _read_notion_session(websocket_url: str) -> dict[str, str]:
    """Read only the Notion cookies used by the private web API plus browser UA."""
    client = _CDP(websocket_url)
    try:
        result = client.call("Storage.getCookies")
        cookies = result.get("cookies") or []
        chosen: dict[str, tuple[int, float, str]] = {}
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "")
            if name not in _SESSION_COOKIE_NAMES:
                continue
            domain = str(cookie.get("domain") or "")
            rank = _notion_domain_rank(domain)
            value = str(cookie.get("value") or "").strip()
            if not rank or not value:
                continue
            try:
                expires = float(cookie.get("expires") or 0)
            except (TypeError, ValueError):
                expires = 0.0
            previous = chosen.get(name)
            if previous is None or (rank, expires) > (previous[0], previous[1]):
                chosen[name] = (rank, expires, value)
        session = {name: chosen[name][2] for name in _SESSION_COOKIE_NAMES if name in chosen}
        try:
            version = client.call("Browser.getVersion")
            user_agent = str(version.get("userAgent") or "").strip()
            if user_agent:
                session["user_agent"] = user_agent
        except Exception:
            pass
        return session
    finally:
        client.close()


def _session_cookie_header(session: dict[str, str]) -> str:
    return "; ".join(
        f"{name}={session[name]}"
        for name in _SESSION_COOKIE_NAMES
        if session.get(name)
    )


def capture_notion_session(timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS) -> dict[str, str]:
    """Open a temporary browser and return the minimal authenticated Notion session."""
    capable, browser_or_reason = browser_login_capability()
    if not capable:
        raise RuntimeError(browser_or_reason)

    browser = browser_or_reason
    port = _free_loopback_port()
    profile_dir = Path(tempfile.mkdtemp(prefix="gateway-notion-login-"))
    args = [
        browser,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        NOTION_LOGIN_URL,
    ]
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        websocket_url = _browser_websocket_url(port)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Cửa sổ đăng nhập Notion đã bị đóng trước khi đăng nhập hoàn tất.")
            session = _read_notion_session(websocket_url)
            if session.get("token_v2"):
                session["cookie"] = _session_cookie_header(session)
                return session
            time.sleep(2)
        raise TimeoutError("Hết thời gian chờ đăng nhập Notion.")
    finally:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)


def capture_token_v2(timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS) -> str:
    """Backward-compatible helper that returns only token_v2."""
    return capture_notion_session(timeout_seconds=timeout_seconds)["token_v2"]
