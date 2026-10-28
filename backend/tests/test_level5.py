from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import app.main as main
from app.database import SessionLocal
from app.main import app
from app.models import Booking, IdempotencyRecord, Slot


client = TestClient(app)


def reset_db_and_limiter():
    main.clear_rate_limit_counters()
    db = SessionLocal()
    try:
        db.query(IdempotencyRecord).delete()
        db.query(Booking).delete()
        db.query(Slot).delete()
        db.commit()
    finally:
        db.close()


def add_slots(*slot_ids):
    db = SessionLocal()
    try:
        db.add_all(
            [
                Slot(
                    id=slot_id,
                    provider="Dr Ade",
                    start="2020-12-10T09:00:00Z" if slot_id == "started-slot" else "2030-12-10T09:00:00Z",
                    end="2020-12-10T09:30:00Z" if slot_id == "started-slot" else "2030-12-10T09:30:00Z",
                )
                for slot_id in slot_ids
            ]
        )
        db.commit()
    finally:
        db.close()


def booking_payload(email, slot_id="missing-slot", name="Patient"):
    return {"slot_id": slot_id, "name": name, "email": email}


def post_booking(payload, *, key=None):
    headers = {"X-API-Key": "test-key"}
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/bookings", json=payload, headers=headers)


def test_six_attempts_count_mixed_successes_and_failures_and_return_retry_after(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    now = [1000.0]
    monkeypatch.setattr(main, "monotonic", lambda: now[0])
    reset_db_and_limiter()
    add_slots("success-slot", "started-slot")
    email = "Mixed.Attempts@example.com"

    attempts = [
        post_booking(booking_payload(email)),  # 404: missing slot
        post_booking(booking_payload(email, name="")),  # 400: missing name
        post_booking(booking_payload(email, "started-slot")),  # 400: already started
        post_booking(booking_payload(email, "success-slot")),  # 201
        post_booking({"name": "Another", "email": email}),  # 400: missing slot_id
    ]
    assert [response.status_code for response in attempts] == [404, 400, 400, 201, 400]

    sixth = post_booking(booking_payload(email, "success-slot", "Sixth"))
    assert sixth.status_code == 429
    assert sixth.json() == {"error": "rate limit exceeded; retry after 60 seconds"}
    assert sixth.headers["retry-after"] == "60"


def test_rate_limit_is_per_email(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(main, "monotonic", lambda: 2000.0)
    reset_db_and_limiter()
    add_slots("unaffected-slot")
    limited_email = "same@example.com"

    for _ in range(5):
        response = post_booking(booking_payload(limited_email))
        assert response.status_code == 404

    blocked = post_booking(booking_payload(limited_email))
    assert blocked.status_code == 429

    other_email = post_booking(booking_payload("other@example.com", "unaffected-slot"))
    assert other_email.status_code == 201


def test_idempotent_replays_do_not_count_toward_rate_limit(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(main, "monotonic", lambda: 3000.0)
    reset_db_and_limiter()
    add_slots("idempotent-slot")
    email = "replay@example.com"
    payload = booking_payload(email, "idempotent-slot")

    original = post_booking(payload, key="replay-key")
    assert original.status_code == 201

    for _ in range(5):
        replay = post_booking(payload, key="replay-key")
        assert replay.status_code == 201
        assert replay.json() == original.json()

    for _ in range(4):
        failure = post_booking(booking_payload(email))
        assert failure.status_code == 404

    replay_at_limit = post_booking(payload, key="replay-key")
    assert replay_at_limit.status_code == 201
    assert replay_at_limit.json() == original.json()

    next_attempt = post_booking(booking_payload(email))
    assert next_attempt.status_code == 429


def test_retry_after_slides_and_reset_clears_counters(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    now = [4000.0]
    monkeypatch.setattr(main, "monotonic", lambda: now[0])
    reset_db_and_limiter()
    email = "window@example.com"

    for _ in range(5):
        assert post_booking(booking_payload(email)).status_code == 404

    now[0] += 10.1
    limited = post_booking(booking_payload(email))
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "50"

    now[0] += 50
    expired_attempt = post_booking(booking_payload(email))
    assert expired_attempt.status_code == 404

    for _ in range(4):
        post_booking(booking_payload(email))
    assert post_booking(booking_payload(email)).status_code == 429

    reset = client.post("/reset", json={"slots": []}, headers={"X-API-Key": "test-key"})
    assert reset.status_code == 200
    assert post_booking(booking_payload(email)).status_code == 404


def test_simultaneous_attempts_are_counted_atomically(monkeypatch):
    monkeypatch.setattr(main, "monotonic", lambda: 5000.0)
    main.clear_rate_limit_counters()

    def attempt():
        return main.get_rate_limit_retry_after("parallel@example.com")

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: attempt(), range(20)))

    assert results.count(None) == 5
    assert results.count(60) == 15
