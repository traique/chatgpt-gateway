"""Dynamic OpenAI-compatible provider registry tests."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import generic_provider, provider_routing


@pytest.fixture(autouse=True)
def reset_dynamic_provider_state():
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    generic_provider._memory_dynamic_providers.clear()
    yield
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    generic_provider._memory_dynamic_providers.clear()


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def _create_provider(client: TestClient, *, name: str = "Peach AI") -> dict:
    response = client.post(
        "/auth/custom-providers",
        json={
            "name": name,
            "base_url": "https://peach.example/v1/",
            "api_key": "sk-peach",
            "model": "peach/model-1",
        },
    )
    assert response.status_code == 200
    return response.json()["provider"]


def test_admin_can_create_edit_and_list_dynamic_provider(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)

    assert created["id"].startswith("custom-")
    assert created["base_url"] == "https://peach.example/v1"
    assert created["model"] == "peach/model-1"
    assert created["configured"] is True

    providers = client.get("/auth/providers").json()["providers"]
    dynamic = next(item for item in providers if item["id"] == created["id"])
    assert dynamic["label"] == "Peach AI"
    assert dynamic["kind"] == "custom"
    assert dynamic["editable"] is True

    updated = client.post(
        f"/auth/custom-providers/{created['id']}",
        json={
            "name": "Peach AI Pro",
            "base_url": "https://new-peach.example/v1",
            "api_key": "",  # keep the encrypted key already stored
            "model": "peach/model-2",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["provider"]["name"] == "Peach AI Pro"
    assert runtime.get_dynamic_provider(created["id"])["api_key"] == "sk-peach"


def test_dynamic_provider_routes_chat_responses_and_models(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    client.post("/auth/providers/select", json={"provider": created["id"]})
    captured: list[tuple[str, dict]] = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs))
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "ok", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    chat = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "hardcoded-wrong", "messages": [{"role": "user", "content": "hi"}], "extra_body": {"x": 1}},
    )
    assert chat.status_code == 200
    assert captured[-1][0] == "https://peach.example/v1/chat/completions"
    assert captured[-1][1]["headers"]["Authorization"] == "Bearer sk-peach"
    assert captured[-1][1]["json"]["model"] == "peach/model-1"
    assert "extra_body" not in captured[-1][1]["json"]

    responses = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "client-default", "input": "hi"},
    )
    assert responses.status_code == 200
    assert captured[-1][0] == "https://peach.example/v1/responses"
    assert captured[-1][1]["json"]["model"] == "peach/model-1"

    models = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "peach/model-1"
    assert models.json()["data"][0]["owned_by"] == created["id"]


def test_dynamic_provider_supports_anthropic_bridge(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    client.post("/auth/providers/select", json={"provider": created["id"]})
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "cmpl-custom",
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }
        response.close = lambda: None
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key"},
        json={"model": "claude-default", "max_tokens": 32, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["content"] == [{"type": "text", "text": "hello"}]
    assert captured["url"] == "https://peach.example/v1/chat/completions"
    assert captured["json"]["model"] == "peach/model-1"


def test_client_key_can_pin_dynamic_provider(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    key = client.post(
        "/auth/clients",
        json={"label": "custom-client", "provider": created["id"], "model": "peach/model-client"},
    ).json()["key"]
    assert runtime.get_active_provider() == "chatgpt"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-custom", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "hardcoded", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://peach.example/v1/chat/completions"
    assert captured["json"]["model"] == "peach/model-client"
    assert runtime.get_active_provider() == "chatgpt"


def test_cannot_delete_selected_or_referenced_dynamic_provider(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    provider_id = created["id"]

    client.post("/auth/providers/select", json={"provider": provider_id})
    selected = client.delete(f"/auth/custom-providers/{provider_id}")
    assert selected.status_code == 409
    assert "selected globally" in selected.json()["detail"]

    client.post("/auth/providers/select", json={"provider": "chatgpt"})
    client.post("/auth/clients", json={"label": "uses-custom", "provider": provider_id})
    referenced = client.delete(f"/auth/custom-providers/{provider_id}")
    assert referenced.status_code == 409
    assert "client key" in referenced.json()["detail"]


def test_delete_unused_dynamic_provider(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)

    response = client.delete(f"/auth/custom-providers/{created['id']}")

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert runtime.is_dynamic_provider(created["id"]) is False


def test_admin_api_alias_exposes_dynamic_registry(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    response = client.post(
        "/admin-api/custom-providers",
        json={
            "name": "Alias Provider",
            "base_url": "https://alias.example/v1",
            "api_key": "sk-alias",
            "model": "alias-model",
        },
    )
    assert response.status_code == 200
    listed = client.get("/admin-api/custom-providers")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["name"] == "Alias Provider"


def test_client_without_model_uses_dynamic_provider_default_not_other_global_model(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    client.post("/auth/providers/select", json={"provider": "bai", "model": "bai-global-model"})
    key = client.post(
        "/auth/clients",
        json={"label": "custom-default", "provider": created["id"], "model": ""},
    ).json()["key"]
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "ok", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "hardcoded", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert captured["json"]["model"] == "peach/model-1"


def test_chatgpt_client_without_model_does_not_inherit_custom_global_model(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = _create_provider(client)
    client.post("/auth/providers/select", json={"provider": created["id"], "model": "peach/override"})
    key = client.post("/auth/clients", json={"label": "chatgpt-client", "provider": "chatgpt", "model": ""}).json()["key"]
    runtime.set_client_policy(runtime.lookup_client_policy(key))
    try:
        assert provider_routing.resolve_model(runtime, "gpt-4o-mini", "chatgpt-gpt-5.6") == "chatgpt-gpt-5.6"
    finally:
        runtime.set_client_policy(None)
