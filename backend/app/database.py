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
        has_slots = db.query(Slot).first() is not None
        if not has_slots:
            from datetime import datetime, timedelta, timezone

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
