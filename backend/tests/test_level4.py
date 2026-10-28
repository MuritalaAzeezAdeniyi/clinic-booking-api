import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Booking, IdempotencyRecord, Slot


client = TestClient(app)


def reset_db():
    db = SessionLocal()
    try:
        db.query(IdempotencyRecord).delete()
        db.query(Booking).delete()
        db.query(Slot).delete()
        db.commit()
    finally:
        db.close()


def auth_headers(api_key="test-key"):
    return {"X-API-Key": api_key}


def add_slot(slot_id="level4-slot"):
    db = SessionLocal()
    try:
        db.add(
            Slot(
                id=slot_id,
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()


def test_idempotency_replays_response_and_rejects_different_body(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()
    add_slot()
    payload = {"slot_id": "level4-slot", "name": "Alice", "email": "alice@example.com"}
    headers = {**auth_headers(), "Idempotency-Key": "same-request-key"}

    first = client.post("/bookings", json=payload, headers=headers)
    replay = client.post("/bookings", json=payload, headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()

    changed = client.post(
        "/bookings",
        json={**payload, "name": "Alicia"},
        headers=headers,
    )
    assert changed.status_code == 422
    assert changed.json() == {"error": "Idempotency-Key reused with different request body"}

    db = SessionLocal()
    try:
        assert db.query(Booking).count() == 1
    finally:
        db.close()


async def post_same_idempotency_request(payload, key):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        return await async_client.post(
            "/bookings",
            json=payload,
            headers={"X-API-Key": "test-key", "Idempotency-Key": key},
        )


async def send_two_same_key_requests(payload):
    return await asyncio.gather(
        post_same_idempotency_request(payload, "concurrent-idempotency-key"),
        post_same_idempotency_request(payload, "concurrent-idempotency-key"),
    )


def test_simultaneous_same_key_requests_create_one_booking(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()
    add_slot("simultaneous-slot")
    payload = {
        "slot_id": "simultaneous-slot",
        "name": "Concurrent User",
        "email": "concurrent@example.com",
    }

    responses = asyncio.run(send_two_same_key_requests(payload))

    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    db = SessionLocal()
    try:
        assert db.query(Booking).filter(Booking.slot_id == "simultaneous-slot").count() == 1
        assert db.query(IdempotencyRecord).filter_by(key="concurrent-idempotency-key").count() == 1
    finally:
        db.close()


def test_get_bookings_paginates_oldest_first_and_matches_email_case_insensitively(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()
    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="pagination-slot",
                provider="Dr Ade",
                start="2030-12-10T09:00:00Z",
                end="2030-12-10T09:30:00Z",
            )
        )
        base_time = datetime(2031, 1, 1, tzinfo=timezone.utc)
        db.add_all(
            [
                Booking(
                    id=f"page-{index}",
                    slot_id="pagination-slot",
                    name=f"Patient {index}",
                    email="Person@Example.com" if index % 2 else "person@example.com",
                    status="cancelled" if index == 2 else "confirmed",
                    created_at=base_time + timedelta(minutes=index),
                )
                for index in range(5)
            ]
            + [
                Booking(
                    id="other-email",
                    slot_id="pagination-slot",
                    name="Other Patient",
                    email="other@example.com",
                    status="confirmed",
                    created_at=base_time,
                )
            ]
        )
        db.commit()
    finally:
        db.close()

    headers = auth_headers()
    first = client.get("/bookings?email=PERSON%40EXAMPLE.COM&limit=2", headers=headers)
    assert first.status_code == 200
    first_data = first.json()
    assert [booking["id"] for booking in first_data["bookings"]] == ["page-0", "page-1"]
    assert first_data["next_cursor"]

    second = client.get(
        "/bookings?email=person%40example.com&limit=2&cursor=" + first_data["next_cursor"],
        headers=headers,
    )
    assert second.status_code == 200
    second_data = second.json()
    assert [booking["id"] for booking in second_data["bookings"]] == ["page-2", "page-3"]
    assert second_data["next_cursor"]

    third = client.get(
        "/bookings?email=Person%40Example.com&limit=2&cursor=" + second_data["next_cursor"],
        headers=headers,
    )
    assert third.status_code == 200
    third_data = third.json()
    assert [booking["id"] for booking in third_data["bookings"]] == ["page-4"]
    assert third_data["next_cursor"] is None


def test_get_bookings_rejects_missing_email_invalid_limit_and_cursor(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    reset_db()
    headers = auth_headers()

    assert client.get("/bookings", headers=headers).status_code == 400
    for limit in ("0", "51", "invalid"):
        response = client.get(f"/bookings?email=alice%40example.com&limit={limit}", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]

    invalid_cursor = client.get(
        "/bookings?email=alice%40example.com&cursor=not-a-valid-cursor",
        headers=headers,
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"error": "invalid cursor"}

    wrong_email_cursor = client.get(
        "/bookings?email=bob%40example.com&cursor=eyJlbWFpbCI6ImFsaWNlQGV4YW1wbGUuY29tIiwiY3JlYXRlZF9hdCI6IjIwMzEtMDEtMDFUMDA6MDA6MDArMDA6MDAiLCJpZCI6ImJvb2tpbmcifQ",
        headers=headers,
    )
    assert wrong_email_cursor.status_code == 400
