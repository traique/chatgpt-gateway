"""Tests for the TokenRouter provider (admin key, OpenAI passthrough, models)."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import provider_routing, tokenrouter_provider


@pytest.fixture(autouse=True)
def reset_tokenrouter_state():
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    tokenrouter_provider._tokenrouter_models_cache = {"ts": 0.0, "models": []}
    original_key = runtime.TOKENROUTER_API_KEY
    original_base = runtime.TOKENROUTER_BASE_URL
    yield
    runtime.TOKENROUTER_API_KEY = original_key
    runtime.TOKENROUTER_BASE_URL = original_base
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    tokenrouter_provider._tokenrouter_models_cache = {"ts": 0.0, "models": []}


def _activate_tokenrouter(model: str = "auto") -> None:
    runtime.set_active_provider_model("tokenrouter", model)


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def test_chat_without_key_returns_503() -> None:
    _activate_tokenrouter()
    runtime.TOKENROUTER_API_KEY = ""
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "TOKENROUTER_API_KEY" in response.json()["detail"]


def test_chat_completions_passthrough(monkeypatch) -> None:
    _activate_tokenrouter("openai/gpt-5-mini")
    runtime.TOKENROUTER_API_KEY = "tr_test"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-tr", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openai/gpt-5-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "cmpl-tr"
    assert captured["url"] == "https://api.tokenrouter.io/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer tr_test"
    assert captured["json"]["model"] == "openai/gpt-5-mini"


def test_responses_passthrough(monkeypatch) -> None:
    _activate_tokenrouter("openai/gpt-5-mini")
    runtime.TOKENROUTER_API_KEY = "tr_test"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "resp-tr", "object": "response"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openai/gpt-5-mini", "input": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "resp-tr"
    assert captured["url"] == "https://api.tokenrouter.io/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer tr_test"


def test_save_key_via_admin(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.post("/auth/tokenrouter/key", json={"api_key": "tr_saved"})

    assert response.status_code == 200
    assert runtime.TOKENROUTER_API_KEY == "tr_saved"
    status = client.get("/auth/tokenrouter/key").json()
    assert status["configured"] is True
    assert status["base_url"] == "https://api.tokenrouter.io/v1"


def test_v1_models_uses_dynamic_catalog(monkeypatch) -> None:
    _activate_tokenrouter()
    runtime.TOKENROUTER_API_KEY = "tr_test"

    def fake_get(url, **kwargs):
        assert url == "https://api.tokenrouter.io/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer tr_test"
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": [{"id": "z/model"}, {"id": "a/model"}]}
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)
    client = TestClient(app)
    response = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [m["id"] for m in data] == ["a/model", "z/model"]
    assert all(m["owned_by"] == "tokenrouter" for m in data)


def test_client_key_can_target_tokenrouter(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post(
        "/auth/clients",
        json={"label": "bot", "provider": "tokenrouter", "model": "openai/gpt-5-mini"},
    )
    assert created.status_code == 200
    key = created.json()["key"]
    runtime.TOKENROUTER_API_KEY = "tr_test"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-tr", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://api.tokenrouter.io/v1/chat/completions"
    assert captured["json"]["model"] == "openai/gpt-5-mini"


def test_anthropic_messages_native_passthrough(monkeypatch) -> None:
    _activate_tokenrouter("anthropic/claude-sonnet-4-5")
    runtime.TOKENROUTER_API_KEY = "tr_test"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "msg_tr",
            "type": "message",
            "role": "assistant",
            "model": "anthropic/claude-sonnet-4-5",
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)
    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key", "anthropic-version": "2023-06-01"},
        json={
            "model": "anthropic/claude-sonnet-4-5",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == "msg_tr"
    assert captured["url"] == "https://api.tokenrouter.io/v1/messages"
    assert captured["headers"]["Authorization"] == "Bearer tr_test"
    assert captured["json"]["model"] == "anthropic/claude-sonnet-4-5"
