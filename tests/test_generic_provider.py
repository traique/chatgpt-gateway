"""Tests for the vendor-neutral OpenAI-compatible provider."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import provider_routing


@pytest.fixture(autouse=True)
def reset_generic_state():
    provider_routing._memory_settings.clear()
    original = (
        runtime.GENERIC_BASE_URL,
        runtime.GENERIC_API_KEY,
        runtime.GENERIC_MODEL,
    )
    runtime.GENERIC_BASE_URL = ""
    runtime.GENERIC_API_KEY = ""
    runtime.GENERIC_MODEL = ""
    yield
    runtime.GENERIC_BASE_URL, runtime.GENERIC_API_KEY, runtime.GENERIC_MODEL = original
    provider_routing._memory_settings.clear()


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def _configure() -> None:
    runtime.GENERIC_BASE_URL = "https://compatible.example/v1"
    runtime.GENERIC_API_KEY = "sk-generic"
    runtime.GENERIC_MODEL = "vendor/model-1"
    runtime.set_active_provider_model("generic", "")


def test_admin_can_save_generic_config(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    response = client.post(
        "/auth/generic/config",
        json={
            "base_url": "https://compatible.example/v1/",
            "api_key": "sk-saved",
            "model": "vendor/model-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "configured": True,
        "base_url": "https://compatible.example/v1",
        "model": "vendor/model-1",
    }
    assert runtime.GENERIC_API_KEY == "sk-saved"
    assert client.get("/auth/generic/config").json() == {
        "configured": True,
        "base_url": "https://compatible.example/v1",
        "model": "vendor/model-1",
    }


def test_admin_rejects_invalid_base_url(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    response = client.post(
        "/auth/generic/config",
        json={"base_url": "compatible.example/v1", "api_key": "sk-test", "model": "model-1"},
    )

    assert response.status_code == 400
    assert "absolute http(s) URL" in response.json()["detail"]


def test_chat_completions_passthrough_uses_configured_model(monkeypatch) -> None:
    _configure()
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-generic", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={
            "model": "glm-5.3-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "extra_body": {"provider": "should-be-removed"},
        },
    )

    assert response.status_code == 200
    assert captured["url"] == "https://compatible.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-generic"
    assert captured["json"]["model"] == "vendor/model-1"
    assert "extra_body" not in captured["json"]


def test_chat_completions_stream_passthrough(monkeypatch) -> None:
    _configure()

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
    with TestClient(app).stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert body.endswith("data: [DONE]\n\n")


def test_responses_passthrough(monkeypatch) -> None:
    _configure()
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "resp-generic", "object": "response"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = TestClient(app).post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "some-client-default", "input": "hi"},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://compatible.example/v1/responses"
    assert captured["json"]["model"] == "vendor/model-1"


def test_models_returns_configured_generic_model() -> None:
    _configure()

    response = TestClient(app).get(
        "/v1/models",
        headers={"Authorization": "Bearer test-gateway-key"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": "vendor/model-1",
            "object": "model",
            "created": response.json()["data"][0]["created"],
            "owned_by": "openai-compatible",
        }
    ]


def test_client_key_can_route_to_generic_without_changing_global(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    runtime.GENERIC_BASE_URL = "https://compatible.example/v1"
    runtime.GENERIC_API_KEY = "sk-generic"
    runtime.GENERIC_MODEL = "vendor/model-1"
    key = client.post(
        "/auth/clients",
        json={"label": "generic-client", "provider": "generic", "model": "vendor/model-client"},
    ).json()["key"]
    assert runtime.get_active_provider() == "chatgpt"
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-client", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "hardcoded-client-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://compatible.example/v1/chat/completions"
    assert captured["json"]["model"] == "vendor/model-client"
    assert runtime.get_active_provider() == "chatgpt"


def test_anthropic_messages_bridge_to_generic_chat(monkeypatch) -> None:
    _configure()
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "cmpl-generic",
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = TestClient(app).post(
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key"},
        json={"model": "claude-default", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["content"] == [{"type": "text", "text": "hello"}]
    assert captured["url"] == "https://compatible.example/v1/chat/completions"
    assert captured["json"]["model"] == "vendor/model-1"


def test_missing_generic_config_returns_clear_503() -> None:
    runtime.set_active_provider_model("generic", "")

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "base_url, api_key, and model" in response.json()["detail"]
