from decimal import Decimal
from datetime import datetime

from sqlalchemy import String, Numeric, DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


class Base(DeclarativeBase):
    pass


class Booking(Base):
    __tablename__ = "bookings"

    book_ref: Mapped[str] = mapped_column(String(6), primary_key=True)
    book_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


def get_booking_by_ref(session: Session, book_ref: str) -> Booking | None:
    """
    Return a booking by its 6-character reference, or None if not found.

    Raises:
        ValueError: If book_ref is not exactly 6 characters.
    """
    if not isinstance(book_ref, str) or len(book_ref) != 6:
        raise ValueError("book_ref must be a string of exactly 6 characters.")

    stmt = select(Booking).where(Booking.book_ref == book_ref)
    return session.scalar(stmt)
