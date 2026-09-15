import json
from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import QueryableAttribute, selectinload
from sqlmodel import Session, col, select

from app.db.schemas import (
    Airport,
    Flight,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


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


def _localized(value: Any, lang: str = "en") -> str | None:
    """Extract a readable string from a JSON column (dict or JSON text)."""
    if value is None:
        return None

    if isinstance(value, dict):
        selected = (
            value.get(lang) or value.get("en") or next(iter(value.values()), None)
        )
        return str(selected) if selected is not None else None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value

        if isinstance(parsed, dict):
            selected = (
                parsed.get(lang)
                or parsed.get("en")
                or next(iter(parsed.values()), None)
            )
            return str(selected) if selected is not None else None

        return value

    return str(value)


def _escape_like(pattern: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_coordinates(value: str | None) -> dict[str, float | None]:
    """Parse the SQLite-safe coordinates string into lat/lon floats.

    Handles 'lat, lon', 'lat lon', 'lat; lon', JSON lists, and
    JSON dicts with latitude/longitude keys.
    """
    if value is None:
        return {"latitude": None, "longitude": None}

    value = value.strip()
    if not value:
        return {"latitude": None, "longitude": None}

    if value.startswith(("[", "{")):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None

        if isinstance(parsed, list) and len(parsed) >= 2:
            try:
                return {
                    "latitude": float(parsed[0]),
                    "longitude": float(parsed[1]),
                }
            except (TypeError, ValueError):
                pass

        if isinstance(parsed, dict):
            lat = parsed.get("latitude") or parsed.get("lat")
            lon = parsed.get("longitude") or parsed.get("lon") or parsed.get("lng")
            if lat is not None and lon is not None:
                try:
                    return {
                        "latitude": float(lat),
                        "longitude": float(lon),
                    }
                except (TypeError, ValueError):
                    pass

    normalized = value.replace(";", ",").replace(" ", ",")
    parts = [part for part in normalized.split(",") if part.strip()]
    if len(parts) >= 2:
        try:
            return {
                "latitude": float(parts[0]),
                "longitude": float(parts[1]),
            }
        except ValueError:
            pass

    return {"latitude": None, "longitude": None}


def _ensure_airport_exists(session: Session, airport_code: str) -> None:
    """Raise ValueError if the airport does not exist (lightweight check)."""
    exists = session.exec(
        select(Airport.airport_code).where(Airport.airport_code == airport_code)
    ).first()

    if exists is None:
        raise ValueError(f"Airport with airport_code '{airport_code}' not found.")


def get_airport_by_code(
    session: Session,
    airport_code: str,
) -> Airport | None:
    """Retrieve a single airport by its primary key."""
    return session.get(Airport, airport_code)


def search_airports_by_city(
    session: Session,
    city: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Airport]:
    """Case-insensitive city search across all localized city names.

    Paginated and ordered by airport_code for stable offsets.
    """
    _validate_pagination(limit, offset)

    pattern = f"%{_escape_like(city.strip().lower())}%"

    statement = (
        select(Airport)
        .where(func.lower(Airport.city).like(pattern, escape="\\"))
        .order_by(Airport.airport_code)
        .offset(offset)
        .limit(limit)
    )

    return list(session.exec(statement).all())


def get_airport_details(
    session: Session,
    airport_code: str,
    *,
    lang: str = "en",
) -> dict[str, Any]:
    """Display airport_name, city, coordinates, and timezone.

    Raises:
        ValueError: If the airport does not exist.
    """
    airport = session.get(Airport, airport_code)

    if airport is None:
        raise ValueError(f"Airport with airport_code '{airport_code}' not found.")

    coordinates = _parse_coordinates(airport.coordinates)

    return {
        "airport_code": airport.airport_code,
        "airport_name": _localized(airport.airport_name, lang),
        "city": _localized(airport.city, lang),
        "coordinates": airport.coordinates,
        "latitude": coordinates["latitude"],
        "longitude": coordinates["longitude"],
        "timezone": airport.timezone,
        "lang": lang,
    }


def get_incoming_flights(
    session: Session,
    airport_code: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """Flights arriving at the airport, ordered by scheduled arrival."""
    _validate_pagination(limit, offset)
    _ensure_airport_exists(session, airport_code)

    statement = (
        select(Flight)
        .where(Flight.arrival_airport == airport_code)
        .order_by(col(Flight.scheduled_arrival), col(Flight.flight_id))
        .offset(offset)
        .limit(limit)
        .options(*_flight_load_options())
    )

    return list(session.exec(statement).all())


def get_outgoing_flights(
    session: Session,
    airport_code: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[Flight]:
    """Flights departing from the airport, ordered by scheduled departure."""
    _validate_pagination(limit, offset)
    _ensure_airport_exists(session, airport_code)

    statement = (
        select(Flight)
        .where(Flight.departure_airport == airport_code)
        .order_by(col(Flight.scheduled_departure), col(Flight.flight_id))
        .offset(offset)
        .limit(limit)
        .options(*_flight_load_options())
    )

    return list(session.exec(statement).all())
