# Clinic Booking API

Monorepo containing a FastAPI backend and a Vite + React frontend.

## Deployment overview

Deploy the database first, then the backend, then the frontend:

1. Create a PostgreSQL database on Neon and copy its connection string.
2. Deploy `backend/` as a Render Web Service.
3. Set the Render service's `ALLOWED_ORIGINS` to the final Vercel site origin, then deploy it.
4. Deploy `frontend/` to Vercel with the Render API URL and the same API key.
5. Run the smoke-test checklist below.

No live services are provisioned by this repository or these instructions. You must create the Neon, Render, and Vercel resources yourself.

## 1. Create the Neon database

1. In Neon, create a project and a PostgreSQL database.
2. Copy the connection string from the Neon connection details. Use the pooled connection string for the Render web service when Neon offers one.
3. Keep the connection string private. It contains database credentials. Do not commit it or put it in frontend variables.
4. The backend accepts standard `postgresql://` URLs. If a provider gives you the legacy `postgres://` form, the backend normalizes it to `postgresql+psycopg2://`; `psycopg2-binary` is installed by the backend requirements.

On first startup, SQLAlchemy `create_all()` creates the tables. The current startup initializer also inserts three demo slots when the slots table is empty. `create_all()` creates missing tables, but it does not migrate existing table schemas; schema changes later will need a migration process.

## 2. Deploy the backend to Render

1. In Render, create a **New Web Service** and connect this repository.
2. Set **Root Directory** to `backend`.
3. Use these exact commands:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Leave the worker count at **one**. Do not add `--workers` or run multiple worker processes: the Level 5 rate limiter is held in process memory.
5. Add these environment variables in Render's Environment settings:
   - `DATABASE_URL` — the Neon PostgreSQL connection string.
   - `API_KEY` — a newly generated, strong random value. Do not use the example/default key.
   - `ALLOWED_ORIGINS` — the exact frontend origin, such as `https://your-project.vercel.app`. Add additional trusted origins as a comma-separated list if needed; do not include a path or trailing slash.
6. Do not set `TEST_DATABASE_URL` on the production Render service.
7. Optional: set Render's health check path to `/health`. This endpoint is intentionally exempt from API-key auth.
8. Create the service and wait for Render's deploy to finish. Copy the deployed service URL, for example `https://your-api.onrender.com`.

The `ALLOWED_ORIGINS` list is read when the app process starts. If you change it, restart/redeploy the service. CORS is not an access-control substitute; the API still expects the `X-API-Key` header for normal endpoints.

## 3. Deploy the frontend to Vercel

1. In Vercel, import the same repository as a new project.
2. Set **Root Directory** to `frontend`.
3. Set the project build settings:
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`
   - Framework preset: **Vite** (if Vercel asks).
4. Add these environment variables for the environments you will deploy (Production, and Preview if required):
   - `VITE_API_URL` — the Render service base URL, with no trailing slash, e.g. `https://your-api.onrender.com`.
   - `VITE_API_KEY` — the same value configured as Render's `API_KEY`.
5. Deploy the project and copy its public origin, e.g. `https://your-project.vercel.app`.
6. Ensure that origin is present in Render's `ALLOWED_ORIGINS`. If you change the Render value, restart/redeploy Render. If you change Vercel environment variables, trigger a new Vercel deployment because Vite embeds them at build time.

**Important security limitation:** `VITE_API_KEY` is bundled into browser JavaScript and is visible to every site visitor. It cannot be treated as a server-side secret. This frontend/API-key design is suitable only when that limitation is acceptable; for production protection, put a trusted server-side layer in front of the API and use user authentication rather than relying on a shared browser key.

## Environment files for local development

Use `backend/.env.example` and `frontend/.env.example` as references when creating local `.env` files. Never commit real `.env` files or credentials. Vercel and Render environment variables are configured in their dashboards; do not upload local `.env` files to either service.

## Local development

Backend, from the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Set `VITE_API_URL` and `VITE_API_KEY` in `frontend/.env`, and set the matching `API_KEY` in the backend process/environment. Restart Vite after changing its environment variables.

## Smoke-test checklist

After both deployments are live:

1. **Health:** open `https://your-api.onrender.com/health`. Expect HTTP 200 and `{"status":"ok"}` without an API key.
2. **Auth required:** request `GET https://your-api.onrender.com/slots` without `X-API-Key`. Expect HTTP 401 and `{"error":"unauthorized"}`.
3. **CORS + slots:** open the Vercel site and confirm the slots load. In browser developer tools, confirm requests go to the Render URL and include `X-API-Key`; the response should allow the Vercel origin.
4. **Create booking:** choose an available future slot, enter a valid name/email, and submit. Confirm the UI shows the booking ID and confirmed status.
5. **Idempotency:** retry the same booking attempt with the same idempotency key (the frontend handles this for unchanged attempt data). Confirm the response does not create an extra booking.
6. **Conflict and cancellation:** attempt to book a slot already taken and confirm the conflict is displayed; cancel a confirmed booking and confirm its status changes to cancelled and the slot becomes available.
7. **My bookings:** search using the booking email (case-insensitive). If enough records exist, use **Next page** and confirm subsequent results appear.
8. **Rate limiting:** make six new booking attempts using the same email within 60 seconds. The sixth should receive HTTP 429 with a `Retry-After` header and a visible wait-time message. Attempts for a different email should not be affected.

## Operational limitations and manual tasks

- The Level 5 rate limiter is in process memory: counters reset when the backend restarts and are not shared across instances. Keep Render at one worker and do not scale to multiple instances if you require a single consistent limit. A shared store such as Redis is needed to share counters.
- You must create/configure the Neon, Render, and Vercel resources, enter credentials in their dashboards, set the exact Vercel origin in Render, and trigger deployments yourself.
- Rotate any API key or database credential that has been exposed. Keep Neon credentials only in Render's server-side `DATABASE_URL`; never place them in the frontend.
- The API key included in the frontend bundle is public to site visitors, as noted above.
