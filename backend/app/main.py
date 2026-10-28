import os
import re
import uuid
from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import SessionLocal, init_db
from app.models import Booking, Slot

app = FastAPI(title="Clinic Booking API")


def get_expected_api_key():
    return os.getenv("API_KEY", "")


def get_allowed_origins():
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed_origins = get_allowed_origins()
    is_allowed_origin = bool(origin and origin in allowed_origins)

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-API-Key, Idempotency-Key",
            "Access-Control-Expose-Headers": "Retry-After",
        }
        if is_allowed_origin:
            headers["Access-Control-Allow-Origin"] = origin
        return JSONResponse(status_code=200, content={}, headers=headers)

    if request.url.path == "/health":
        response = await call_next(request)
        if is_allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "Retry-After"
        return response

    expected = get_expected_api_key()
    provided = request.headers.get("X-API-Key")
    if not expected or not provided or not compare_digest(provided, expected):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    response = await call_next(request)
    if is_allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Expose-Headers"] = "Retry-After"
    return response

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
        db.query(Booking).delete()
        db.query(Slot).delete()

        for slot in slots:
            db.add(
                Slot(
                    id=slot["id"],
                    provider=slot["provider"],
                    start=slot["start"],
                    end=slot["end"],
                )
            )

        db.commit()
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
        results = []
        for slot in slots:
            confirmed_booking = db.query(Booking).filter(Booking.slot_id == slot.id, Booking.status == "confirmed").first()
            results.append(
                {
                    "id": slot.id,
                    "provider": slot.provider,
                    "start": slot.start,
                    "end": slot.end,
                    "available": confirmed_booking is None,
                }
            )
    finally:
        db.close()

    return {"slots": results}


@app.post("/bookings")
def create_booking(payload: dict):
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

    db = SessionLocal()
    try:
        slot = db.query(Slot).filter(Slot.id == slot_id.strip()).first()
        if slot is None:
            raise HTTPException(status_code=404, detail="slot not found")

        now = datetime.now(timezone.utc)
        current_start = parse_utc(slot.start)
        if current_start <= now:
            raise HTTPException(status_code=400, detail="slot has already started")

        booking_id = str(uuid.uuid4())
        booking = Booking(
            id=booking_id,
            slot_id=slot.id,
            name=normalized_name,
            email=normalized_email,
            status="confirmed",
        )
        db.add(booking)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="slot already booked")
        db.refresh(booking)

        return JSONResponse(
            status_code=201,
            content={
                "id": booking.id,
                "slot_id": booking.slot_id,
                "name": booking.name,
                "email": booking.email,
                "status": booking.status,
                "created_at": booking.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
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
