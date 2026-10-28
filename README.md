# Clinic Booking API Monorepo

This repository contains the backend API and the React frontend for the clinic booking app.

## Structure

- backend/: FastAPI backend service
- frontend/: Vite + React frontend app

## Environment

Copy the example env files before running locally:

- backend/.env.example -> backend/.env
- frontend/.env.example -> frontend/.env

## Backend

Run from the backend directory:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Frontend

Run from the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

## Rate limit note

The Level 5 booking rate limiter is held in process memory. Its counters reset
when the backend restarts and are not shared across multiple backend instances;
deployments that need a shared limit should use a shared store such as Redis.
