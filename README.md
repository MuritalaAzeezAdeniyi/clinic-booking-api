# Slotwell clinic booking

Clinic appointment booking monorepo: a FastAPI/SQLAlchemy API with a Vite + React UI.

## Architecture and layout

```text
backend/   FastAPI API, SQLAlchemy models, SQLite locally / PostgreSQL in deployment
frontend/  React single-page app built with Vite
SPEC.md    API contract and implementation decisions
```

Render builds and runs from **Root Directory `backend/`**. Vercel builds from **Root Directory `frontend/`** and publishes `dist/`.

At startup the backend creates missing database tables and adds demo appointments only when the slots table is empty. The demo schedule is 12 half-hour UTC slots from 09:00 to 11:00 over the next three days, shared between two providers.

## Booking protections

- **Double booking:** the database has a unique partial index allowing at most one confirmed booking per slot. A conflict is returned as HTTP 409; cancellation frees the slot.
- **Idempotency:** an optional `Idempotency-Key` is unique in the database. Repeating the same key and JSON body replays the stored status and response; using that key with a different body returns 422. Replays do not count against the rate limit.
- **Rate limiting:** at most five new booking attempts per normalized email in a sliding 60-second window. Failed attempts count; the sixth returns 429 with `Retry-After`. Different emails have separate counters.

## Run locally (PowerShell)

Backend terminal, from the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set API_KEY in backend/.env to a local development value.
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In `frontend/.env`, set `VITE_API_URL=http://127.0.0.1:8000` and `VITE_API_KEY` to the same development key. In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Restart Vite after changing its environment. Do not commit `.env` files.

## API

Every endpoint except `/health` requires `X-API-Key`. Errors use `{"error":"..."}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check; no API key required |
| POST | `/reset` | Replace all slots and clear bookings, idempotency records, and rate-limit counters |
| GET | `/slots?provider=...` | List slots, optionally filtered by exact provider |
| POST | `/bookings` | Create booking; optional `Idempotency-Key`; includes validation, conflict, and rate-limit responses |
| GET | `/bookings?email=...&limit=10&cursor=...` | Case-insensitive email lookup with oldest-first cursor pagination; limit 1–50 |
| GET | `/bookings/{id}` | Fetch booking by ID |
| DELETE | `/bookings/{id}` | Cancel booking and free its slot |

## Limitations and security notes

- The API key in `VITE_API_KEY` is bundled into public browser JavaScript. Anyone who can access the page can inspect it and call protected API routes—including `POST /reset`. It is not a secret or a security boundary. Production use needs real user authentication and server-side authorization (and `/reset` should be restricted or removed from public access).
- Rate-limit counters are process-local memory: they reset on restart and are not shared across instances. Keep one worker/instance for consistent rate limiting; multi-instance deployments need a shared store such as Redis.
- Startup `create_all()` creates missing tables but does not migrate existing schemas. Use a migration tool for future schema changes.
- PostgreSQL-only concurrency verification requires a real PostgreSQL database; the gated test is skipped when one is unavailable.
