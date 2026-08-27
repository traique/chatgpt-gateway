from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_endpoint_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_auth_endpoint_exists() -> None:
    response = client.get("/auth")
    assert response.status_code == 200
    assert response.json()["message"] == "Admin authentication endpoint"


def test_dashboard_endpoint_exists() -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.json()["message"] == "Dashboard"


def test_hoppscotch_cors_is_enabled() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "https://hoppscotch.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_health_response_exposes_cors_header() -> None:
    response = client.get("/health", headers={"Origin": "https://hoppscotch.io"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
