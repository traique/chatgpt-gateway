"""Tests for the Notion AI provider (token_v2 login, NDJSON parsing, chat routing)."""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import notion_provider, provider_routing

NOTION_TOKEN_V2 = "tok123"


@pytest.fixture(autouse=True)
def reset_notion_state():
    provider_routing._memory_settings.clear()
    notion_provider._memory_notion_accounts.clear()
    notion_provider._memory_notion_browser_logins.clear()
    notion_provider._notion_models_cache = {"ts": 0.0, "alias_map": {}, "models": []}
    original = dict(runtime.__dict__)
    yield
    notion_provider._memory_notion_accounts.clear()
    notion_provider._memory_notion_browser_logins.clear()
    notion_provider._notion_models_cache = {"ts": 0.0, "alias_map": {}, "models": []}
    provider_routing._memory_settings.clear()
    for key, value in original.items():
        runtime.__dict__[key] = value


def _bootstrap_payload() -> dict:
    return {
        "recordMap": {
            "notion_user": {
                "user-1": {"value": {"value": {"name": [["Gia"]], "email": "g@example.com"}}}
            },
            "space": {"space-1": {"value": {"id": "space-1", "name": "Workspace"}}},
            "space_view": {"view-1": {"value": {"id": "view-1", "space_id": "space-1"}}},
        }
    }


def _notion_stream_lines() -> list[bytes]:
    return [
        json.dumps({"type": "patch-start", "data": {"s": [{"type": "agent-inference", "value": []}]}}).encode(),
        json.dumps({"type": "patch", "v": [{"o": "a", "p": "/s/0/value/-", "v": {"type": "text", "content": "Xin"}}]}).encode(),
        json.dumps({"type": "patch", "v": [{"o": "x", "p": "/s/0/value/0/content", "v": " chào bạn"}]}).encode(),
        json.dumps({"type": "patch", "v": [{"o": "a", "p": "/s/0/value/0/inputTokens", "v": 5}]}).encode(),
        json.dumps({"type": "patch", "v": [{"o": "a", "p": "/s/0/value/0/outputTokens", "v": 7}]}).encode(),
    ]


def _signin_notion(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)

    def fake_bootstrap(runtime_arg, token_v2, **kwargs):
        assert token_v2 == NOTION_TOKEN_V2
        assert kwargs.get("user_id", "") == ""
        assert kwargs.get("notion_users", "") == ""
        return {
            "token_v2": NOTION_TOKEN_V2,
            "full_cookie": f"token_v2={token_v2}",
            "user_id": "user-1",
            "user_name": "Gia",
            "user_email": "g@example.com",
            "space_id": "space-1",
            "space_name": "Workspace",
            "space_view_id": "view-1",
            "browser_id": "browser-1",
            "device_id": "device-1",
        }

    monkeypatch.setattr(notion_provider, "bootstrap_notion_account", fake_bootstrap)
    client = TestClient(app)
    response = client.post("/auth/notion/login", json={"token_v2": NOTION_TOKEN_V2})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    return client


def _activate_notion() -> None:
    runtime.set_active_provider_model("notion", "notion-ai")

