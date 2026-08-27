import os

from fastapi.testclient import TestClient

os.environ["GATEWAY_API_KEY"] = "test-gateway-key"
os.environ["CHATGPT_TOKEN_ENCRYPTION_KEY"] = "Z1hVQ2FhRk5lY0JjR2xYc2t3V3R4dVh6a0F5cE1tRkE="

from app import app

client = TestClient(app)


def test_health_reports_faable_transport() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["transport"] == "curl_cffi"


def test_auth_page_is_html() -> None:
    response = client.get("/auth")
    assert response.status_code == 200
    assert "Đăng nhập ChatGPT" in response.text


def test_chat_completions_requires_gateway_key() -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


def test_chat_completions_requires_chatgpt_account(monkeypatch) -> None:
    monkeypatch.setattr("app.active_account", lambda: None)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-gateway-key"},
        json={"model": "chatgpt-gpt-5.6", "messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 401
    assert "Login first" in response.json()["error"]["message"]
