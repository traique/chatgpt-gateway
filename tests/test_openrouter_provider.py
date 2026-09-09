"""Tests for the OpenRouter provider (admin key, passthrough, models)."""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import openrouter_provider, provider_routing


@pytest.fixture(autouse=True)
def reset_openrouter_state():
    provider_routing._memory_settings.clear()
    openrouter_provider._openrouter_models_cache = {"ts": 0.0, "models": []}
    original_key = runtime.OPENROUTER_API_KEY
    yield
    runtime.OPENROUTER_API_KEY = original_key
    provider_routing._memory_settings.clear()
    openrouter_provider._openrouter_models_cache = {"ts": 0.0, "models": []}


def _activate_openrouter() -> None:
    runtime.set_active_provider_model("openrouter", "openrouter/auto")


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def test_chat_without_key_returns_503(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = ""
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openrouter/auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_chat_completions_passthrough_non_stream(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-or", "object": "chat.completion", "model": "openrouter/auto"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openai/gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "cmpl-or"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-v1-test"
    assert captured["json"]["model"] == "openai/gpt-5.6"


def test_chat_completions_passthrough_stream(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"

    def fake_post(url, **kwargs):
        assert kwargs["stream"] is True
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openrouter/auto", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert body.endswith("data: [DONE]\n\n")


def test_responses_endpoint_unsupported(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"
    client = TestClient(app)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "openrouter/auto", "input": "hi"},
    )

    assert response.status_code == 503
    assert "/v1/chat/completions" in response.json()["detail"]


def test_save_key_via_admin(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    response = client.post("/auth/openrouter/key", json={"api_key": "sk-or-v1-saved"})

    assert response.status_code == 200
    assert runtime.OPENROUTER_API_KEY == "sk-or-v1-saved"
    assert client.get("/auth/openrouter/key").json() == {"configured": True}


def test_v1_models_filters_to_free_models(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"

    def fake_get(url, **kwargs):
        response = Mock()
        response.json.return_value = {
            "data": [
                {"id": "x-ai/grok-4.5"},
                {"id": "deepseek/deepseek-chat-v4:free"},
                {"id": "openai/gpt-5.6"},
            ]
        }
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)
    client = TestClient(app)

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [m["id"] for m in data] == ["deepseek/deepseek-chat-v4:free"]
    assert all(m["owned_by"] == "openrouter" for m in data)


def test_models_filter_mode_all_keeps_everything(monkeypatch) -> None:
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"
    monkeypatch.setenv("OPENROUTER_MODELS_FILTER_MODE", "all")

    def fake_get(url, **kwargs):
        response = Mock()
        response.json.return_value = {
            "data": [{"id": "x-ai/grok-4.5"}, {"id": "deepseek/deepseek-chat-v4:free"}]
        }
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)

    assert openrouter_provider.openrouter_list_models(runtime) == [
        "deepseek/deepseek-chat-v4:free",
        "x-ai/grok-4.5",
    ]


def test_providers_endpoint_lists_all_providers(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    response = client.get("/auth/providers")

    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["providers"]]
    assert ids == ["chatgpt", "bai", "openrouter", "notion", "nim"]


def test_client_key_can_target_openrouter(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post(
        "/auth/clients",
        json={"label": "bot", "provider": "openrouter", "model": "openai/gpt-5.6"},
    )
    assert created.status_code == 200
    key = created.json()["key"]
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"

    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-or", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["json"]["model"] == "openai/gpt-5.6"


def test_client_key_can_target_notion(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post(
        "/auth/clients",
        json={"label": "bot", "provider": "notion", "model": "notion-ai"},
    )
    assert created.status_code == 200
    entry = next(item for item in client.get("/auth/clients").json()["data"] if item["id"] == created.json()["id"])
    assert entry["provider"] == "notion"


def test_anthropic_messages_bridge_non_stream(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "cmpl-or",
            "choices": [{"message": {"role": "assistant", "content": "Chao ban"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key"},
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 64,
            "system": "Be nice.",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["content"] == [{"type": "text", "text": "Chao ban"}]
    assert body["usage"] == {"input_tokens": 3, "output_tokens": 4}
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "Be nice."}
    assert captured["json"]["messages"][1]["content"] == "hi"


def test_anthropic_messages_bridge_stream(monkeypatch) -> None:
    _activate_openrouter()
    runtime.OPENROUTER_API_KEY = "sk-or-v1-test"

    def fake_post(url, **kwargs):
        assert kwargs["stream"] is True
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter([
            b'data: {"choices":[{"delta":{"content":"xin"}}]}',
            b'',
            b'data: {"choices":[{"delta":{"content":" chao"}}]}',
            b'',
            b"data: [DONE]",
            b"",
        ])
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert "event: message_start" in body
    assert "event: content_block_delta" in body
    assert "xin" in body
    assert "chao" in body
    assert "event: message_stop" in body
