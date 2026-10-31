import base64
import binascii
import json
import os
import re
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from math import ceil
from secrets import compare_digest
from time import monotonic

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, insert, or_

from app.config import API_KEY
from app.database import SessionLocal, init_db
from app.models import Booking, IdempotencyRecord, Slot

app = FastAPI(title="Clinic Booking API")

# Process-local by design: counters reset on restart and are not shared across instances.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_ATTEMPTS = 5
rate_limit_lock = threading.Lock()
rate_limit_attempts: dict[str, deque[float]] = defaultdict(deque)


def get_rate_limit_retry_after(email_value):
    if not isinstance(email_value, str) or not email_value.strip():
        return None

    normalized_email = email_value.strip().lower()
    now = monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with rate_limit_lock:
        attempts = rate_limit_attempts[normalized_email]
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

        if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
            return max(1, ceil(RATE_LIMIT_WINDOW_SECONDS - (now - attempts[0])))

        attempts.append(now)
        return None


def clear_rate_limit_counters():
    with rate_limit_lock:
        rate_limit_attempts.clear()


def rate_limit_response(retry_after: int):
    return JSONResponse(
        status_code=429,
        content={"error": f"rate limit exceeded; retry after {retry_after} seconds"},
        headers={"Retry-After": str(retry_after)},
    )


def get_expected_api_key():
    return os.environ["API_KEY"] if "API_KEY" in os.environ else API_KEY


def get_allowed_origins():
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    expected = get_expected_api_key()
    provided = request.headers.get("X-API-Key")
    if not expected or not provided or not compare_digest(provided, expected):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    return await call_next(request)


# Register CORS last so it is the outermost middleware and decorates auth/error responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Idempotency-Key"],
    expose_headers=["Retry-After"],
)

init_db()


@app.on_event("startup")
def startup_event():
    init_db()


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request, exc: RequestValidationError):
    loc = exc.errors()
    field_name = "request"
    if loc:
        last_loc = loc[0].get("loc", [])
        if last_loc:
            field_name = str(last_loc[-1])

    return JSONResponse(
        status_code=400,
        content={"error": f"{field_name} is required" if field_name != "request" else "invalid request"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    detail = exc.detail
    if exc.status_code == 404:
        detail = "not found"
    return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})


@app.exception_handler(Exception)
async def unknown_exception_handler(request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "internal server error"})


def parse_utc(dt_text: str):
    return datetime.strptime(dt_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def serialize_booking(booking: Booking):
    created_at = booking.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": booking.id,
        "slot_id": booking.slot_id,
        "name": booking.name,
        "email": booking.email,
        "status": booking.status,
        "created_at": created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def create_booking_result(payload: dict, db):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid request body")

    slot_id = payload.get("slot_id")
    name = payload.get("name")
    email = payload.get("email")

    if not isinstance(slot_id, str) or not slot_id.strip():
        raise HTTPException(status_code=400, detail="slot_id is required")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(status_code=400, detail="email is required")

    normalized_name = name.strip()
    normalized_email = email.strip().lower()
    if not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized_email):
        raise HTTPException(status_code=400, detail="email is invalid")

    slot = db.query(Slot).filter(Slot.id == slot_id.strip()).first()
    if slot is None:
        raise HTTPException(status_code=404, detail="slot not found")

    if parse_utc(slot.start) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="slot has already started")

    booking = Booking(
        id=str(uuid.uuid4()),
        slot_id=slot.id,
        name=normalized_name,
        email=normalized_email,
        status="confirmed",
    )
    try:
        with db.begin_nested():
            db.add(booking)
            db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="slot already booked")

    return 201, serialize_booking(booking)


def encode_booking_cursor(email: str, booking: Booking):
    timestamp = booking.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    cursor_data = {
        "email": email,
        "created_at": timestamp.astimezone(timezone.utc).isoformat(),
        "id": booking.id,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(cursor_data, separators=(",", ":")).encode())
    return encoded.rstrip(b"=").decode("ascii")


def decode_booking_cursor(cursor: str, email: str):
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded_cursor, altchars=b"-_", validate=True)
        data = json.loads(raw.decode("utf-8"))
        cursor_email = data["email"]
        cursor_id = data["id"]
        cursor_time = datetime.fromisoformat(data["created_at"])
        if not isinstance(cursor_email, str) or not isinstance(cursor_id, str):
            raise ValueError("invalid cursor data")
        if cursor_email != email or not cursor_id:
            raise ValueError("cursor does not match email")
        if cursor_time.tzinfo is None:
            cursor_time = cursor_time.replace(tzinfo=timezone.utc)
        return cursor_time.astimezone(timezone.utc), cursor_id
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor")


