import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app
from faable import app as runtime
from faable import provider_routing
from faable.provider_routing import resolve_model


@pytest.fixture(autouse=True)
def reset_provider_state():
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    provider_routing._models_cache = {"ts": 0.0, "models": []}
    original = (runtime.BAI_API_KEY, runtime.BAI_BASE_URL)
    yield
    runtime.BAI_API_KEY, runtime.BAI_BASE_URL = original
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    provider_routing._models_cache = {"ts": 0.0, "models": []}


def _activate_bai(model: str = "deepseek-v4-flash") -> None:
    runtime.set_active_provider_model("bai", model)


def test_default_active_provider_is_chatgpt() -> None:
    assert runtime.get_active_provider() == "chatgpt"
    assert runtime.get_active_model() == ""


def test_set_active_provider_model_rejects_unknown_provider() -> None:
    import fastapi

    with pytest.raises(fastapi.HTTPException) as error:
        runtime.set_active_provider_model("nope", "")
    assert error.value.status_code == 400


def test_resolve_model_replaces_alias_with_active_model() -> None:
    runtime.set_active_provider_model("bai", "deepseek-v4-flash")
    assert resolve_model(runtime, "chatgpt-gpt-5.6", "chatgpt-gpt-5.6") == "deepseek-v4-flash"
    assert resolve_model(runtime, "", "chatgpt-gpt-5.6") == "deepseek-v4-flash"
    assert resolve_model(runtime, "gpt-5.6-codex", "chatgpt-gpt-5.6") == "gpt-5.6-codex"


def test_resolve_model_without_active_model_keeps_requested() -> None:
    assert resolve_model(runtime, "chatgpt-gpt-5.6", "chatgpt-gpt-5.6") == "chatgpt-gpt-5.6"


def test_providers_endpoint_lists_providers(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    response = client.get("/auth/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["active_provider"] == "chatgpt"
    assert [p["id"] for p in body["providers"]] == ["chatgpt", "bai"]
    chatgpt = body["providers"][0]
    assert chatgpt["configured"] is True
    assert "chatgpt-gpt-5.6" in chatgpt["models"]
    assert body["providers"][1]["configured"] is False


def test_select_provider_endpoint_persists_selection(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(app)

    response = client.post(
        "/auth/providers/select",
        json={"provider": "bai", "model": "deepseek-v4-flash"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "active_provider": "bai", "active_model": "deepseek-v4-flash"}
    assert client.get("/auth/providers").json()["active_provider"] == "bai"


def test_chat_completions_bai_non_stream_passthrough(monkeypatch) -> None:
    _activate_bai("deepseek-v4-flash")
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-1", "object": "chat.completion", "model": "deepseek-v4-flash"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"
    assert captured["url"] == "https://api.b.ai/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["headers"]["Authorization"] == "Bearer sk-bai"


def test_chat_completions_bai_stream_passthrough(monkeypatch) -> None:
    _activate_bai()
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")

    def fake_post(url, **kwargs):
        assert kwargs["stream"] is True
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n', b"data: [DONE]\n\n"]
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes()).decode()
    assert 'delta' in body


def test_chat_completions_bai_missing_key_returns_503(monkeypatch) -> None:
    _activate_bai()
    monkeypatch.setattr(runtime, "BAI_API_KEY", "")
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "BAI_API_KEY" in response.json()["detail"]


def test_v1_models_reflects_active_bai_provider(monkeypatch) -> None:
    _activate_bai()
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")

    def fake_get(url, **kwargs):
        response = Mock()
        response.json.return_value = {"object": "list", "data": [{"id": "deepseek-v4-flash"}, {"id": "gpt-5.6"}]}
        return response

    monkeypatch.setattr(runtime.requests, "get", fake_get)
    client = TestClient(app)

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [m["id"] for m in data] == ["deepseek-v4-flash", "gpt-5.6"]
    assert all(m["owned_by"] == "b-ai" for m in data)


def test_v1_models_chatgpt_provider_unchanged() -> None:
    client = TestClient(app)

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-gateway-key"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == "chatgpt-gpt-5.6"
    assert data[0]["owned_by"] == "openai-chatgpt"


def test_v1_messages_bai_native_passthrough(monkeypatch) -> None:
    _activate_bai("deepseek-v4-flash")
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Xin chao"}],
            "stop_reason": "end_turn",
        }
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert captured["url"] == "https://api.b.ai/v1/messages"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["headers"]["x-api-key"] == "sk-bai"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


def test_responses_endpoint_bai_passthrough(monkeypatch) -> None:
    _activate_bai()
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "resp_1", "object": "response", "status": "completed"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)
    client = TestClient(app)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "deepseek-v4-flash", "input": "hi", "stream": False},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "resp_1"
    assert captured["url"] == "https://api.b.ai/v1/responses"


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    return TestClient(app)


