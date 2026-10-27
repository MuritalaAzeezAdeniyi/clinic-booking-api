import datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Booking, Slot


client = TestClient(app)


def reset_db():
    db = SessionLocal()
    try:
        db.query(Booking).delete()
        db.query(Slot).delete()
        db.commit()
    finally:
        db.close()


def auth_headers(api_key="test-key"):
    return {"X-API-Key": api_key}


def test_missing_or_wrong_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")

    response = client.get("/slots")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}

    response = client.get("/slots", headers=auth_headers("wrong-key"))
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_options_preflight_bypasses_api_key(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    response = client.options(
        "/slots",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200


def test_post_bookings_rejects_missing_and_empty_fields(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    payloads = [
        {"name": "Alice", "email": "alice@example.com"},
        {"slot_id": "slot-1", "email": "alice@example.com"},
        {"slot_id": "slot-1", "name": "Alice"},
        {"slot_id": "slot-1", "name": "", "email": "alice@example.com"},
        {"slot_id": "slot-1", "name": "Alice", "email": ""},
    ]

    for payload in payloads:
        response = client.post("/bookings", json=payload, headers=auth_headers())
        assert response.status_code == 400
        assert response.json()["error"]


def test_post_bookings_rejects_invalid_email_and_non_string_fields(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-1",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()

    rejects = [
        {"slot_id": "slot-1", "name": "Alice", "email": "not-an-email"},
        {"slot_id": 123, "name": "Alice", "email": "a@b.com"},
        {"slot_id": "slot-1", "name": 123, "email": "a@b.com"},
        {"slot_id": "slot-1", "name": "Alice", "email": 123},
    ]

    for payload in rejects:
        response = client.post("/bookings", json=payload, headers=auth_headers())
        assert response.status_code == 400
        assert response.json()["error"]


def test_post_bookings_rejects_missing_slot_and_started_slots(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    missing = client.post(
        "/bookings",
        json={"slot_id": "missing-slot", "name": "Alice", "email": "alice@example.com"},
        headers=auth_headers(),
    )
    assert missing.status_code == 404

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="started-slot",
                provider="Dr Ade",
                start="2020-01-01T09:00:00Z",
                end="2020-01-01T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()

    started = client.post(
        "/bookings",
        json={"slot_id": "started-slot", "name": "Alice", "email": "alice@example.com"},
        headers=auth_headers(),
    )
    assert started.status_code == 400
    assert started.json()["error"]


def test_post_bookings_trims_name_and_email_and_lowercases_email(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-2",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/bookings",
        json={"slot_id": "slot-2", "name": "  Alice Smith  ", "email": " ALICE.SMITH@example.com "},
        headers=auth_headers(),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Alice Smith"
    assert data["email"] == "alice.smith@example.com"

    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.slot_id == "slot-2").one()
        assert booking.name == "Alice Smith"
        assert booking.email == "alice.smith@example.com"
    finally:
        db.close()
