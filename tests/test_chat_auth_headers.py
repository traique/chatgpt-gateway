from unittest.mock import Mock

from fastapi.testclient import TestClient

from app import app
from faable import app as runtime


client = TestClient(app)


def test_chat_completions_reads_authorization_from_header(monkeypatch) -> None:
    original_key = runtime.GATEWAY_API_KEY
    runtime.GATEWAY_API_KEY = "gateway-secret"

    def fake_upstream_request(payload):
        response = Mock()
        response.status_code = 200
        response.headers = {"content-type": "text/event-stream"}
        response.iter_content.return_value = [b"data: {}\n\n"]
        return response

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream_request)
    try:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer gateway-secret"},
            json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "ping"}]},
        )
    finally:
        runtime.GATEWAY_API_KEY = original_key

    assert response.status_code == 200


def test_chat_completions_reads_x_api_key_from_header(monkeypatch) -> None:
    original_key = runtime.GATEWAY_API_KEY
    runtime.GATEWAY_API_KEY = "gateway-secret"

    def fake_upstream_request(payload):
        response = Mock()
        response.status_code = 200
        response.headers = {"content-type": "text/event-stream"}
        response.iter_content.return_value = [b"data: {}\n\n"]
        return response

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream_request)
    try:
        response = client.post(
            "/v1/chat/completions",
            headers={"X-API-Key": "gateway-secret"},
            json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "ping"}]},
        )
    finally:
        runtime.GATEWAY_API_KEY = original_key

    assert response.status_code == 200
