import os

DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///./clinic_booking.db")
API_KEY = os.getenv("API_KEY", "")