def test_create_client_key_and_list_masked(monkeypatch) -> None:
    client = _admin_client(monkeypatch)

    created = client.post("/auth/clients", json={"label": "Bot", "provider": "bai", "model": "deepseek-v4-flash"})
    assert created.status_code == 200
    key = created.json()["key"]
    assert key.startswith("gwc-")

    listed = client.get("/auth/clients").json()["data"]
    assert len(listed) == 1
    assert listed[0]["label"] == "Bot"
    assert listed[0]["provider"] == "bai"
    assert listed[0]["key_masked"].endswith(key[-4:])
    assert key not in listed[0]["key_masked"]


def test_client_key_routes_to_bai_while_global_stays_chatgpt(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    key = client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": "deepseek-v4-flash"}).json()["key"]
    assert runtime.get_active_provider() == "chatgpt"
    monkeypatch.setattr(runtime, "BAI_API_KEY", "sk-bai")

    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "cmpl-1", "object": "chat.completion"}
        return response

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://api.b.ai/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert runtime.get_active_provider() == "chatgpt"


def test_master_key_still_uses_global_provider(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": "deepseek-v4-flash"})

    called: dict = {}

    def fake_upstream_request(payload):
        called["payload"] = payload

        class FakeResponse:
            status_code = 200

            def iter_lines(self):
                return iter([
                    b'data: {"type":"response.output_text.delta","delta":"ok"}',
                    b'data: {"type":"response.completed"}',
                ])

            def close(self):
                pass

        return FakeResponse()

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream_request)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert "b.ai" not in json.dumps(called["payload"])
    assert called["payload"]["model"] == "gpt-5.6-terra"


def test_disabled_client_key_is_rejected(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": "m1"}).json()

    client.post(f"/auth/clients/{created['id']}", json={"status": "disabled"})

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {created['key']}"},
        json={"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


def test_deleted_client_key_is_rejected(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    created = client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": "m1"}).json()
    key, client_id = created["key"], created["id"]

    assert client.delete(f"/auth/clients/{client_id}").status_code == 200
    assert client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
    ).status_code == 401


def test_duplicate_client_key_rejected(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    first = client.post("/auth/clients", json={"label": "a", "provider": "bai", "model": "m1", "key": "gwc-custom-1"})
    assert first.status_code == 200
    second = client.post("/auth/clients", json={"label": "b", "provider": "chatgpt", "key": "gwc-custom-1"})
    assert second.status_code == 400


def test_unknown_client_key_rejected(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": "m1"})

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gwc-not-registered"},
        json={"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


def test_client_policy_without_model_falls_back_to_global_model(monkeypatch) -> None:
    client = _admin_client(monkeypatch)
    client.post("/auth/providers/select", json={"provider": "bai", "model": "global-model"})
    key = client.post("/auth/clients", json={"label": "bot", "provider": "bai", "model": ""}).json()["key"]
    assert key.startswith("gwc-")

    # Client policy without a model falls back to the admin's global model pick.
    assert resolve_model(runtime, "chatgpt-gpt-5.6", "chatgpt-gpt-5.6") == "global-model"
