"""Tests for the NVIDIA NIM provider (admin key, free-model filter, passthrough)."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import nim_provider, provider_routing


@pytest.fixture(autouse=True)
def reset_nim_state():
    provider_routing._memory_settings.clear()
    nim_provider._nim_models_cache = {"ts": 0.0, "models": []}
    original_key = runtime.NIM_API_KEY
    yield
    runtime.NIM_API_KEY = original_key
    provider_routing._memory_settings.clear()
    nim_provider._nim_models_cache = {"ts": 0.0, "models": []}


def _activate_nim() -> None:
    runtime.set_active_provider_model("nim", "meta/llama-3.3-70b-instruct")


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def test_is_free_chat_model_drops_non_chat_models() -> None:
    assert nim_provider.is_free_chat_model("meta/llama-3.3-70b-instruct") is True
    assert nim_provider.is_free_chat_model("nvidia/nv-embedqa-e5-v5") is False
    assert nim_provider.is_free_chat_model("nvidia/nv-rerankqa-mistral-4b-v3") is False
    assert nim_provider.is_free_chat_model("google/deplot") is False
    assert nim_provider.is_free_chat_model("nvidia/nemoretriever-parse") is False


def test_chat_without_key_returns_503(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = ""
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "meta/llama-3.3-70b-instruct", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "NIM_API_KEY" in response.json()["detail"]


def test_chat_completions_passthrough_non_stream(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = "nvapi-test"
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-nim", "object": "chat.completion", "model": "meta/llama-3.3-70b-instruct"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "cmpl-nim"
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer nvapi-test"
    assert captured["json"]["model"] == "meta/llama-3.3-70b-instruct"


def test_nim_strips_zcode_client_envelopes(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = "nvapi-test"
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-nim", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}], "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}, "reasoning_effort": "high", "store": True},
    )

    assert response.status_code == 200
    assert "extra_body" not in captured["json"]
    assert "reasoning_effort" not in captured["json"]
    assert "store" not in captured["json"]


def test_chat_completions_passthrough_stream(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = "nvapi-test"

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
        json={"model": "meta/llama-3.3-70b-instruct", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert body.endswith("data: [DONE]\n\n")


def test_models_list_is_filtered_to_free_chat_models(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = "nvapi-test"

    def fake_get(url, **kwargs):
        response = Mock()
        response.json.return_value = {
            "data": [
                {"id": "meta/llama-3.3-70b-instruct"},
                {"id": "nvidia/nv-embedqa-e5-v5"},
                {"id": "google/deplot"},
                {"id": "deepseek-ai/deepseek-r1"},
                {"id": "nvidia/nv-rerankqa-mistral-4b-v3"},
            ]
        }
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)
    client = TestClient(app)

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [m["id"] for m in data] == ["deepseek-ai/deepseek-r1", "meta/llama-3.3-70b-instruct"]
    assert all(m["owned_by"] == "nvidia-nim" for m in data)


def test_filter_mode_all_keeps_everything(monkeypatch) -> None:
    runtime.NIM_API_KEY = "nvapi-test"
    monkeypatch.setenv("NIM_MODELS_FILTER_MODE", "all")

    def fake_get(url, **kwargs):
        response = Mock()
        response.json.return_value = {
            "data": [{"id": "meta/llama-3.3-70b-instruct"}, {"id": "nvidia/nv-embedqa-e5-v5"}]
        }
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)

    assert nim_provider.nim_list_models(runtime) == [
        "meta/llama-3.3-70b-instruct",
        "nvidia/nv-embedqa-e5-v5",
    ]


def test_save_key_via_admin(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    response = client.post("/auth/nim/key", json={"api_key": "nvapi-saved"})

    assert response.status_code == 200
    assert runtime.NIM_API_KEY == "nvapi-saved"
    assert client.get("/auth/nim/key").json()["configured"] is True


def test_responses_endpoint_unsupported(monkeypatch) -> None:
    _activate_nim()
    runtime.NIM_API_KEY = "nvapi-test"
    client = TestClient(app)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "meta/llama-3.3-70b-instruct", "input": "hi"},
    )

    assert response.status_code == 503
    assert "/v1/chat/completions" in response.json()["detail"]


def test_client_key_can_target_nim(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post(
        "/auth/clients",
        json={"label": "bot", "provider": "nim", "model": "deepseek-ai/deepseek-r1"},
    )
    assert created.status_code == 200
    key = created.json()["key"]
    runtime.NIM_API_KEY = "nvapi-test"

    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-nim", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-ai/deepseek-r1"
