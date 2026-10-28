from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import relationship

from app.database import Base


class Slot(Base):
    __tablename__ = "slots"

    id = Column(String, primary_key=True, index=True)
    provider = Column(String, nullable=False)
    start = Column(String, nullable=False)
    end = Column(String, nullable=False)
    bookings = relationship("Booking", back_populates="slot", cascade="all, delete-orphan")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index(
            "ix_unique_confirmed_booking_per_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
    )

    id = Column(String, primary_key=True, index=True)
    slot_id = Column(String, ForeignKey("slots.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="confirmed")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    slot = relationship("Slot", back_populates="bookings")
