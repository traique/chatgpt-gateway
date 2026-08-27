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


def test_hoppscotch_cors_is_enabled() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "https://hoppscotch.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://hoppscotch.io"


def test_health_response_exposes_cors_header() -> None:
    response = client.get("/health", headers={"Origin": "https://hoppscotch.io"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://hoppscotch.io"
