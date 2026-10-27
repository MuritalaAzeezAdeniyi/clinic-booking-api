from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_not_found_error():
    response = client.get("/not-here")
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


def test_http_exception_returns_error_payload():
    response = client.get("/manual-error")
    assert response.status_code == 401
    assert response.json() == {"error": "bad creds"}


def test_request_validation_uses_400_error_payload():
    response = client.get("/requires-name")
    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload
    assert "name" in payload["error"].lower()