def seed_demo_slots():
    from datetime import timedelta

    db = SessionLocal()
    try:
        if db.query(Slot).first() is not None:
            return

        now = datetime.now(timezone.utc)
        demo_slots = [
            Slot(
                id="demo-s1",
                provider="Dr Ade",
                start=(now + timedelta(days=1, hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                end=(now + timedelta(days=1, hours=9, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            Slot(
                id="demo-s2",
                provider="Dr Bisi",
                start=(now + timedelta(days=2, hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                end=(now + timedelta(days=2, hours=10, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            Slot(
                id="demo-s3",
                provider="Dr Ade",
                start=(now + timedelta(days=3, hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                end=(now + timedelta(days=3, hours=14, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        ]
        db.add_all(demo_slots)
        db.commit()
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/manual-error")
def manual_error():
    raise HTTPException(status_code=401, detail="bad creds")


@app.get("/requires-name")
def requires_name(name: str = Query(...)):
    return {"name": name}


@app.post("/reset")
def reset_slots(payload: dict):
    slots = payload.get("slots", [])
    db = SessionLocal()
    try:
        db.query(IdempotencyRecord).delete()
        db.query(Booking).delete()
        db.query(Slot).delete()

        if slots:
            db.execute(
                insert(Slot),
                [
                    {
                        "id": slot["id"],
                        "provider": slot["provider"],
                        "start": slot["start"],
                        "end": slot["end"],
                    }
                    for slot in slots
                ],
            )

        db.commit()
        clear_rate_limit_counters()
    finally:
        db.close()

    return {"status": "ok"}


@app.get("/slots")
def list_slots(provider: str | None = None):
    db = SessionLocal()
    try:
        query = db.query(Slot)
        if provider is not None:
            query = query.filter(Slot.provider == provider)

        slots = query.order_by(Slot.start.asc()).all()
        confirmed_slot_ids = {
            slot_id
            for (slot_id,) in db.query(Booking.slot_id)
            .filter(Booking.status == "confirmed", Booking.slot_id.in_([slot.id for slot in slots]))
            .all()
        }
        results = []
        for slot in slots:
            results.append(
                {
                    "id": slot.id,
                    "provider": slot.provider,
                    "start": slot.start,
                    "end": slot.end,
                    "available": slot.id not in confirmed_slot_ids,
                }
            )
    finally:
        db.close()

    return {"slots": results}


@app.post("/bookings")
def create_booking(payload: dict, request: Request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    db = SessionLocal()
    try:
        if not idempotency_key:
            email_value = payload.get("email") if isinstance(payload, dict) else None
            retry_after = get_rate_limit_retry_after(email_value)
            if retry_after is not None:
                return rate_limit_response(retry_after)
            status_code, response_body = create_booking_result(payload, db)
            db.commit()
            return JSONResponse(status_code=status_code, content=response_body)

        request_body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        record = IdempotencyRecord(
            key=idempotency_key,
            request_body=request_body,
            response_status=0,
            response_body="{}",
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == idempotency_key).first()
            if existing is None:
                raise
            if existing.request_body != request_body:
                return JSONResponse(status_code=422, content={"error": "Idempotency-Key reused with different request body"})
            return JSONResponse(
                status_code=existing.response_status,
                content=json.loads(existing.response_body),
            )

        email_value = payload.get("email") if isinstance(payload, dict) else None
        retry_after = get_rate_limit_retry_after(email_value)
        if retry_after is not None:
            db.rollback()
            return rate_limit_response(retry_after)

        try:
            status_code, response_body = create_booking_result(payload, db)
        except HTTPException as error:
            status_code = error.status_code
            error_message = "not found" if status_code == 404 else str(error.detail)
            response_body = {"error": error_message}

        record.response_status = status_code
        record.response_body = json.dumps(response_body, separators=(",", ":"))
        db.commit()
        return JSONResponse(status_code=status_code, content=response_body)
    finally:
        db.close()


@app.get("/bookings")
def list_bookings(
    email: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
):
    if email is None or not email.strip():
        raise HTTPException(status_code=400, detail="email is required")
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50")

    normalized_email = email.strip().lower()
    db = SessionLocal()
    try:
        query = db.query(Booking).filter(func.lower(Booking.email) == normalized_email)
        if cursor is not None:
            cursor_time, cursor_id = decode_booking_cursor(cursor, normalized_email)
            query = query.filter(
                or_(
                    Booking.created_at > cursor_time,
                    and_(Booking.created_at == cursor_time, Booking.id > cursor_id),
                )
            )

        page = query.order_by(Booking.created_at.asc(), Booking.id.asc()).limit(limit + 1).all()
        has_more = len(page) > limit
        page = page[:limit]
        next_cursor = encode_booking_cursor(normalized_email, page[-1]) if has_more and page else None
        return {
            "bookings": [serialize_booking(booking) for booking in page],
            "next_cursor": next_cursor,
        }
    finally:
        db.close()


@app.delete("/bookings/{booking_id}")
def delete_booking(booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking is None:
            raise HTTPException(status_code=404, detail="booking not found")
        if booking.status == "cancelled":
            raise HTTPException(status_code=409, detail="booking already cancelled")

        booking.status = "cancelled"
        db.commit()
        db.refresh(booking)

        return {
            "id": booking.id,
            "slot_id": booking.slot_id,
            "name": booking.name,
            "email": booking.email,
            "status": booking.status,
            "created_at": booking.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    finally:
        db.close()


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking is None:
            raise HTTPException(status_code=404, detail="booking not found")
        return {
            "id": booking.id,
            "slot_id": booking.slot_id,
            "name": booking.name,
            "email": booking.email,
            "status": booking.status,
            "created_at": booking.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    finally:
        db.close()
