import json
import re
from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterator

from sqlalchemy import Engine, bindparam, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from app.schemas.booking import (
    BookingDetails,
    TicketInfo,
    BookingSummary,
    BookingStatistics,
    BoardingPassInfo,
    DeleteBookingResult,
    FlightInfo,
    BookingSearchResult,
    DependencyCounts,
)

# ============================================================
# Configuration
# ============================================================

BOOK_REF_PATTERN = re.compile(r"^[A-Z0-9]{6}$")
SHORT_TIMEZONE_PATTERN = re.compile(r"([+-]\d{2})$")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


# ============================================================
# Validation and conversion helpers
# ============================================================


def validate_book_ref(book_ref: str) -> str:
    if not isinstance(book_ref, str):
        raise TypeError("book_ref must be a string")

    normalized = book_ref.strip().upper()

    if not BOOK_REF_PATTERN.fullmatch(normalized):
        raise ValueError("book_ref must contain exactly 6 ASCII letters or digits")

    return normalized


def validate_pagination(
    limit: int,
    offset: int,
    *,
    max_limit: int = MAX_LIMIT,
) -> tuple[int, int]:
    # bool is a subclass of int, so reject it explicitly.
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")

    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError("offset must be an integer")

    if not 1 <= limit <= max_limit:
        raise ValueError(f"limit must be between 1 and {max_limit}")

    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")

    return limit, offset


def parse_database_datetime(value: Any) -> datetime | None:
    """
    Convert a SQLite timestamp into a Python datetime.

    Handles timestamps ending in shortened offsets such as:
        2017-07-16 17:15:00+03

    by converting them to:
        2017-07-16 17:15:00+03:00
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise TypeError(f"Expected a datetime string, got {type(value).__name__}")

    normalized = value.strip()
    normalized = SHORT_TIMEZONE_PATTERN.sub(r"\1:00", normalized)

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid datetime value stored in the database: {value!r}"
        ) from exc


def serialize_database_datetime(value: datetime) -> str:
    """
    Serialize a datetime using an ISO-compatible representation.

    Examples:
        2026-08-19 10:30:00
        2026-08-19 10:30:00+03:30
    """
    if not isinstance(value, datetime):
        raise TypeError("Expected a datetime instance")

    return value.isoformat(sep=" ", timespec="seconds")


def parse_json_value(value: Any) -> Any:
    """
    SQLite usually returns JSON columns as strings. This safely converts
    valid JSON strings to Python objects while preserving non-JSON values.
    """
    if value is None:
        return None

    if isinstance(value, (dict, list, int, float, bool)):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    return value


def validate_amount(total_amount: Decimal | str | int | float) -> Decimal:
    try:
        amount = Decimal(str(total_amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("total_amount must be a valid decimal number") from exc

    if not amount.is_finite():
        raise ValueError("total_amount must be finite")

    if amount < 0:
        raise ValueError("total_amount cannot be negative")

    # numeric(10, 2): at most 8 digits before the decimal point.
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if amount > Decimal("99999999.99"):
        raise ValueError("total_amount exceeds the numeric(10, 2) database limit")

    return amount


def normalize_date_boundary(
    value: date | datetime,
    *,
    end_of_day: bool = False,
) -> datetime:
    """
    Convert a date to the beginning of that day.

    Date-range functions use a half-open interval:
        start_date <= book_date < end_date

    Therefore callers should normally pass the next day as end_date when
    searching by whole calendar days.
    """
    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, time.min)

    raise TypeError("Date boundary must be a date or datetime")


@contextmanager
def connection_scope(
    engine_or_connection: Engine | Connection,
) -> Iterator[Connection]:
    """
    Open a connection only when the caller supplied an Engine.

    A caller-owned Connection is not closed by this helper.
    """
    if isinstance(engine_or_connection, Engine):
        with engine_or_connection.connect() as connection:
            yield connection
    elif isinstance(engine_or_connection, Connection):
        yield engine_or_connection
    else:
        raise TypeError("Expected a SQLAlchemy Engine or Connection instance")


# ============================================================
# SQLite timestamp expression
# ============================================================

# Existing database timestamps may end in +03 instead of +03:00.
# This expression appends ":00" when a short timezone suffix is detected.
#
# Note: normalizing timestamps permanently is preferable because wrapping
# a column in an expression can prevent SQLite from using a normal index.
NORMALIZED_BOOK_DATE_SQL = """
CASE
    WHEN book_date GLOB '*[+-][0-9][0-9]'
        THEN book_date || ':00'
    ELSE book_date
