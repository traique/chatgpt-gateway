from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401
from app import app as fastapi_app
from faable import app as runtime
from faable import provider_routing


@pytest.fixture(autouse=True)
def reset_state():
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    provider_routing._settings_cache.clear()
    provider_routing._client_policy_cache.clear()
    runtime.set_client_policy(None)
    yield
    runtime.set_client_policy(None)
    provider_routing._memory_settings.clear()
    provider_routing._memory_clients.clear()
    provider_routing._settings_cache.clear()
    provider_routing._client_policy_cache.clear()


def _sse_response(lines: list[dict]) -> Mock:
    response = Mock()
    response.status_code = 200
    response.iter_lines.return_value = [f"data: {json.dumps(line)}".encode() for line in lines]
    return response


def _create_chatgpt_client(monkeypatch) -> str:
    monkeypatch.setattr(runtime, "require_admin", lambda request: None)
    client = TestClient(fastapi_app)
    response = client.post(
        "/auth/clients",
        json={"label": "9Router", "provider": "chatgpt", "model": ""},
    )
    assert response.status_code == 200
    return response.json()["key"]


def test_chatgpt_client_never_forwards_model_from_other_provider(monkeypatch) -> None:
    # Reproduce the regression: global routing/model belongs to another provider,
    # while the bot's client key is explicitly pinned to ChatGPT.
    runtime.set_active_provider_model("generic", "peach/model-1")
    key = _create_chatgpt_client(monkeypatch)
    captured: list[dict] = []

    def fake_upstream(payload):
        captured.append(payload)
        return _sse_response([
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ])

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream)
    client = TestClient(fastapi_app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "peach/model-1", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert captured[0]["model"] == "gpt-5.6-terra"
    assert response.json()["choices"][0]["message"]["content"] == "ok"


def test_chatgpt_responses_route_resolves_model_for_pinned_client(monkeypatch) -> None:
    runtime.set_active_provider_model("generic", "peach/model-1")
    key = _create_chatgpt_client(monkeypatch)
    captured: list[dict] = []

    def fake_upstream(payload):
        captured.append(payload)
        return _sse_response([
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_ok",
                    "object": "response",
                    "status": "completed",
                    "output": [],
                },
            }
        ])

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream)
    client = TestClient(fastapi_app)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "peach/model-1", "input": "hi", "stream": False},
    )

    assert response.status_code == 200
    assert captured[0]["model"] == "gpt-5.6-terra"


def test_responses_stream_retries_one_preoutput_overload(monkeypatch) -> None:
    runtime.set_active_provider_model("chatgpt", "chatgpt-gpt-5.6")
    calls: list[dict] = []
    failed = _sse_response([
        {"type": "response.created", "response": {"id": "resp_failed", "status": "in_progress"}},
        {
            "type": "response.failed",
            "response": {
                "id": "resp_failed",
                "object": "response",
                "status": "failed",
                "error": {"code": "server_is_overloaded", "message": "server overloaded"},
            },
        },
    ])
    succeeded = _sse_response([
        {"type": "response.created", "response": {"id": "resp_ok", "status": "in_progress"}},
        {"type": "response.output_text.delta", "delta": "hello"},
        {"type": "response.completed", "response": {"id": "resp_ok", "status": "completed"}},
    ])
    responses = iter([failed, succeeded])

    def fake_upstream(payload):
        calls.append(payload)
        return next(responses)

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream)
    client = TestClient(fastapi_app)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "input": "hi", "stream": True},
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert "resp_failed" not in response.text
    assert "server_is_overloaded" not in response.text
    assert "resp_ok" in response.text
    assert "hello" in response.text


def test_chat_completions_stream_retries_one_preoutput_overload(monkeypatch) -> None:
    runtime.set_active_provider_model("chatgpt", "chatgpt-gpt-5.6")
    calls: list[dict] = []
    failed = _sse_response([
        {
            "type": "response.failed",
            "response": {
                "id": "resp_failed",
                "status": "failed",
                "error": {"code": "server_is_overloaded", "message": "server overloaded"},
            },
        }
    ])
    succeeded = _sse_response([
        {"type": "response.output_text.delta", "delta": "hello"},
        {"type": "response.completed", "response": {"status": "completed"}},
    ])
    responses = iter([failed, succeeded])

    def fake_upstream(payload):
        calls.append(payload)
        return next(responses)

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream)
    client = TestClient(fastapi_app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert "server_is_overloaded" not in response.text
    assert "hello" in response.text
