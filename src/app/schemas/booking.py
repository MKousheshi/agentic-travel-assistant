from pydantic import BaseModel, Field

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, List, Any, List, Annotated

import re

from pydantic import BaseModel, Field, BeforeValidator


class BookingRequest(BaseModel):
    book_ref: Optional[str] = Field(default=None)


class InputClassification(BaseModel):
    intent: Literal["Booking", "Unknown"]


def parse_sqlite_datetime(value: Any) -> Any:
    """
    Normalizes timestamps with 2-digit timezone offsets (e.g. '+03' -> '+03:00')
    so that Pydantic/ISO-8601 parsers can process them seamlessly.
    """
    if isinstance(value, str):
        value = value.strip()
        # Match '+HH' or '-HH' at the end of the string and append ':00'
        value = re.sub(r"([+-]\d{2})$", r"\1:00", value)
    return value


SQLiteDateTime = Annotated[datetime, BeforeValidator(parse_sqlite_datetime)]


class BoardingPassInfo(BaseModel):
    boarding_no: Optional[int] = None
    seat_no: Optional[str] = None


class FlightSegment(BaseModel):
    flight_id: int
    flight_no: str
    fare_conditions: str
    amount: Decimal
    # Use SQLiteDateTime for all datetime fields
    scheduled_departure: SQLiteDateTime
    scheduled_arrival: SQLiteDateTime
    actual_departure: Optional[SQLiteDateTime] = None
    actual_arrival: Optional[SQLiteDateTime] = None
    status: str
    aircraft_code: str
    departure_airport: str
    departure_city: Optional[str] = None
    arrival_airport: str
    arrival_city: Optional[str] = None
    boarding_pass: Optional[BoardingPassInfo] = None


class TicketInfo(BaseModel):
    ticket_no: str
    passenger_id: str
    flights: List[FlightSegment] = Field(default_factory=list)


class BookingDetails(BaseModel):
    book_ref: str
    book_date: SQLiteDateTime  # Also applied here to prevent errors on book_date
    total_amount: Decimal
    tickets: List[TicketInfo] = Field(default_factory=list)
