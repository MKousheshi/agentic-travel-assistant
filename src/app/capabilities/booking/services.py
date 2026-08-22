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


def search_bookings_by_date_range(
    session: Session,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
) -> list[Booking]:
    """
    Search bookings using an optional date range.

    - start_date only: bookings on/after start_date
    - end_date only: bookings on/before end_date
    - both: bookings within the inclusive range
    - neither: raises ValueError

    Results are ordered newest-first.
    """
    if start_date is None and end_date is None:
        raise ValueError("Provide at least one of start_date or end_date.")

    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must be earlier than or equal to end_date.")

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer.")

    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000.")

    stmt = select(Booking)

    if start_date is not None:
        stmt = stmt.where(Booking.book_date >= start_date)

    if end_date is not None:
        stmt = stmt.where(Booking.book_date <= end_date)

    stmt = stmt.order_by(Booking.book_date.desc()).limit(limit)

    return list(session.scalars(stmt))


from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session


def search_bookings_for_date(
    session: Session,
    booking_date: date,
    *,
    limit: int = 100,
) -> list[Booking]:
    """
    Return bookings made on one calendar date, using a half-open date range.

    `booking_date` is interpreted as a UTC calendar date.
    Results are ordered newest-first.
    """
    if isinstance(booking_date, datetime) or not isinstance(booking_date, date):
        raise ValueError("booking_date must be a datetime.date, not a datetime.")

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer.")

    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000.")

    start = datetime.combine(booking_date, time.min, tzinfo=timezone.utc)
    next_day = start + timedelta(days=1)

    stmt = (
        select(Booking)
        .where(
            Booking.book_date >= start,
            Booking.book_date < next_day,
        )
        .order_by(Booking.book_date.desc())
        .limit(limit)
    )

    return list(session.scalars(stmt))
