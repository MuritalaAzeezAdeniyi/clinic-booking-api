import asyncio
import os

import httpx
import pytest

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


def test_delete_booking_sets_status_to_cancelled_and_frees_slot(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-cancel",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.commit()
        booking = Booking(
            id="booking-cancel",
            slot_id="slot-cancel",
            name="Alice",
            email="alice@example.com",
            status="confirmed",
        )
        db.add(booking)
        db.commit()
    finally:
        db.close()

    response = client.delete("/bookings/booking-cancel", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["id"] == "booking-cancel"

    second = client.post(
        "/bookings",
        json={"slot_id": "slot-cancel", "name": "Bob", "email": "bob@example.com"},
        headers=auth_headers(),
    )
    assert second.status_code == 201


def test_delete_booking_rejects_unknown_and_already_cancelled(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
    reset_db()

    missing = client.delete("/bookings/missing-booking", headers=auth_headers())
    assert missing.status_code == 404

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-cancelled",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.add(
            Booking(
                id="booking-cancelled",
                slot_id="slot-cancelled",
                name="Alice",
                email="alice@example.com",
                status="cancelled",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.delete(
        "/bookings/booking-cancelled",
        headers={**auth_headers(), "Origin": "http://localhost:5173"},
    )
    assert response.status_code == 409
    assert response.json()["error"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def create_booking_request(payload):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/bookings",
            json=payload,
            headers={"X-API-Key": "test-key"},
        )
        return response.status_code


async def run_concurrent_booking_requests():
    return await asyncio.gather(
        *[
            create_booking_request(
                {
                    "slot_id": "slot-concurrency",
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                }
            )
            for i in range(10)
        ]
    )


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgres"),
    reason="Real PostgreSQL is required for database-enforced slot locking under concurrency.",
)
def test_concurrent_post_bookings_same_slot_only_one_succeeds(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-concurrency",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()

    statuses = asyncio.run(run_concurrent_booking_requests())

    assert statuses.count(201) == 1
    assert statuses.count(409) == 9
