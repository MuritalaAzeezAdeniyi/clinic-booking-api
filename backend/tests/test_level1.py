from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app, seed_demo_slots
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


def test_seed_demo_slots_when_empty():
    reset_db()
    seed_demo_slots()

    db = SessionLocal()
    try:
        slots = db.query(Slot).all()
    finally:
        db.close()

    assert len(slots) >= 2
    assert all(slot.start.endswith("Z") for slot in slots)


def test_reset_replaces_slots_and_deletes_bookings():
    reset_db()

    db = SessionLocal()
    try:
        db.add(Slot(id="initial-slot", provider="Dr Alpha", start="2026-12-10T09:00:00Z", end="2026-12-10T09:30:00Z"))
        db.commit()
        booking = Booking(
            id="b1",
            slot_id="initial-slot",
            name="Alice",
            email="alice@example.com",
            status="confirmed",
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
    finally:
        db.close()

    response = client.post(
        "/reset",
        json={
            "slots": [
                {"id": "replacement-1", "provider": "Dr Beta", "start": "2026-12-11T10:00:00Z", "end": "2026-12-11T10:30:00Z"},
                {"id": "replacement-2", "provider": "Dr Delta", "start": "2026-12-11T11:00:00Z", "end": "2026-12-11T11:30:00Z"},
            ]
        },
    )
    assert response.status_code == 200

    slots_response = client.get("/slots")
    assert slots_response.status_code == 200
    slots = slots_response.json()["slots"]
    assert [slot["id"] for slot in slots] == ["replacement-1", "replacement-2"]

    lookup = client.get("/bookings/b1")
    assert lookup.status_code == 404


def test_get_slots_filters_and_sorts_by_start_and_available():
    reset_db()

    now = datetime.now(timezone.utc)
    slot_1 = Slot(id="s1", provider="Dr Ade", start=(now + timedelta(days=1, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), end=(now + timedelta(days=1, hours=1, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    slot_2 = Slot(id="s2", provider="Dr Ade", start=(now + timedelta(days=2, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), end=(now + timedelta(days=2, hours=1, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    slot_3 = Slot(id="s3", provider="Dr B", start=(now + timedelta(days=3, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), end=(now + timedelta(days=3, hours=1, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    db = SessionLocal()
    try:
        db.add_all([slot_1, slot_2, slot_3])
        db.add(Booking(id="b2", slot_id="s2", name="Bob", email="bob@example.com", status="confirmed"))
        db.commit()
    finally:
        db.close()

    response = client.get("/slots?provider=Dr+Ade")
    assert response.status_code == 200
    slots = response.json()["slots"]
    assert [slot["id"] for slot in slots] == ["s1", "s2"]
    assert slots[0]["available"] is True
    assert slots[1]["available"] is False


def test_post_bookings_creates_booking_and_get_booking_by_id():
    reset_db()

    db = SessionLocal()
    try:
        db.add(
            Slot(
                id="slot-123",
                provider="Dr Ade",
                start="2026-12-10T09:00:00Z",
                end="2026-12-10T09:30:00Z",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/bookings",
        json={"slot_id": "slot-123", "name": "  Alice  ", "email": " ALICE@example.com "},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["slot_id"] == "slot-123"
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"
    assert data["status"] == "confirmed"
    assert data["created_at"].endswith("Z")

    lookup = client.get(f"/bookings/{data['id']}")
    assert lookup.status_code == 200
    assert lookup.json()["id"] == data["id"]
