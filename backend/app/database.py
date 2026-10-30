from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import Booking, IdempotencyRecord, Slot

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Slot).first() is None:
            seed_demo_slots(db)
            db.commit()
    finally:
        db.close()


def seed_demo_slots(db):
    from datetime import datetime, time, timedelta, timezone

    from app.models import Slot

    now = datetime.now(timezone.utc)
    earliest_start = now + timedelta(hours=24)
    first_day = earliest_start.date()
    first_start = datetime.combine(first_day, time(9, 0), tzinfo=timezone.utc)
    if first_start < earliest_start:
        first_day += timedelta(days=1)
    providers = ("Dr Ade", "Dr Bisi")
    demo_slots = []

    for day_offset in range(3):
        slot_date = first_day + timedelta(days=day_offset)
        first_start = datetime.combine(slot_date, time(9, 0), tzinfo=timezone.utc)
        for slot_number in range(4):
            start = first_start + timedelta(minutes=30 * slot_number)
            end = start + timedelta(minutes=30)
            demo_slots.append(
                Slot(
                    id=f"demo-{slot_date:%Y%m%d}-{slot_number + 1}",
                    provider=providers[slot_number % len(providers)],
                    start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )

    db.add_all(demo_slots)
