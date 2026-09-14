import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import QueryableAttribute, selectinload
from sqlmodel import Session, col, select

from app.db.schemas import (
    Aircraft,
    Airport,
    Flight,
    TicketFlight,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

# Expected presence of actual times per status (demo airline statuses).
# True  -> actual time must be present
# False -> actual time must be absent
# None  -> no strict expectation (Delayed can be pre- or post-departure)
STATUS_TIME_RULES: dict[str, dict[str, bool | None]] = {
    "Scheduled": {"actual_departure": False, "actual_arrival": False},
    "On Time": {"actual_departure": False, "actual_arrival": False},
    "Delayed": {"actual_departure": None, "actual_arrival": None},
    "Departed": {"actual_departure": True, "actual_arrival": False},
    "Arrived": {"actual_departure": True, "actual_arrival": True},
    "Cancelled": {"actual_departure": False, "actual_arrival": False},
}


def _validate_pagination(limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero.")


def _flight_load_options() -> tuple:
    """Eager-load airports and aircraft for flight queries."""
    return (
        selectinload(cast(QueryableAttribute, Flight.departure_airport_rel)),
        selectinload(cast(QueryableAttribute, Flight.arrival_airport_rel)),
        selectinload(cast(QueryableAttribute, Flight.aircraft)),
    )


def _minutes_between(scheduled: datetime, actual: datetime) -> int:
    return int((actual - scheduled).total_seconds() // 60)


def _localized(value: Any, lang: str = "en") -> str | None:
    """Extract a readable string from a JSON column (dict or JSON text)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or next(iter(value.values()), None)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, dict):
            return (
                parsed.get(lang)
                or parsed.get("en")
                or next(iter(parsed.values()), None)
            )
        return value
    return str(value)


def get_flight_by_id(session: Session, flight_id: int) -> Flight | None:
    """Retrieve a single flight by primary key with airports/aircraft loaded."""
    statement = (
        select(Flight)
        .where(Flight.flight_id == flight_id)
        .options(*_flight_load_options())
    )
    return session.exec(statement).one_or_none()


def get_flights_by_flight_no(
    session: Session,
    flight_no: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """Paginated flights matching a flight number, ordered by scheduled departure."""
    _validate_pagination(limit, offset)

    statement = (
        select(Flight)
        .where(Flight.flight_no == flight_no)
        .order_by(col(Flight.scheduled_departure))
        .offset(offset)
        .limit(limit)
        .options(*_flight_load_options())
    )
    return list(session.exec(statement).all())


def find_flights_between_airports(
    session: Session,
    departure_airport: str,
    arrival_airport: str,
    *,
    scheduled_date: date | None = None,
    status: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """Find flights between two airports with optional date and status filters."""
    _validate_pagination(limit, offset)

    conditions = [
        col(Flight.departure_airport) == departure_airport,
        col(Flight.arrival_airport) == arrival_airport,
    ]

    if scheduled_date is not None:
        conditions.append(
            func.date(Flight.scheduled_departure) == scheduled_date.isoformat()
        )

    if status is not None:
        conditions.append(col(Flight.status) == status)

    statement = (
        select(Flight)
        .where(*conditions)
        .order_by(
            col(Flight.scheduled_departure),
            col(Flight.flight_id),
        )
        .offset(offset)
        .limit(limit)
        .options(*_flight_load_options())
    )

    return list(session.exec(statement).all())


def get_flight_status(session: Session, flight_id: int) -> dict[str, Any]:
    """Return status, scheduled/actual times, and derived delay flags."""
    flight = get_flight_by_id(session, flight_id)
    if flight is None:
        raise ValueError(f"Flight with flight_id '{flight_id}' not found.")

    departure_delay = (
        _minutes_between(flight.scheduled_departure, flight.actual_departure)
        if flight.actual_departure is not None
        else None
    )
    arrival_delay = (
        _minutes_between(flight.scheduled_arrival, flight.actual_arrival)
        if flight.actual_arrival is not None
        else None
    )

    return {
        "flight_id": flight.flight_id,
        "flight_no": flight.flight_no,
        "status": flight.status,
        "departure_airport": flight.departure_airport,
        "arrival_airport": flight.arrival_airport,
        "aircraft_code": flight.aircraft_code,
        "scheduled_departure": flight.scheduled_departure,
        "scheduled_arrival": flight.scheduled_arrival,
        "actual_departure": flight.actual_departure,
        "actual_arrival": flight.actual_arrival,
        "has_actual_departure": flight.actual_departure is not None,
        "has_actual_arrival": flight.actual_arrival is not None,
        "departure_delay_minutes": departure_delay,
        "arrival_delay_minutes": arrival_delay,
        "is_cancelled": flight.status == "Cancelled",
        "is_delayed": flight.status == "Delayed",
        "has_departed": flight.status in {"Departed", "Arrived"},
        "has_arrived": flight.status == "Arrived",
    }


def analyze_actual_times_by_status(
    session: Session,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Aggregate actual-time coverage and average delays grouped by status."""
    _validate_pagination(limit, offset)

    total_flights = session.exec(select(func.count()).select_from(Flight)).one()

    total_statuses = session.exec(
        select(func.count(func.distinct(Flight.status))).select_from(Flight)
    ).one()

    # select()'s typed overloads only cover up to ~4 mixed columns; valid at
    # runtime, but no overload matches this many.
    rows = session.exec(
        select(  # type: ignore[call-overload]  # pyright: ignore[reportCallIssue]
            col(Flight.status).label("status"),
            func.count().label("flight_count"),
            func.count(col(Flight.actual_departure)).label("with_actual_departure"),
            func.count(col(Flight.actual_arrival)).label("with_actual_arrival"),
            func.avg(
                (
                    func.julianday(Flight.actual_departure)
                    - func.julianday(Flight.scheduled_departure)
                )
                * 86400.0
            ).label("avg_departure_delay_seconds"),
            func.avg(
                (
                    func.julianday(Flight.actual_arrival)
                    - func.julianday(Flight.scheduled_arrival)
                )
                * 86400.0
            ).label("avg_arrival_delay_seconds"),
        )
        .group_by(col(Flight.status))
        .order_by(col(Flight.status))
        .offset(offset)
        .limit(limit)
    ).all()

    statuses = []
    for row in rows:
        statuses.append(
            {
                "status": row.status,
                "flight_count": row.flight_count,
                "with_actual_departure": row.with_actual_departure,
                "missing_actual_departure": row.flight_count
                - row.with_actual_departure,
                "with_actual_arrival": row.with_actual_arrival,
                "missing_actual_arrival": row.flight_count - row.with_actual_arrival,
                "avg_departure_delay_minutes": (
                    round(row.avg_departure_delay_seconds / 60, 2)
                    if row.avg_departure_delay_seconds is not None
                    else None
                ),
                "avg_arrival_delay_minutes": (
                    round(row.avg_arrival_delay_seconds / 60, 2)
                    if row.avg_arrival_delay_seconds is not None
                    else None
                ),
            }
        )

    return {
        "total_flights": total_flights,
        "statuses_returned": len(statuses),
        "offset": offset,
        "limit": limit,
        "statuses_truncated": offset + len(statuses) < total_statuses,
        "statuses": statuses,
    }


def get_aircraft_for_flight(
    session: Session,
    flight_id: int,
) -> Aircraft | None:
    flight = session.get(Flight, flight_id)

    if flight is None:
        raise ValueError(f"Flight with flight_id '{flight_id}' not found.")

    return session.get(Aircraft, flight.aircraft_code)


def get_flights_by_aircraft_code(
    session: Session,
    aircraft_code: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """Paginated flights operated by a given aircraft."""
    _validate_pagination(limit, offset)

    statement = (
        select(Flight)
        .where(Flight.aircraft_code == aircraft_code)
        .order_by(col(Flight.scheduled_departure))
        .offset(offset)
        .limit(limit)
        .options(*_flight_load_options())
    )
    return list(session.exec(statement).all())


def analyze_high_traffic_routes(
    session: Session,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Rank routes by flight count, with ticket counts and total revenue."""
    _validate_pagination(limit, offset)

    distinct_routes = (
        select(Flight.departure_airport, Flight.arrival_airport).distinct().subquery()
    )
    total_routes = session.exec(select(func.count()).select_from(distinct_routes)).one()

    # select()'s typed overloads only cover up to ~4 mixed columns; valid at
    # runtime, but no overload matches this many.
    rows = session.exec(
        select(  # type: ignore[call-overload]  # pyright: ignore[reportCallIssue]
            col(Flight.departure_airport).label("departure_airport"),
            col(Flight.arrival_airport).label("arrival_airport"),
            func.count(func.distinct(Flight.flight_id)).label("flight_count"),
            func.count(col(TicketFlight.ticket_no)).label("ticket_count"),
            func.coalesce(func.sum(TicketFlight.amount), 0).label("total_revenue"),
        )
        .outerjoin(TicketFlight, TicketFlight.flight_id == Flight.flight_id)
        .group_by(col(Flight.departure_airport), col(Flight.arrival_airport))
        .order_by(
            func.count(func.distinct(Flight.flight_id)).desc(),
            func.coalesce(func.sum(TicketFlight.amount), 0).desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    # Load names only for the routes on this page (bounded lookup).
    airport_codes = {
        code for row in rows for code in (row.departure_airport, row.arrival_airport)
    }
    airports: dict[str, Airport] = {}
    if airport_codes:
        airports = {
            airport.airport_code: airport
            for airport in session.exec(
                select(Airport).where(col(Airport.airport_code).in_(airport_codes))
            ).all()
        }

    routes = []
    for row in rows:
        departure = airports.get(row.departure_airport)
        arrival = airports.get(row.arrival_airport)
        revenue = Decimal(str(row.total_revenue or 0))
        ticket_count = row.ticket_count or 0

        routes.append(
            {
                "departure_airport": row.departure_airport,
                "departure_airport_name": (
                    _localized(departure.airport_name) if departure else None
                ),
                "departure_city": _localized(departure.city) if departure else None,
                "arrival_airport": row.arrival_airport,
                "arrival_airport_name": (
                    _localized(arrival.airport_name) if arrival else None
                ),
                "arrival_city": _localized(arrival.city) if arrival else None,
                "flight_count": row.flight_count,
                "ticket_count": ticket_count,
                "total_revenue": revenue,
                "avg_revenue_per_ticket": (
                    (revenue / ticket_count).quantize(Decimal("0.01"))
                    if ticket_count
                    else None
                ),
            }
        )

    return {
        "total_routes": total_routes,
        "routes_returned": len(routes),
        "offset": offset,
        "limit": limit,
        "routes_truncated": offset + len(routes) < total_routes,
        "routes": routes,
    }
