import os
from pathlib import Path

from dotenv import dotenv_values

DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///./clinic_booking.db")
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
ENV_FILE_VALUES = dotenv_values(ENV_FILE)
API_KEY = os.getenv("API_KEY") or ENV_FILE_VALUES.get("API_KEY", "")
