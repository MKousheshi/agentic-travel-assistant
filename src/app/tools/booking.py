from typing import Optional
import re

from app.schemas.schema import BookingDetails, BoardingPassInfo, FlightSegment
from sqlalchemy import text
from sqlalchemy.engine import Engine, Connection
from typing import Optional
import re

from sqlalchemy import text
from sqlalchemy.engine import Engine, Connection



def get_booking_details(
    db_engine_or_conn: Engine | Connection, 
    book_ref: str,
    limit: int = 50,
    offset: int = 0
) -> Optional[BookingDetails]:
    """
    Fetches comprehensive booking details securely from a SQLite database.
    Supports configurable limit and offset constraints for tickets to optimize memory usage.
    
    :param db_engine_or_conn: Active SQLAlchemy Engine or Connection object.
    :param book_ref: 6-character alphanumeric booking reference.
    :param limit: Maximum number of tickets to load in this query execution.
    :param offset: Offset index for pagination of tickets within the booking.
    :return: BookingDetails object if found, otherwise None.
    :raises ValueError: If input validation fails on constraints or inputs.
    """
    # 1. Strict Input Validation & Sanitization
    book_ref = book_ref.strip().upper()
    if not re.fullmatch(r"^[A-Z0-9]{6}$", book_ref):
        raise ValueError("Invalid book_ref format. Must be exactly 6 alphanumeric characters.")
    
    if limit < 1 or offset < 0:
        raise ValueError("Limit must be >= 1 and Offset must be >= 0.")

    # 2. Standard SQL Query compatible with SQLite (Uses explicit JOINs)
    # The Subquery locks down the pagination boundaries on the 'tickets' table.
    query = text("""
        WITH paginated_tickets AS (
            SELECT ticket_no, passenger_id
            FROM tickets
            WHERE book_ref = :book_ref
            LIMIT :limit OFFSET :offset
        )
        SELECT 
            b.book_ref,
            b.book_date,
            b.total_amount,
            t.ticket_no,
            t.passenger_id,
            f.flight_id,
            f.flight_no,
            tf.fare_conditions,
            tf.amount,
            f.scheduled_departure,
            f.scheduled_arrival,
            f.actual_departure,
            f.actual_arrival,
            f.status,
            f.aircraft_code,
            f.departure_airport,
            dep_air.city AS departure_city,
            f.arrival_airport,
            arr_air.city AS arrival_city,
            bp.boarding_no,
            bp.seat_no
        FROM bookings b
        LEFT JOIN paginated_tickets t ON b.book_ref = :book_ref
        LEFT JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
        LEFT JOIN flights f ON tf.flight_id = f.flight_id
        LEFT JOIN airports_data dep_air ON f.departure_airport = dep_air.airport_code
        LEFT JOIN airports_data arr_air ON f.arrival_airport = arr_air.airport_code
        LEFT JOIN boarding_passes bp ON bp.ticket_no = tf.ticket_no AND bp.flight_id = tf.flight_id
        WHERE b.book_ref = :book_ref
        ORDER BY t.ticket_no, f.scheduled_departure ASC;
    """)

    # 3. Execution with Bound Parameter dictionary
    params = {
        "book_ref": book_ref,
        "limit": limit,
        "offset": offset
    }

    with (db_engine_or_conn.connect() if isinstance(db_engine_or_conn, Engine) else db_engine_or_conn) as conn:
        rows = conn.execute(query, params).mappings().fetchall()

        if not rows:
            return None

        # 4. Programmatic aggregation of results
        first_row = rows[0]
        booking_data = {
            "book_ref": first_row["book_ref"],
            "book_date": first_row["book_date"],
            "total_amount": first_row["total_amount"],
            "tickets": []
        }

        tickets_map = {}
        for row in rows:
            # Skip if there are no associated tickets
            if not row["ticket_no"]:
                continue

            ticket_no = row["ticket_no"]
            if ticket_no not in tickets_map:
                tickets_map[ticket_no] = {
                    "ticket_no": ticket_no,
                    "passenger_id": row["passenger_id"],
                    "flights": []
                }
                booking_data["tickets"].append(tickets_map[ticket_no])

            # If there's a flight segment associated with the ticket
            if row["flight_id"] is not None:
                boarding_pass = None
                if row["boarding_no"] is not None:
                    boarding_pass = BoardingPassInfo(
                        boarding_no=row["boarding_no"],
                        seat_no=row["seat_no"]
                    )

                flight_segment = FlightSegment(
                    flight_id=row["flight_id"],
                    flight_no=row["flight_no"],
                    fare_conditions=row["fare_conditions"],
                    amount=row["amount"],
                    scheduled_departure=row["scheduled_departure"],
                    scheduled_arrival=row["scheduled_arrival"],
                    actual_departure=row["actual_departure"],
                    actual_arrival=row["actual_arrival"],
                    status=row["status"],
                    aircraft_code=row["aircraft_code"],
                    departure_airport=row["departure_airport"],
                    departure_city=row["departure_city"],
                    arrival_airport=row["arrival_airport"],
                    arrival_city=row["arrival_city"],
                    boarding_pass=boarding_pass
                )
                tickets_map[ticket_no]["flights"].append(flight_segment)

        return BookingDetails(**booking_data)
