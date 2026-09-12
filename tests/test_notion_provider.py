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

    def fake_bootstrap(runtime_arg, token_v2):
        assert token_v2 == NOTION_TOKEN_V2
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
    assert accounts[0]["space_id"] == "space-1"
    assert notion_provider.notion_configured(runtime) is True


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