END
"""


# ============================================================
# 1. Retrieve booking information by book_ref
# ============================================================


def get_booking_by_ref(
    engine_or_connection: Engine | Connection,
    book_ref: str,
    *,
    ticket_limit: int = DEFAULT_LIMIT,
    ticket_offset: int = 0,
    flight_limit: int = DEFAULT_LIMIT,
    flight_offset: int = 0,
) -> BookingDetails | None:
    """
    Retrieve one booking and a paginated portion of its tickets and flights.

    Pagination behavior:
    - ticket_limit/ticket_offset paginate tickets belonging to the booking.
    - flight_limit/flight_offset paginate flights across the selected tickets.

    Returns None when the booking does not exist.
    """
    book_ref = validate_book_ref(book_ref)

    ticket_limit, ticket_offset = validate_pagination(
        ticket_limit,
        ticket_offset,
    )
    flight_limit, flight_offset = validate_pagination(
        flight_limit,
        flight_offset,
    )

    booking_query = text("""
        SELECT
            book_ref,
            book_date,
            total_amount
        FROM bookings
        WHERE book_ref = :book_ref
        LIMIT 1 OFFSET 0
    """)

    ticket_query = text("""
        SELECT
            ticket_no,
            passenger_id
        FROM tickets
        WHERE book_ref = :book_ref
        ORDER BY ticket_no ASC
        LIMIT :ticket_limit OFFSET :ticket_offset
    """)

    flight_query = text("""
        SELECT
            t.ticket_no,
            f.flight_id,
            f.flight_no,
            f.scheduled_departure,
            f.scheduled_arrival,
            f.departure_airport,
            f.arrival_airport,
            departure_airport.city AS departure_city,
            arrival_airport.city AS arrival_city,
            f.status,
            f.aircraft_code,
            f.actual_departure,
            f.actual_arrival,
            tf.fare_conditions,
            tf.amount,
            bp.boarding_no,
            bp.seat_no
        FROM tickets AS t
        JOIN ticket_flights AS tf
            ON tf.ticket_no = t.ticket_no
        JOIN flights AS f
            ON f.flight_id = tf.flight_id
        LEFT JOIN airports_data AS departure_airport
            ON departure_airport.airport_code = f.departure_airport
        LEFT JOIN airports_data AS arrival_airport
            ON arrival_airport.airport_code = f.arrival_airport
        LEFT JOIN boarding_passes AS bp
            ON bp.ticket_no = tf.ticket_no
           AND bp.flight_id = tf.flight_id
        WHERE t.ticket_no IN :ticket_numbers
        ORDER BY
            t.ticket_no ASC,
            f.scheduled_departure ASC,
            f.flight_id ASC
        LIMIT :flight_limit OFFSET :flight_offset
    """).bindparams(bindparam("ticket_numbers", expanding=True))

    with connection_scope(engine_or_connection) as connection:
        booking_row = (
            connection.execute(
                booking_query,
                {"book_ref": book_ref},
            )
            .mappings()
            .one_or_none()
        )

        if booking_row is None:
            return None

        ticket_rows = (
            connection.execute(
                ticket_query,
                {
                    "book_ref": book_ref,
                    "ticket_limit": ticket_limit,
                    "ticket_offset": ticket_offset,
                },
            )
            .mappings()
            .all()
        )

        tickets_by_number: dict[str, TicketInfo] = {}

        for row in ticket_rows:
            ticket_no = row["ticket_no"]

            tickets_by_number[ticket_no] = TicketInfo(
                ticket_no=ticket_no,
                passenger_id=row["passenger_id"],
            )

        if tickets_by_number:
            flight_rows = (
                connection.execute(
                    flight_query,
                    {
                        "ticket_numbers": list(tickets_by_number),
                        "flight_limit": flight_limit,
                        "flight_offset": flight_offset,
                    },
                )
                .mappings()
                .all()
            )

            for row in flight_rows:
                boarding_pass = None

                if row["boarding_no"] is not None:
                    boarding_pass = BoardingPassInfo(
                        boarding_no=row["boarding_no"],
                        seat_no=row["seat_no"],
                    )

                flight = FlightInfo(
                    flight_id=row["flight_id"],
                    flight_no=row["flight_no"],
                    scheduled_departure=parse_database_datetime(
                        row["scheduled_departure"]
                    ),
                    scheduled_arrival=parse_database_datetime(row["scheduled_arrival"]),
                    departure_airport=row["departure_airport"],
                    arrival_airport=row["arrival_airport"],
                    departure_city=parse_json_value(row["departure_city"]),
                    arrival_city=parse_json_value(row["arrival_city"]),
                    status=row["status"],
                    aircraft_code=row["aircraft_code"],
                    actual_departure=parse_database_datetime(row["actual_departure"]),
                    actual_arrival=parse_database_datetime(row["actual_arrival"]),
                    fare_conditions=row["fare_conditions"],
                    amount=Decimal(str(row["amount"])),
                    boarding_pass=boarding_pass,
                )

                tickets_by_number[row["ticket_no"]].flights.append(flight)

        return BookingDetails(
            book_ref=booking_row["book_ref"],
            book_date=parse_database_datetime(booking_row["book_date"]),
            total_amount=Decimal(str(booking_row["total_amount"])),
            tickets=list(tickets_by_number.values()),
            ticket_limit=ticket_limit,
            ticket_offset=ticket_offset,
            flight_limit=flight_limit,
            flight_offset=flight_offset,
        )


# ============================================================
# 2. Search bookings by date or date range
# ============================================================


def search_bookings(
    engine_or_connection: Engine | Connection,
    *,
    book_date: date | None = None,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> BookingSearchResult:
    """
    Search bookings by either:

    1. An exact calendar date:
        book_date=date(2017, 7, 16)

    2. A half-open date/time range:
        start_date <= book_date < end_date

    Do not combine book_date with start_date/end_date.

    For an inclusive calendar range such as August 1 through August 19,
    pass August 20 as end_date.
    """
    limit, offset = validate_pagination(limit, offset)

    if book_date is not None and (start_date is not None or end_date is not None):
        raise ValueError("Use either book_date or a date range, not both")

    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }

    if book_date is not None:
        if isinstance(book_date, datetime):
            raise TypeError(
                "book_date must be a date, not a datetime; "
                "use start_date/end_date for datetime searches"
            )

        where_clause = f"date({NORMALIZED_BOOK_DATE_SQL}) = :book_date"
        params["book_date"] = book_date.isoformat()

    else:
        if start_date is None and end_date is None:
            raise ValueError("Provide book_date, start_date, or end_date")

        conditions: list[str] = []

        if start_date is not None:
            normalized_start = normalize_date_boundary(start_date)
            conditions.append(
                f"julianday({NORMALIZED_BOOK_DATE_SQL}) " ">= julianday(:start_date)"
            )
            params["start_date"] = serialize_database_datetime(normalized_start)

        if end_date is not None:
            normalized_end = normalize_date_boundary(end_date)
            conditions.append(
                f"julianday({NORMALIZED_BOOK_DATE_SQL}) " "< julianday(:end_date)"
            )
            params["end_date"] = serialize_database_datetime(normalized_end)

        if start_date is not None and end_date is not None:
            normalized_start = normalize_date_boundary(start_date)
            normalized_end = normalize_date_boundary(end_date)

            if normalized_start >= normalized_end:
                raise ValueError("start_date must be earlier than end_date")

        where_clause = " AND ".join(conditions)

    query = text(f"""
        SELECT
            book_ref,
            book_date,
            total_amount
        FROM bookings
        WHERE {where_clause}
        ORDER BY book_date ASC, book_ref ASC
        LIMIT :limit OFFSET :offset
    """)

    with connection_scope(engine_or_connection) as connection:
        rows = connection.execute(query, params).mappings().all()

    items = [
        BookingSummary(
            book_ref=row["book_ref"],
            book_date=parse_database_datetime(row["book_date"]),
            total_amount=Decimal(str(row["total_amount"])),
        )
        for row in rows
    ]

    return BookingSearchResult(
        items=items,
        limit=limit,
        offset=offset,
    )


# ============================================================
# 3. Calculate count and revenue for a date range
# ============================================================


def get_booking_statistics(
    engine_or_connection: Engine | Connection,
    *,
    start_date: date | datetime,
    end_date: date | datetime,
) -> BookingStatistics:
    """
    Calculate:
    - Number of bookings
    - Sum of total_amount
    - Revenue, exposed as an alias for total_amount

    The interval is half-open:
        start_date <= book_date < end_date

    This aggregate returns exactly one row, so LIMIT/OFFSET would not provide
    useful pagination.
    """
    normalized_start = normalize_date_boundary(start_date)
    normalized_end = normalize_date_boundary(end_date)

    if normalized_start >= normalized_end:
        raise ValueError("start_date must be earlier than end_date")

    query = text(f"""
        SELECT
            COUNT(*) AS booking_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM bookings
        WHERE julianday({NORMALIZED_BOOK_DATE_SQL})
                  >= julianday(:start_date)
          AND julianday({NORMALIZED_BOOK_DATE_SQL})
                  < julianday(:end_date)
        LIMIT 1 OFFSET 0
    """)

    params = {
        "start_date": serialize_database_datetime(normalized_start),
        "end_date": serialize_database_datetime(normalized_end),
    }

    with connection_scope(engine_or_connection) as connection:
        row = connection.execute(query, params).mappings().one()

    return BookingStatistics(
        start_date=normalized_start,
        end_date=normalized_end,
        booking_count=row["booking_count"],
        total_amount=Decimal(str(row["total_amount"])),
    )


# ============================================================
# 4. Create a new booking
# ============================================================


def create_booking(
    engine: Engine,
    *,
    book_ref: str,
    book_date: datetime,
    total_amount: Decimal | str | int | float,
) -> BookingSummary:
    """
    Create a new booking inside a transaction.

    Raises:
        ValueError: If the booking reference already exists or validation
                    fails.
    """
    if not isinstance(engine, Engine):
        raise TypeError(
            "create_booking expects an Engine so it can control " "the transaction"
        )

    book_ref = validate_book_ref(book_ref)
    amount = validate_amount(total_amount)

    if not isinstance(book_date, datetime):
        raise TypeError("book_date must be a datetime instance")

    serialized_book_date = serialize_database_datetime(book_date)

    duplicate_check_query = text("""
        SELECT 1
        FROM bookings
        WHERE book_ref = :book_ref
        LIMIT 1 OFFSET 0
    """)

    insert_query = text("""
        INSERT INTO bookings (
            book_ref,
            book_date,
            total_amount
        )
        VALUES (
            :book_ref,
            :book_date,
            :total_amount
        )
    """)

    params = {
        "book_ref": book_ref,
        "book_date": serialized_book_date,
        # Passing Decimal directly depends on the SQLite driver configuration.
        # A fixed-point string avoids binary floating-point conversion.
        "total_amount": str(amount),
    }

    try:
        with engine.begin() as connection:
            exists = connection.execute(
                duplicate_check_query,
                {"book_ref": book_ref},
            ).scalar_one_or_none()

            if exists is not None:
                raise ValueError(f"Booking {book_ref!r} already exists")

            connection.execute(insert_query, params)

    except IntegrityError as exc:
        raise ValueError(
            f"Could not create booking {book_ref!r}; " "the reference may already exist"
        ) from exc

    return BookingSummary(
        book_ref=book_ref,
        book_date=book_date,
        total_amount=amount,
    )


# ============================================================
# 5. Check dependencies and delete a booking
# ============================================================


def get_booking_dependency_counts(
    engine_or_connection: Engine | Connection,
    book_ref: str,
) -> DependencyCounts:
    """
    Count records that depend directly or indirectly on a booking.
    """
    book_ref = validate_book_ref(book_ref)

    query = text("""
        SELECT
            (
                SELECT COUNT(*)
                FROM tickets AS t
                WHERE t.book_ref = :book_ref
            ) AS tickets,

            (
                SELECT COUNT(*)
                FROM ticket_flights AS tf
                JOIN tickets AS t
                    ON t.ticket_no = tf.ticket_no
                WHERE t.book_ref = :book_ref
            ) AS ticket_flights,

            (
                SELECT COUNT(*)
                FROM boarding_passes AS bp
                JOIN tickets AS t
                    ON t.ticket_no = bp.ticket_no
                WHERE t.book_ref = :book_ref
            ) AS boarding_passes
        LIMIT 1 OFFSET 0
    """)

    with connection_scope(engine_or_connection) as connection:
        row = (
            connection.execute(
                query,
                {"book_ref": book_ref},
            )
            .mappings()
            .one()
        )

    return DependencyCounts(
        tickets=row["tickets"],
        ticket_flights=row["ticket_flights"],
        boarding_passes=row["boarding_passes"],
    )


def delete_booking(
    engine: Engine,
    book_ref: str,
    *,
    cascade: bool = False,
) -> DeleteBookingResult:
    """
    Delete a booking after checking its dependencies.

    Default behavior:
        cascade=False
        The booking is not deleted if tickets, ticket_flights, or
        boarding_passes depend on it.

    Cascade behavior:
        cascade=True
        Dependencies are deleted in the following order:

        1. boarding_passes
        2. ticket_flights
        3. tickets
        4. bookings

    All deletions happen in one transaction.
    """
    if not isinstance(engine, Engine):
        raise TypeError(
            "delete_booking expects an Engine so it can control " "the transaction"
        )

    book_ref = validate_book_ref(book_ref)

    booking_exists_query = text("""
        SELECT 1
        FROM bookings
        WHERE book_ref = :book_ref
        LIMIT 1 OFFSET 0
    """)

    dependency_query = text("""
        SELECT
            (
                SELECT COUNT(*)
                FROM tickets AS t
                WHERE t.book_ref = :book_ref
            ) AS tickets,

            (
                SELECT COUNT(*)
                FROM ticket_flights AS tf
                JOIN tickets AS t
                    ON t.ticket_no = tf.ticket_no
                WHERE t.book_ref = :book_ref
            ) AS ticket_flights,

            (
                SELECT COUNT(*)
                FROM boarding_passes AS bp
                JOIN tickets AS t
                    ON t.ticket_no = bp.ticket_no
                WHERE t.book_ref = :book_ref
            ) AS boarding_passes
        LIMIT 1 OFFSET 0
    """)

    delete_boarding_passes_query = text("""
        DELETE FROM boarding_passes
        WHERE ticket_no IN (
            SELECT ticket_no
            FROM tickets
            WHERE book_ref = :book_ref
        )
    """)

    delete_ticket_flights_query = text("""
        DELETE FROM ticket_flights
        WHERE ticket_no IN (
            SELECT ticket_no
            FROM tickets
            WHERE book_ref = :book_ref
        )
    """)

    delete_tickets_query = text("""
        DELETE FROM tickets
        WHERE book_ref = :book_ref
    """)

    delete_booking_query = text("""
        DELETE FROM bookings
        WHERE book_ref = :book_ref
    """)

    params = {"book_ref": book_ref}

    with engine.begin() as connection:
        exists = connection.execute(
            booking_exists_query,
            params,
        ).scalar_one_or_none()

        if exists is None:
            return DeleteBookingResult(
                book_ref=book_ref,
                deleted=False,
                dependencies=DependencyCounts(),
                message="Booking not found",
            )

        dependency_row = (
            connection.execute(
                dependency_query,
                params,
            )
            .mappings()
            .one()
        )

        dependencies = DependencyCounts(
            tickets=dependency_row["tickets"],
            ticket_flights=dependency_row["ticket_flights"],
            boarding_passes=dependency_row["boarding_passes"],
        )

        if dependencies.has_dependencies and not cascade:
            return DeleteBookingResult(
                book_ref=book_ref,
                deleted=False,
                dependencies=dependencies,
                message=(
                    "Booking has dependencies and was not deleted. "
                    "Set cascade=True to delete its tickets, flight "
                    "associations, and boarding passes."
                ),
            )

        if cascade:
            connection.execute(delete_boarding_passes_query, params)
            connection.execute(delete_ticket_flights_query, params)
            connection.execute(delete_tickets_query, params)

        result = connection.execute(delete_booking_query, params)

        if result.rowcount != 1:
            raise RuntimeError(
                f"Expected to delete one booking, deleted {result.rowcount}"
            )

    return DeleteBookingResult(
        book_ref=book_ref,
        deleted=True,
        dependencies=dependencies,
        message=(
            "Booking and its dependencies were deleted"
            if cascade and dependencies.has_dependencies
            else "Booking was deleted"
        ),
    )
