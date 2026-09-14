from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db.schemas import (
    BoardingPass,
    Booking,
    Flight,
    Ticket,
    TicketFlight,
)

# Tune these values according to your API and database requirements.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_ANALYSIS_SEGMENTS = 100


class TicketDeletionError(Exception):
    """Raised when a ticket cannot be deleted safely."""


def _validate_pagination(limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")

    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero.")


def get_ticket_by_number(
    session: Session,
    ticket_no: str,
) -> Ticket | None:
    """
    Retrieve one ticket by ticket number.

    Related booking and ticket-flight records are eagerly loaded.
    Does not commit or modify the transaction.
    """
    statement = (
        select(Ticket)
        .where(Ticket.ticket_no == ticket_no)
        .options(
            selectinload(Ticket.booking),
            selectinload(Ticket.ticket_flights),
        )
    )

    return session.exec(statement).one_or_none()


def get_tickets_by_passenger_id(
    session: Session,
    passenger_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Ticket]:
    """
    Retrieve a bounded page of tickets for a passenger.

    Results are ordered by ticket number for stable pagination.
    """
    _validate_pagination(limit, offset)
    normalized_id = passenger_id.replace(" ", "")

    statement = (
        select(Ticket)
        .where(func.replace(Ticket.passenger_id, " ", "") == normalized_id)
        .order_by(Ticket.ticket_no)
        .offset(offset)
        .limit(limit)
        .options(
            selectinload(Ticket.booking),
            selectinload(Ticket.ticket_flights).selectinload(TicketFlight.flight),
            selectinload(Ticket.boarding_passes),
        )
    )

    return list(session.exec(statement).all())


def get_flights_by_ticket_no(
    session: Session,
    ticket_no: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """
    Retrieve a bounded page of flights associated with a ticket.
    """
    _validate_pagination(limit, offset)

    statement = (
        select(Flight)
        .join(
            TicketFlight,
            TicketFlight.flight_id == Flight.flight_id,
        )
        .where(TicketFlight.ticket_no == ticket_no)
        .order_by(Flight.flight_id)
        .offset(offset)
        .limit(limit)
        .options(
            selectinload(Flight.departure_airport_rel),
            selectinload(Flight.arrival_airport_rel),
            selectinload(Flight.aircraft),
        )
    )

    return list(session.exec(statement).all())


def create_ticket(
    session: Session,
    book_ref: str,
    ticket_no: str,
    passenger_id: str,
) -> Ticket:
    """
    Create a ticket for an existing booking.

    The ticket is flushed but not committed. The caller controls the
    surrounding transaction.
    """
    booking_exists = session.exec(
        select(Booking.book_ref).where(Booking.book_ref == book_ref)
    ).first()

    if booking_exists is None:
        raise ValueError(f"Booking with book_ref '{book_ref}' does not exist.")

    ticket_exists = session.exec(
        select(Ticket.ticket_no).where(Ticket.ticket_no == ticket_no)
    ).first()

    if ticket_exists is not None:
        raise ValueError(f"Ticket with ticket_no '{ticket_no}' already exists.")

    ticket = Ticket(
        ticket_no=ticket_no,
        book_ref=book_ref,
        passenger_id=passenger_id,
    )

    session.add(ticket)

    # Makes the INSERT happen inside the current transaction without
    # committing it. It also exposes database constraint errors here.
    session.flush()

    return ticket


def get_ticket_deletion_effect(
    session: Session,
    ticket_no: str,
) -> dict[str, Any]:
    """
    Return the expected deletion effect for a ticket.

    No records are modified and no commit/rollback is performed.
    """
    ticket = session.get(Ticket, ticket_no)

    if ticket is None:
        raise ValueError(f"Ticket with ticket_no '{ticket_no}' not found.")

    ticket_flight_count = session.exec(
        select(func.count())
        .select_from(TicketFlight)
        .where(TicketFlight.ticket_no == ticket_no)
    ).one()

    boarding_pass_count = session.exec(
        select(func.count())
        .select_from(BoardingPass)
        .where(BoardingPass.ticket_no == ticket_no)
    ).one()

    deletion_blocked = boarding_pass_count > 0

    return {
        "ticket_no": ticket.ticket_no,
        "book_ref": ticket.book_ref,
        "passenger_id": ticket.passenger_id,
        "ticket_exists": True,
        "ticket_flight_count": ticket_flight_count,
        "boarding_pass_count": boarding_pass_count,
        "deletion_blocked": deletion_blocked,
        "will_delete_ticket": not deletion_blocked,
        "will_delete_delete_ticket_flights": (
            not deletion_blocked and ticket_flight_count > 0
        ),
        "blocking_dependencies": (["boarding_passes"] if deletion_blocked else []),
    }


def delete_ticket(
    session: Session,
    ticket_no: str,
) -> dict[str, Any]:
    """
    Delete a ticket and its TicketFlight dependencies.

    Deletion is blocked when boarding passes exist.

    The operation is performed inside the current transaction. This
    function does not commit or rollback.
    """
    ticket = session.get(Ticket, ticket_no)

    if ticket is None:
        raise ValueError(f"Ticket with ticket_no '{ticket_no}' not found.")

    boarding_pass_exists = session.exec(
        select(BoardingPass.ticket_no)
        .where(BoardingPass.ticket_no == ticket_no)
        .limit(1)
    ).first()

    if boarding_pass_exists is not None:
        raise TicketDeletionError(
            f"Cannot delete ticket '{ticket_no}': it has one or more boarding passes."
        )

    ticket_flight_count = session.exec(
        select(func.count())
        .select_from(TicketFlight)
        .where(TicketFlight.ticket_no == ticket_no)
    ).one()

    book_ref = ticket.book_ref
    passenger_id = ticket.passenger_id

    # Delete dependent rows first because no ORM cascade was configured.
    session.exec(delete(TicketFlight).where(TicketFlight.ticket_no == ticket_no))

    session.delete(ticket)

    # Flushes both DELETE operations but does not commit them.
    session.flush()

    return {
        "success": True,
        "deleted_ticket_no": ticket_no,
        "book_ref": book_ref,
        "passenger_id": passenger_id,
        "deleted_ticket_flights": ticket_flight_count,
    }


def analyze_ticket_fares(
    session: Session,
    ticket_no: str,
    *,
    segment_limit: int = MAX_ANALYSIS_SEGMENTS,
    segment_offset: int = 0,
) -> dict[str, Any]:
    """
    Analyze fare_conditions and amount for a ticket.

    Aggregate values cover all ticket-flight segments. The detailed
    ``segments`` list is paginated to protect output size.
    """
    if segment_limit < 1 or segment_limit > MAX_ANALYSIS_SEGMENTS:
        raise ValueError(
            f"segment_limit must be between 1 and {MAX_ANALYSIS_SEGMENTS}."
        )

    if segment_offset < 0:
        raise ValueError("segment_offset must be greater than or equal to zero.")

    ticket_exists = session.exec(
        select(Ticket.ticket_no).where(Ticket.ticket_no == ticket_no)
    ).first()

    if ticket_exists is None:
        raise ValueError(f"Ticket with ticket_no '{ticket_no}' not found.")

    # Overall aggregate across all segments.
    aggregate = session.exec(
        select(
            func.count(TicketFlight.flight_id),
            func.coalesce(
                func.sum(TicketFlight.amount),
                Decimal("0.00"),
            ),
            func.min(TicketFlight.amount),
            func.max(TicketFlight.amount),
        ).where(TicketFlight.ticket_no == ticket_no)
    ).one()

    segment_count, total_amount, minimum_amount, maximum_amount = aggregate
    total_amount = total_amount or Decimal("0.00")

    average_amount = total_amount / segment_count if segment_count else Decimal("0.00")

    # Grouped summary across all segments.
    grouped_rows = session.exec(
        select(
            TicketFlight.fare_conditions,
            func.count(TicketFlight.flight_id),
            func.sum(TicketFlight.amount),
        )
        .where(TicketFlight.ticket_no == ticket_no)
        .group_by(TicketFlight.fare_conditions)
        .order_by(TicketFlight.fare_conditions)
    ).all()

    fare_conditions = {
        fare_condition: {
            "segment_count": count,
            "total_amount": amount,
        }
        for fare_condition, count, amount in grouped_rows
    }

    # Only the requested detail page is loaded into Python.
    segment_rows = session.exec(
        select(TicketFlight)
        .where(TicketFlight.ticket_no == ticket_no)
        .order_by(TicketFlight.flight_id)
        .offset(segment_offset)
        .limit(segment_limit)
    ).all()

    segments = [
        {
            "flight_id": ticket_flight.flight_id,
            "fare_conditions": ticket_flight.fare_conditions,
            "amount": ticket_flight.amount,
        }
        for ticket_flight in segment_rows
    ]

    return {
        "ticket_no": ticket_no,
        "segment_count": segment_count,
        "total_amount": total_amount,
        "average_amount": average_amount.quantize(Decimal("0.01")),
        "minimum_amount": minimum_amount,
        "maximum_amount": maximum_amount,
        "fare_conditions": fare_conditions,
        "segments": segments,
        "segments_returned": len(segments),
        "segment_offset": segment_offset,
        "segment_limit": segment_limit,
        "segments_truncated": (segment_offset + len(segments) < segment_count),
    }
