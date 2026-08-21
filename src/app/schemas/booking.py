from __future__ import annotations

from enum import Enum
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputClassification(BaseModel):
    intent: Literal["Booking", "Unknown"]


class BookingOperation(str, Enum):
    GET = "get_booking"
    SEARCH = "search_bookings"
    SUMMARY = "booking_summary"
    CREATE = "create_booking"
    DELETE = "delete_booking"


class GuidanceReply(BaseModel):
    message: str
    addressed_issues: list[str]


BookRef = Annotated[
    str,
    Field(
        min_length=6,
        max_length=6,
        description=(
            "Six-character booking reference, for example 'AB12CD'. "
            "Only populate this when the user explicitly provides it. "
            "Never invent or guess a booking reference."
        ),
    ),
]

Money = Annotated[
    Decimal,
    Field(
        ge=0,
        max_digits=10,
        decimal_places=2,
        description=(
            "Booking total amount as a non-negative decimal with up to two "
            "fractional digits. Only populate it when explicitly supplied."
        ),
    ),
]


class BookingRequest(BaseModel):
    """
    Structured booking information extracted from the user's message.

    All fields except `operation` are optional deliberately. The LLM must not
    fabricate missing booking references, dates, or amounts. Missing data is
    collected later through a follow-up question.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
    )

    operation: BookingOperation | None = Field(
        default=None,
        description=(
            "The booking action requested by the user. "
            # "Use get_booking, search_bookings, booking_summary, "
            # "create_booking, or delete_booking. "
            "Leave null if the user's intended action is unclear."
        ),
    )

    book_ref: BookRef | None = Field(
        default=None,
        description=(
            "Booking reference used to retrieve or delete one booking, "
            "or to create a booking if the user provides it."
        ),
    )

    book_date: datetime | None = Field(
        default=None,
        description=(
            "Exact booking date/time. Use for creating a booking or searching "
            "for bookings on one specific date. Preserve timezone information "
            "when the user provides it."
        ),
    )

    date_from: datetime | None = Field(
        default=None,
        description=(
            "Inclusive beginning of a date range. Use for booking searches "
            "or revenue/booking-count summaries."
        ),
    )

    date_to: datetime | None = Field(
        default=None,
        description=(
            "Inclusive end of a date range. Use for booking searches "
            "or revenue/booking-count summaries."
        ),
    )

    total_amount: Money | None = Field(
        default=None,
        description=(
            "Total monetary amount for a new booking. "
            "Required only when creating a booking."
        ),
    )

    @model_validator(mode="after")
    def validate_request(self) -> "BookingRequest":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to must be greater than or equal to date_from")
        if not self.operation:
            return self
        required_fields = {
            # BookingOperation.SEARCH: ["book_date",],
            BookingOperation.DELETE: ["book_ref"],
            BookingOperation.GET: ["book_ref"],
            BookingOperation.SUMMARY: ["date_from", "date_to"],
            BookingOperation.CREATE: ["book_ref", "book_date", "total_amount"],
        }

        if self.operation in required_fields:
            missing = [
                field_name
                for field_name in required_fields[self.operation]
                if getattr(self, field_name) is None
            ]
            if missing:
                raise ValueError(
                    f"Missing required fields for {self.operation}: {', '.join(missing)}"
                )

        return self


# ============================================================
# Response models
# ============================================================


class BoardingPassInfo(BaseModel):
    boarding_no: int
    seat_no: str


class FlightInfo(BaseModel):
    flight_id: int
    flight_no: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    departure_airport: str
    arrival_airport: str
    departure_city: Any | None = None
    arrival_city: Any | None = None
    status: str
    aircraft_code: str
    actual_departure: datetime | None = None
    actual_arrival: datetime | None = None
    fare_conditions: str
    amount: Decimal
    boarding_pass: BoardingPassInfo | None = None


class TicketInfo(BaseModel):
    ticket_no: str
    passenger_id: str
    flights: list[FlightInfo] = Field(default_factory=list)


class BookingDetails(BaseModel):
    book_ref: str
    book_date: datetime
    total_amount: Decimal
    tickets: list[TicketInfo] = Field(default_factory=list)

    # Pagination metadata makes partial results explicit.
    ticket_limit: int
    ticket_offset: int
    flight_limit: int
    flight_offset: int


class BookingSummary(BaseModel):
    book_ref: str
    book_date: datetime
    total_amount: Decimal


class BookingSearchResult(BaseModel):
    items: list[BookingSummary]
    limit: int
    offset: int


class BookingStatistics(BaseModel):
    start_date: datetime
    end_date: datetime
    booking_count: int
    total_amount: Decimal

    @property
    def revenue(self) -> Decimal:
        """Alias for total_amount."""
        return self.total_amount


class DependencyCounts(BaseModel):
    tickets: int = 0
    ticket_flights: int = 0
    boarding_passes: int = 0

    @property
    def has_dependencies(self) -> bool:
        return any(
            (
                self.tickets,
                self.ticket_flights,
                self.boarding_passes,
            )
        )


class DeleteBookingResult(BaseModel):
    book_ref: str
    deleted: bool
    dependencies: DependencyCounts
    message: str
