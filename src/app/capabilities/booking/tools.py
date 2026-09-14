from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal

from langchain_core.tools import tool
from langgraph.graph.state import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session

from app.capabilities.booking import services
from app.models import Confirmation

# ─────────────────────────────────────────────
# 1. Retrieve a booking by reference
# ─────────────────────────────────────────────


class GetBookingInput(BaseModel):
    book_ref: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Unique booking reference, must be exactly 6 letters, alphanumeric",
    )


@tool(args_schema=GetBookingInput)
def get_booking_by_ref(book_ref: str, config: RunnableConfig) -> dict:
    """Retrieve complete booking information using its booking reference."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_booking_by_ref."
        )
    booking = services.get_booking_by_ref(session, book_ref)

    if booking is None:
        return {
            "found": False,
            "booking": None,
            "message": f"No booking was found for reference '{book_ref}'.",
        }

    return {
        "found": True,
        "booking": booking.model_dump(),
        "message": "Booking retrieved successfully.",
    }


# ─────────────────────────────────────────────
# 2. Search by one date or a date range
# ─────────────────────────────────────────────


class SearchBookingsInput(BaseModel):
    date_book: date | None = Field(
        default=None,
        description="Exact booking date in YYYY-MM-DD format.",
    )
    date_from: date | None = Field(
        default=None,
        description="Start date of the search range in YYYY-MM-DD format.",
    )
    date_to: date | None = Field(
        default=None,
        description="End date of the search range in YYYY-MM-DD format.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Maximum number of booking records to return.",
    )

    @model_validator(mode="after")
    def validate_dates(self):
        # Exact-date search cannot be mixed with range search.
        if self.date_book and (self.date_from or self.date_to):
            raise ValueError(
                "Use date_book for an exact-date search, or date_from/date_to "
                "for a range search—not both."
            )

        if not self.date_book and not self.date_from and not self.date_to:
            raise ValueError(
                "Provide at least one of: date_book, date_from, or date_to."
            )

        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be earlier than or equal to date_to.")

        return self


def format_validation_error(error: Exception) -> str:
    """
    Converts LangChain/Pydantic validation failures into a useful tool response.
    """
    return f"Invalid search_bookings input: {error}"


@tool(args_schema=SearchBookingsInput)
def search_bookings(
    config: RunnableConfig,
    date_book: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 10,
) -> dict:
    """
    Search bookings for one exact date or within an inclusive date range.

    Use either:
    - date_book: an exact booking date
    - date_from and date_to: an inclusive date range
    """
    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError("Session is required in RunnableConfig for search_bookings.")

    if date_book is not None:
        bookings = services.search_bookings_for_date(
            session,
            booking_date=date_book,
            limit=limit,
        )
    else:
        bookings = services.search_bookings_by_date_range(
            session,
            start_date=(
                datetime.combine(date_from, datetime.min.time()) if date_from else None
            ),
            end_date=(
                datetime.combine(date_to, datetime.min.time()) if date_to else None
            ),
            limit=limit,
        )

    return {
        "count": len(bookings),
        "bookings": [booking.model_dump() for booking in bookings],
    }


# ─────────────────────────────────────────────
# 3. Calculate booking analytics for a time range
# ─────────────────────────────────────────────


class BookingAnalyticsInput(BaseModel):
    date_from: date = Field(
        ...,
        description="Start date of the reporting range in YYYY-MM-DD format.",
    )
    date_to: date = Field(
        ...,
        description="End date of the reporting range in YYYY-MM-DD format.",
    )

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be earlier than or equal to date_to.")
        return self


@tool(args_schema=BookingAnalyticsInput)
def calculate_booking_analytics(
    config: RunnableConfig,
    date_from: date,
    date_to: date,
) -> dict:
    """
    Calculate revenue (total_amount sum) and booking count for a date range.
    """
    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for calculate_booking_analytics."
        )

    summary = services.calculate_booking_revenue(
        session,
        start_date=datetime.combine(date_from, datetime.min.time()),
        end_date=datetime.combine(date_to, datetime.min.time()),
    )
    return {
        "count": summary.booking_count,
        "revenue": summary.total_revenue,
    }


# ─────────────────────────────────────────────
# 4. Create a booking
# ─────────────────────────────────────────────


class CreateBookingInput(BaseModel):
    book_ref: str = Field(
        ...,
        min_length=6,
        max_length=16,
        description="Unique reference code for the new booking. Must be 6 letters length. Alphanumeric",
    )
    total_amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Final total amount of the booking.",
    )
    book_date: date = Field(
        ...,
        description="Booking date in YYYY-MM-DD format.",
    )


@tool(args_schema=CreateBookingInput)
def create_booking(
    config: RunnableConfig,
    book_ref: str,
    total_amount: Decimal,
    book_date: date,
) -> dict:
    """
    Create a new booking with a unique book_ref, total_amount, and book_date.
    """
    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError("Session is required in RunnableConfig for create_booking.")

    try:
        booking = services.create_booking(
            session,
            book_ref=book_ref,
            book_date=datetime.combine(book_date, datetime.min.time()),
            total_amount=total_amount,
        )
        return {
            "message": "Booking created successfully",
            "booking": booking.model_dump(),
        }
    except Exception as e:
        return {
            "message": f"Failed to create booking: {e!s}",
            "booking": None,
        }


# ─────────────────────────────────────────────
# 5. Delete only when no dependencies exist
# ─────────────────────────────────────────────


class DeleteBookingInput(BaseModel):
    book_ref: str = Field(
        ...,
        min_length=1,
        description="Reference of the booking to delete.",
    )


@tool(args_schema=DeleteBookingInput)
def delete_booking_with_dependency_check(
    config: RunnableConfig,
    book_ref: str,
) -> dict:
    """
    Delete a booking after checking related and dependent records.

    The returned result always contains:
    - success
    - retryable
    - error_code
    - message
    """

    session: Session | None = config.get("configurable", {}).get("session")

    if session is None:
        return {
            "success": False,
            "retryable": False,
            "error_code": "MISSING_DATABASE_SESSION",
            "message": ("A database session is required to delete the booking."),
        }

    # This operation is read-only and is safe to repeat after interrupt
    # resumption.
    try:
        effect = services.preview_booking_deletion(
            session,
            book_ref=book_ref,
        )
    except Exception as e:
        return {
            "success": False,
            "retryable": False,
            "error_code": "BOOKING_PREVIEW_FAILED",
            "message": (
                f"Could not check whether booking '{book_ref}' can be deleted: {e}"
            ),
        }

    if not effect.booking_exists:
        return {
            # The requested end state is already satisfied.
            "success": True,
            "retryable": False,
            "error_code": "BOOKING_NOT_FOUND",
            "message": (
                f"Booking '{book_ref}' was not found. No deletion was necessary."
            ),
        }

    # Do not catch interrupt(). LangGraph needs the interrupt to propagate.
    confirmation = Confirmation(
        message="Proceed to delete booking?", data=asdict(effect)
    )
    result = interrupt(confirmation)
    confirmation = Confirmation.model_validate(result)

    if not confirmation.confirmed:
        return {
            "success": False,
            "retryable": False,
            "error_code": "USER_ABORTED",
            "message": "The user cancelled the booking deletion.",
        }

    services.delete_booking_by_ref(
        session,
        book_ref=book_ref,
    )

    return {
        "success": True,
        "message": "Booking deleted successfully.",
    }


booking_tools = [
    get_booking_by_ref,
    search_bookings,
    calculate_booking_analytics,
    create_booking,
    delete_booking_with_dependency_check,
]
