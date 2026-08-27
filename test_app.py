from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_endpoint_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_auth_page_exists() -> None:
    response = client.get("/auth")
    assert response.status_code == 200
    assert "ChatGPT Gateway" in response.text


def test_dashboard_requires_login() -> None:
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["location"] == "/auth"
