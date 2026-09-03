import os

from fastapi.testclient import TestClient

os.environ["GATEWAY_API_KEY"] = "test-gateway-key"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "password"
os.environ["CHATGPT_TOKEN_ENCRYPTION_KEY"] = "Z1hVQ2FhRk5lY0JjR2xYc2t3V3R4dVh6a0F5cE1tRkE="

from faable.app import app

client = TestClient(app)


def test_health_reports_faable_transport() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["runtime"] == "faable-curl-cffi"
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


def test_admin_login_sets_session() -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_admin_login_rejects_invalid_credentials() -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert response.status_code == 401
