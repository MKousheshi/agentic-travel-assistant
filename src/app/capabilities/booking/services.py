from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import String, Numeric, DateTime, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.exc import IntegrityError


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


@dataclass(frozen=True)
class BookingRevenueSummary:
    booking_count: int
    total_revenue: Decimal


def calculate_booking_revenue(
    session: Session,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> BookingRevenueSummary:
    """
    Calculate booking count and summed total_amount for an optional inclusive date range.

    - start_date only: bookings on/after start_date
    - end_date only: bookings on/before end_date
    - both: bookings within the inclusive range
    - neither: calculates across all bookings

    For no matching bookings:
        booking_count = 0
        total_revenue = Decimal("0.00")
    """
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must be earlier than or equal to end_date.")

    stmt = select(
        func.count(Booking.book_ref).label("booking_count"),
        func.coalesce(func.sum(Booking.total_amount), 0).label("total_revenue"),
    )

    if start_date is not None:
        stmt = stmt.where(Booking.book_date >= start_date)

    if end_date is not None:
        stmt = stmt.where(Booking.book_date <= end_date)

    row = session.execute(stmt).one()

    return BookingRevenueSummary(
        booking_count=row.booking_count,
        total_revenue=Decimal(row.total_revenue),
    )


class BookingAlreadyExistsError(ValueError):
    """Raised when a booking with the same book_ref already exists."""


def create_booking(
    session: Session,
    *,
    book_ref: str,
    book_date: datetime,
    total_amount: Decimal,
) -> Booking:
    """
    Create and persist a booking.

    The database primary-key/unique constraint is the final protection against
    duplicate book_ref values, including concurrent requests.

    This function flushes but does not commit the outer transaction.
    """
    if not isinstance(book_ref, str) or len(book_ref) != 6:
        raise ValueError("book_ref must be a string of exactly 6 characters.")

    if not isinstance(book_date, datetime):
        raise ValueError("book_date must be a datetime.")

    if not isinstance(total_amount, Decimal):
        raise ValueError("total_amount must be a Decimal.")

    if total_amount < Decimal("0.00"):
        raise ValueError("total_amount cannot be negative.")

    existing_booking = session.scalar(
        select(Booking.book_ref).where(Booking.book_ref == book_ref)
    )

    if existing_booking is not None:
        raise BookingAlreadyExistsError(
            f"A booking with reference {book_ref!r} already exists."
        )

    booking = Booking(
        book_ref=book_ref,
        book_date=book_date,
        total_amount=total_amount,
    )

    try:
        # A savepoint lets us handle a duplicate without rolling back an
        # outer transaction that may be managed by the caller.
        with session.begin_nested():
            session.add(booking)
            session.flush()  # Executes INSERT now, so uniqueness is checked now.
    except IntegrityError as exc:
        raise BookingAlreadyExistsError(
            f"A booking with reference {book_ref!r} already exists."
        ) from exc

    return booking


class BookingNotFoundError(LookupError):
    """Raised when no booking exists for the requested book_ref."""


def delete_booking_by_ref(session: Session, *, book_ref: str) -> None:
    """
    Delete one booking by its reference.

    Raises:
        ValueError: If `book_ref` is not a 6-character string.
        BookingNotFoundError: If no matching booking exists.

    The function flushes the DELETE but does not commit the transaction.
    """
    print(f"[[ deleting {book_ref}]]")
    if not isinstance(book_ref, str) or len(book_ref) != 6:
        raise ValueError("book_ref must be a string of exactly 6 characters.")

    stmt = delete(Booking).where(Booking.book_ref == book_ref)

    result = session.execute(stmt)

    if result.rowcount == 0:
        raise BookingNotFoundError(f"No booking was found with reference {book_ref!r}.")

    session.flush()