def test_login_requires_token_v2(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    response = client.post("/auth/notion/login", json={})

    assert response.status_code == 400
    assert "token_v2" in response.json()["detail"]

def test_login_rejects_full_cookie_string(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    response = client.post(
        "/auth/notion/login",
        json={"token_v2": "token_v2=tok123; notion_user_id=user-1"},
    )

    assert response.status_code == 400
    assert "only the token_v2 value" in response.json()["detail"]

def test_manual_login_forwards_notion_identity_cookies(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    captured: dict[str, str] = {}

    def fake_bootstrap(runtime_arg, token_v2, **kwargs):
        captured["token_v2"] = token_v2
        captured["user_id"] = kwargs.get("user_id", "")
        captured["notion_users"] = kwargs.get("notion_users", "")
        return {
            "token_v2": token_v2,
            "user_id": captured["user_id"],
            "notion_users": captured["notion_users"],
            "user_name": "Gia",
            "user_email": "g@example.com",
            "space_id": "space-1",
            "space_name": "Workspace",
            "space_view_id": "view-1",
            "browser_id": "browser-1",
            "device_id": "device-1",
        }

    monkeypatch.setattr(notion_provider, "bootstrap_notion_account", fake_bootstrap)
    client = TestClient(app)
    response = client.post(
        "/auth/notion/login",
        json={
            "token_v2": "token_v2=tok123",
            "notion_user_id": "notion_user_id=user-1",
            "notion_users": "notion_users=[%22user-1%22]",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "token_v2": "tok123",
        "user_id": "user-1",
        "notion_users": "[%22user-1%22]",
    }
    active = notion_provider.get_active_notion_account(runtime)
    assert active["user_id"] == "user-1"
    assert active["notion_users"] == "[%22user-1%22]"
    assert "notion_user_id=user-1" in active["full_cookie"]
    assert "notion_users=[%22user-1%22]" in active["full_cookie"]

def test_manual_login_rejects_full_cookie_in_identity_fields(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    response = client.post(
        "/auth/notion/login",
        json={
            "token_v2": NOTION_TOKEN_V2,
            "notion_user_id": "user-1; notion_users=[%22user-1%22]",
        },
    )

    assert response.status_code == 400
    assert "only the notion_user_id value" in response.json()["detail"]

def test_obsolete_bookmarklet_routes_are_removed(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    assert client.post("/auth/notion/start").status_code == 404
    assert client.get("/auth/notion/capture?t=anything").status_code == 404

def test_browser_login_routes(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    monkeypatch.setattr(
        notion_provider,
        "start_notion_browser_login",
        lambda runtime_arg, label: {
            "id": "login-1", "status": "pending", "expires_at": 1234567890000
        },
    )
    monkeypatch.setattr(
        notion_provider,
        "poll_notion_browser_login",
        lambda runtime_arg, login_id: {
            "id": login_id, "status": "completed", "error": "",
            "account_id": "acc-1", "expires_at": 1234567890000,
        },
    )
    client = TestClient(app)

    started = client.post("/auth/notion/browser/start", json={})
    assert started.status_code == 200
    assert started.json()["login_id"] == "login-1"
    assert started.json()["interval_seconds"] == 2

    polled = client.post("/auth/notion/browser/poll", json={"login_id": "login-1"})
    assert polled.status_code == 200
    assert polled.json()["status"] == "completed"
    assert polled.json()["account_id"] == "acc-1"

def test_browser_login_poll_requires_id(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)
    response = client.post("/auth/notion/browser/poll", json={})
    assert response.status_code == 400
    assert "login_id" in response.json()["detail"]

def test_notion_login_and_accounts(monkeypatch) -> None:
    client = _signin_notion(monkeypatch)

    accounts = client.get("/auth/notion/accounts").json()["data"]
    assert len(accounts) == 1
    assert accounts[0]["status"] == "active"
    assert accounts[0]["health"] == "healthy"
    assert accounts[0]["space_id"] == "space-1"
    assert notion_provider.notion_configured(runtime) is True


def test_notion_account_health_disable_enable_and_delete(monkeypatch) -> None:
    client = _signin_notion(monkeypatch)
    account_id = client.get("/auth/notion/accounts").json()["data"][0]["id"]

    def fake_post(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"models": []}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    health = client.post(f"/auth/notion/accounts/{account_id}/health")
    assert health.status_code == 200
    assert health.json()["health"]["status"] == "ok"

    disabled = client.post(f"/auth/notion/accounts/{account_id}", json={"status": "disabled"})
    assert disabled.status_code == 200
    assert disabled.json()["data"][0]["health"] == "disabled"

    enabled = client.post(f"/auth/notion/accounts/{account_id}", json={"status": "active"})
    assert enabled.status_code == 200
    assert enabled.json()["data"][0]["health"] == "healthy"

    assert client.delete(f"/auth/notion/accounts/{account_id}").status_code == 409
    client.post(f"/auth/notion/accounts/{account_id}", json={"status": "disabled"})
    deleted = client.delete(f"/auth/notion/accounts/{account_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"] == []


def test_notion_failed_health_is_visible_and_deletable(monkeypatch) -> None:
    client = _signin_notion(monkeypatch)
    account_id = client.get("/auth/notion/accounts").json()["data"][0]["id"]

    def fake_post(url, **kwargs):
        response = Mock()
        response.status_code = 401
        response.json.return_value = {}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    checked = client.post(f"/auth/notion/accounts/{account_id}/health")
    assert checked.status_code == 200
    assert checked.json()["health"]["status"] == "error"
    row = checked.json()["data"][0]
    assert row["health"] == "error"
    assert "HTTP 401" in row["last_error"]

    deleted = client.delete(f"/auth/notion/accounts/{account_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"] == []

def test_notion_chat_completions_non_stream(monkeypatch) -> None:
    _signin_notion(monkeypatch)
    _activate_notion()
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter(_notion_stream_lines())
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "notion-ai", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Xin chào bạn"
    assert body["usage"]["prompt_tokens"] == 5
    assert body["usage"]["completion_tokens"] == 7
    assert captured["url"] == "https://app.notion.com/api/v3/runInferenceTranscript"
    assert captured["headers"]["x-notion-space-id"] == "space-1"
    assert captured["json"]["spaceId"] == "space-1"
    assert captured["json"]["createThread"] is True
    config = captured["json"]["transcript"][0]
    assert config["type"] == "config"
    assert config["value"]["model"] == "ambrosia-tart-high"
    user_entry = captured["json"]["transcript"][2]
    assert user_entry["type"] == "user"
    assert user_entry["value"] == [["hi"]]

def test_notion_route_forwards_resolved_model(monkeypatch) -> None:
    _signin_notion(monkeypatch)
    _activate_notion()
    captured: dict = {}

    monkeypatch.setattr(runtime, "resolve_provider_model", lambda provider, requested: "opus-4.8")

    def fake_notion_request(payload):
        captured.update(payload)
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter(_notion_stream_lines())
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime, "notion_request", fake_notion_request)
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "unknown-client-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["model"] == "opus-4.8"

def test_notion_chat_completions_stream_sse(monkeypatch) -> None:
    _signin_notion(monkeypatch)
    _activate_notion()

    def fake_post(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter(_notion_stream_lines())
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "notion-ai", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert body.endswith("data: [DONE]\n\n")
    deltas = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ") and "[DONE]" not in line]
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "")
        for chunk in deltas
        if chunk.get("object") == "chat.completion.chunk"
    )
    assert text == "Xin chào bạn"
    finish = [chunk for chunk in deltas if chunk["choices"][0]["finish_reason"] == "stop"]
    assert finish and finish[0]["usage"]["total_tokens"] == 12

def test_notion_chat_without_account_returns_503(monkeypatch) -> None:
    _activate_notion()
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "notion-ai", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "Notion" in response.json()["detail"]

def test_notion_error_event_maps_to_http_error(monkeypatch) -> None:
    _signin_notion(monkeypatch)
    _activate_notion()

    def fake_post(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter([json.dumps({"type": "error", "message": "boom"}).encode()])
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "notion-ai", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 502
    assert "boom" in response.json()["detail"]

def test_notion_responses_endpoint_unsupported(monkeypatch) -> None:
    _signin_notion(monkeypatch)
    _activate_notion()
    client = TestClient(app)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "notion-ai", "input": "hi"},
    )

    assert response.status_code == 503
    assert "/v1/chat/completions" in response.json()["detail"]

def test_notion_model_aliases_resolve() -> None:
    assert notion_provider.resolve_notion_model("opus-4.8") == "ambrosia-tart-high"
    assert notion_provider.resolve_notion_model("") == notion_provider.DEFAULT_NOTION_MODEL
    assert notion_provider.resolve_notion_model("fireworks-kimi-k2.6") == "fireworks-kimi-k2.6"

def test_parse_available_models_builds_alias_map_and_catalog() -> None:
    payload = {
        "models": [
            {"model": "ambrosia-tart-high", "modelMessage": "Opus 4.8"},
            {"model": "angel-cake-high", "modelMessage": "Sonnet 5"},
            {"model": "dead-model", "modelMessage": "Old Model", "isDisabled": True},
        ]
    }

    alias_map, catalog = notion_provider.parse_available_models(payload)

    assert alias_map["opus-4.8"] == "ambrosia-tart-high"
    assert alias_map["sonnet-5"] == "angel-cake-high"
    assert "Old Model" not in catalog
    assert catalog == ["Opus 4.8", "Sonnet 5"]

def test_notion_list_models_uses_get_available_models(monkeypatch) -> None:
    notion_provider._memory_notion_accounts["acc-1"] = {
        "id": "acc-1", "label": "Test", "cookie_enc": NOTION_TOKEN_V2,
        "user_id": "user-1", "space_id": "space-1", "space_name": "WS",
        "status": "active", "created_at": 1, "updated_at": 1,
    }
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"models": [{"model": "orchid-muffin", "modelMessage": "GPT-5.6 Terra"}]}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    monkeypatch.setattr(runtime, "DATABASE_URL", "", raising=False)

    models = notion_provider.notion_list_models(runtime)

    assert models == ["GPT-5.6 Terra"]
    assert captured["url"] == "https://app.notion.com/api/v3/getAvailableModels"
    assert captured["json"] == {"spaceId": "space-1"}
    assert notion_provider.resolve_notion_model("gpt-5.6-terra") == "orchid-muffin"

def test_build_cookie_header_preserves_exact_notion_users_value() -> None:
    header = notion_provider.build_cookie_header({
        "token_v2": NOTION_TOKEN_V2,
        "user_id": "user-1",
        "notion_users": "%5B%22user-1%22%2C%22user-2%22%5D",
        "browser_id": "browser-1",
        "device_id": "device-1",
    })

    assert "notion_user_id=user-1" in header
    assert "notion_users=%5B%22user-1%22%2C%22user-2%22%5D" in header
    assert "token_v2=tok123" in header

def test_bootstrap_manual_identity_fields_are_sent_on_first_request(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = _bootstrap_payload()
        response.text = ""
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    account = notion_provider.bootstrap_notion_account(
        runtime,
        NOTION_TOKEN_V2,
        user_id="user-1",
        notion_users="%5B%22user-1%22%5D",
        browser_id="browser-1",
        device_id="device-1",
    )

    assert account["user_id"] == "user-1"
    assert account["notion_users"] == "%5B%22user-1%22%5D"
    assert captured["url"] == "https://app.notion.com/api/v3/loadUserContent"
    assert captured["headers"]["x-notion-active-user-header"] == "user-1"
    assert "notion_user_id=user-1" in captured["headers"]["cookie"]
    assert "notion_users=%5B%22user-1%22%5D" in captured["headers"]["cookie"]

def test_bootstrap_401_falls_back_to_www_and_uses_browser_session(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        response = Mock()
        if url.startswith("https://app.notion.com"):
            response.status_code = 401
            response.text = "unauthorized"
            return response
        response.status_code = 200
        response.json.return_value = _bootstrap_payload()
        response.text = ""
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    account = notion_provider.bootstrap_notion_account(
        runtime,
        NOTION_TOKEN_V2,
        session_cookie=(
            "notion_browser_id=browser-real; device_id=device-real; "
            "notion_user_id=user-1; notion_users=[%22user-1%22]; token_v2=tok123"
        ),
        user_id="user-1",
        browser_id="browser-real",
        device_id="device-real",
    )

    assert account["user_id"] == "user-1"
    assert account["space_id"] == "space-1"
    assert [url for url, _ in calls] == [
        "https://app.notion.com/api/v3/loadUserContent",
        "https://www.notion.so/api/v3/loadUserContent",
    ]
    first_headers = calls[0][1]["headers"]
    assert "token_v2=tok123" in first_headers["cookie"]
    assert "notion_browser_id=browser-real" in first_headers["cookie"]
    assert first_headers["x-notion-active-user-header"] == "user-1"

def test_bootstrap_401_message_does_not_claim_token_is_expired(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        response = Mock()
        response.status_code = 401
        response.text = "unauthorized"
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    with pytest.raises(Exception) as error:
        notion_provider.bootstrap_notion_account(runtime, NOTION_TOKEN_V2)

    detail = getattr(error.value, "detail", str(error.value))
    assert "does not always mean token_v2 expired" in detail
    assert "Browser Login" in detail
    assert "notion_user_id" in detail
    assert "notion_users" in detail

def test_save_manual_notion_account_persists_stable_minimal_session() -> None:
    account = {
        "token_v2": NOTION_TOKEN_V2,
        "full_cookie": "",
        "user_id": "user-1",
        "space_id": "space-1",
        "space_name": "Workspace",
        "browser_id": "browser-1",
        "device_id": "device-1",
    }

    notion_provider.save_notion_account(runtime, "Notion", account)
    active = notion_provider.get_active_notion_account(runtime)

    assert active["token_v2"] == NOTION_TOKEN_V2
    assert "notion_browser_id=browser-1" in active["full_cookie"]
    assert "device_id=device-1" in active["full_cookie"]
    assert "notion_user_id=user-1" in active["full_cookie"]


def test_save_notion_account_preserves_browser_user_agent() -> None:
    account = {
        "token_v2": NOTION_TOKEN_V2,
        "full_cookie": "token_v2=tok123; notion_user_id=user-1",
        "user_id": "user-1",
        "space_id": "space-1",
        "space_name": "Workspace",
        "user_agent": "Mozilla/5.0 Chrome/133.0.0.0 Safari/537.36",
    }

    notion_provider.save_notion_account(runtime, "Notion", account)
    active = notion_provider.get_active_notion_account(runtime)

    assert active["user_agent"] == account["user_agent"]
