from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, func, select

from app.db.schemas import BoardingPass, Booking, Ticket, TicketFlight


def get_booking_by_ref(
    session: Session,
    book_ref: str,
) -> Booking | None:
    """
    Return a booking by its 6-character reference, or None if not found.

    Raises:
        ValueError: If book_ref is not exactly 6 characters.
    """
    if len(book_ref) != 6:
        raise ValueError("book_ref must be exactly 6 characters long")

    statement = select(Booking).where(Booking.book_ref == book_ref)
    return session.exec(statement).one_or_none()


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
        raise ValueError("At least one of start_date or end_date is required")

    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date cannot be later than end_date")

    statement = select(Booking)

    if start_date is not None:
        statement = statement.where(Booking.book_date >= start_date)

    if end_date is not None:
        statement = statement.where(Booking.book_date <= end_date)

    statement = statement.order_by(col(Booking.book_date).desc()).limit(limit)

    return list(session.exec(statement).all())


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
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    start_dt = datetime.combine(booking_date, time.min, tzinfo=UTC)
    end_dt = start_dt + timedelta(days=1)

    statement = (
        select(Booking)
        .where(Booking.book_date >= start_dt)
        .where(Booking.book_date < end_dt)
        .order_by(col(Booking.book_date).desc())
        .limit(limit)
    )

    return list(session.exec(statement).all())


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
    statement = select(
        func.count(col(Booking.book_ref)),
        func.coalesce(func.sum(col(Booking.total_amount)), Decimal("0.00")),
    )

    if start_date is not None:
        statement = statement.where(Booking.book_date >= start_date)

    if end_date is not None:
        statement = statement.where(Booking.book_date <= end_date)

    booking_count, total_revenue = session.exec(statement).one()

    return BookingRevenueSummary(
        booking_count=int(booking_count or 0),
        total_revenue=total_revenue or Decimal("0.00"),
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
    booking = Booking(
        book_ref=book_ref,
        book_date=book_date,
        total_amount=total_amount,
    )

    try:
        session.add(booking)
        session.flush()

    except IntegrityError as exc:
        raise BookingAlreadyExistsError(
            f"A booking with book_ref={book_ref!r} already exists"
        ) from exc

    return booking


class BookingNotFoundError(LookupError):
    """Raised when no booking exists for the requested book_ref."""


def delete_booking_by_ref(session: Session, *, book_ref: str) -> int:
    """
    Delete all bookings matching the given reference and cascade-delete
    all related tickets, ticket_flights, and boarding_passes.

    Works safely even if non-unique duplicate book_ref records exist in the database.

    Returns:
        int: The number of booking records deleted.

    Raises:
        ValueError: If `book_ref` is not a 6-character string.
        BookingNotFoundError: If no matching booking exists.

    The function flushes the DELETE operations but does not commit the transaction.
    """
    if not isinstance(book_ref, str) or len(book_ref) != 6:
        raise ValueError("book_ref must be exactly 6 characters long")

    # 1. Check how many bookings match (safe against duplicates, unlike one_or_none())
    matching_count = session.exec(
        select(func.count()).select_from(Booking).where(Booking.book_ref == book_ref)
    ).one()

    if matching_count == 0:
        raise BookingNotFoundError(f"No booking found for book_ref={book_ref!r}")

    # Subquery identifying all ticket numbers belonging to this booking reference
    ticket_subquery = select(Ticket.ticket_no).where(Ticket.book_ref == book_ref)

    with session.begin_nested():
        # 2. Delete boarding passes associated with matching tickets
        session.exec(
            delete(BoardingPass).where(col(BoardingPass.ticket_no).in_(ticket_subquery))
        )

        # 3. Delete ticket flights associated with matching tickets
        session.exec(
            delete(TicketFlight).where(col(TicketFlight.ticket_no).in_(ticket_subquery))
        )

        # 4. Delete tickets associated with this book_ref
        session.exec(delete(Ticket).where(col(Ticket.book_ref) == book_ref))

        # 5. Delete all matching bookings in bulk
        session.exec(delete(Booking).where(col(Booking.book_ref) == book_ref))

        session.flush()

    return matching_count


@dataclass(frozen=True)
class BookingDeleteEffect:
    book_ref: str
    booking_exists: bool
    booking_count: int
    ticket_count: int
    ticket_flight_count: int
    boarding_pass_count: int

    @property
    def total_record_count(self) -> int:
        """Total number of records that would be deleted."""
        return (
            self.booking_count
            + self.ticket_count
            + self.ticket_flight_count
            + self.boarding_pass_count
        )


def preview_booking_deletion(
    session: Session,
    *,
    book_ref: str,
) -> BookingDeleteEffect:
    """
    Report the records that would be affected by deleting a booking.

    This function does not delete or modify anything.

    Raises:
        ValueError: If `book_ref` is not a 6-character string.
    """
    if not isinstance(book_ref, str) or len(book_ref) != 6:
        raise ValueError("book_ref must be exactly 6 characters long")

    booking_exists = session.exec(
        select(func.count()).select_from(Booking).where(Booking.book_ref == book_ref)
    ).one()

    ticket_count = session.exec(
        select(func.count()).select_from(Ticket).where(Ticket.book_ref == book_ref)
    ).one()

    ticket_flight_count = session.exec(
        select(func.count())
        .select_from(TicketFlight)
        .join(Ticket, col(Ticket.ticket_no) == col(TicketFlight.ticket_no))
        .where(Ticket.book_ref == book_ref)
    ).one()

    boarding_pass_count = session.exec(
        select(func.count())
        .select_from(BoardingPass)
        .join(Ticket, col(Ticket.ticket_no) == col(BoardingPass.ticket_no))
        .where(Ticket.book_ref == book_ref)
    ).one()

    return BookingDeleteEffect(
        book_ref=book_ref,
        booking_exists=bool(booking_exists),
        booking_count=int(booking_exists),
        ticket_count=int(ticket_count),
        ticket_flight_count=int(ticket_flight_count),
        boarding_pass_count=int(boarding_pass_count),
    )
