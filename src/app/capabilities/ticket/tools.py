from decimal import Decimal

from langchain_core.tools import tool
from langgraph.graph.state import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.capabilities.ticket import services
from app.capabilities.ticket.services import TicketDeletionError
from app.models import Confirmation


class GetTicketInput(BaseModel):
    ticket_no: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="Unique ticket number, must be exactly 13 characters alphanumeric.",
    )


@tool(args_schema=GetTicketInput)
def get_ticket_by_number(ticket_no: str, config: RunnableConfig) -> dict:
    """Retrieve full details for a single ticket by its ticket number, including relations."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_ticket_by_number."
        )

    ticket = services.get_ticket_by_number(session, ticket_no)

    if ticket is None:
        return {
            "found": False,
            "ticket": None,
            "message": f"No ticket was found for ticket number '{ticket_no}'.",
        }

    return {
        "found": True,
        "ticket": ticket.model_dump(),
        "message": "Ticket retrieved successfully.",
    }


class GetTicketsByPassengerInput(BaseModel):
    passenger_id: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unique passenger identifier.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of tickets to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    )


@tool(args_schema=GetTicketsByPassengerInput)
def get_tickets_by_passenger_id(
    config: RunnableConfig,
    passenger_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search and retrieve tickets by passenger ID with pagination."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_tickets_by_passenger_id."
        )

    tickets = services.get_tickets_by_passenger_id(
        session,
        passenger_id,
        limit=limit,
        offset=offset,
    )

    return {
        "found": len(tickets) > 0,
        "count": len(tickets),
        "tickets": [ticket.model_dump() for ticket in tickets],
        "message": (
            f"Found {len(tickets)} ticket(s) for passenger_id '{passenger_id}'."
            if tickets
            else f"No tickets were found for passenger_id '{passenger_id}'."
        ),
    }


class GetFlightsByTicketInput(BaseModel):
    ticket_no: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="Unique ticket number, must be exactly 13 characters.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of flights to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of flights to skip for pagination.",
    )


@tool(args_schema=GetFlightsByTicketInput)
def get_flights_by_ticket_no(
    ticket_no: str,
    limit: int,
    offset: int,
    config: RunnableConfig,
) -> dict:
    """Find flights associated with a ticket through ticket_flights."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_flights_by_ticket_no."
        )

    flights = services.get_flights_by_ticket_no(
        session,
        ticket_no,
        limit=limit,
        offset=offset,
    )

    return {
        "found": len(flights) > 0,
        "count": len(flights),
        "flights": [flight.model_dump() for flight in flights],
        "message": (
            f"Found {len(flights)} flight(s) associated with ticket '{ticket_no}'."
            if flights
            else f"No flights were found for ticket '{ticket_no}'."
        ),
    }


class CreateTicketInput(BaseModel):
    book_ref: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Unique 6-character booking reference. Must already exist.",
    )
    ticket_no: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="Unique 13-character ticket number. Must not already exist.",
    )
    passenger_id: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Passenger identifier (up to 20 characters).",
    )


@tool(args_schema=CreateTicketInput)
def create_ticket(
    book_ref: str,
    ticket_no: str,
    passenger_id: str,
    config: RunnableConfig,
) -> dict:
    """Create a new ticket under an existing booking reference."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError("Session is required in RunnableConfig for create_ticket.")

    try:
        new_ticket = services.create_ticket(
            session=session,
            book_ref=book_ref,
            ticket_no=ticket_no,
            passenger_id=passenger_id,
        )
        return {
            "success": True,
            "ticket": new_ticket.model_dump(),
            "message": f"Ticket '{ticket_no}' created successfully for booking '{book_ref}'.",
        }
    except ValueError as exc:
        return {
            "success": False,
            "ticket": None,
            "message": str(exc),
        }


class DeleteTicketInput(BaseModel):
    ticket_no: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="Unique 13-character ticket number to delete.",
    )


@tool(args_schema=DeleteTicketInput)
def delete_ticket_with_dependency_check(
    ticket_no: str,
    config: RunnableConfig,
) -> dict:
    """Check dependencies and delete a ticket if no blocking boarding passes exist."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError("Session is required in RunnableConfig for delete_ticket.")

    try:
        # Step 1: Pre-deletion dependency impact check
        effect = services.get_ticket_deletion_effect(session, ticket_no)

        if effect.get("deletion_blocked", False):
            blocking = effect.get("blocking_dependencies", [])
            return {
                "success": False,
                "deleted": False,
                "deletion_effect": effect,
                "message": (
                    f"Deletion blocked for ticket '{ticket_no}'. "
                    f"Boarding pass(es) already issued: {', '.join(blocking)}."
                ),
            }

    except (ValueError, SQLAlchemyError) as exc:
        return {
            "success": False,
            "deleted": False,
            "message": str(exc),
        }
    confirmation = Confirmation(message="Proceed to delete booking?", data=effect)
    result = interrupt(confirmation)
    confirmation = Confirmation.model_validate(result)
    if confirmation.confirmed:
        try:
            # Step 2: Perform deletion
            result = services.delete_ticket(session, ticket_no)
            return {
                "success": True,
                "deleted": True,
                "result": result,
                "deletion_effect": effect,
                "message": f"Ticket '{ticket_no}' and its flight segments deleted successfully.",
            }

        except (ValueError, TicketDeletionError, SQLAlchemyError) as exc:
            return {
                "success": False,
                "deleted": False,
                "message": str(exc),
            }
    return {
        "success": True,
        "deleted": False,
        "message": "User aborted deletion.",
    }


class AnalyzeTicketFaresInput(BaseModel):
    ticket_no: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="Unique ticket number, must be exactly 13 characters.",
    )
    segment_limit: int = Field(
        100,
        ge=1,
        description="Maximum number of flight segments to include in the detailed result.",
    )
    segment_offset: int = Field(
        0,
        ge=0,
        description="Number of flight segments to skip in the detailed result.",
    )


@tool(args_schema=AnalyzeTicketFaresInput)
def analyze_ticket_fares(
    config: RunnableConfig,
    ticket_no: str,
    segment_limit: int = 100,
    segment_offset: int = 0,
) -> dict:
    """Analyze fare conditions and amounts across a ticket."""

    session: Session | None = config.get("configurable", {}).get("session", None)
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for analyze_ticket_fares."
        )

    try:
        fare_analysis = services.analyze_ticket_fares(
            session,
            ticket_no,
            segment_limit=segment_limit,
            segment_offset=segment_offset,
        )

        # Convert Decimal values and any nested Decimal values into JSON-safe values.
        fare_analysis = _make_json_serializable(fare_analysis)

        return {
            "found": True,
            "analysis": fare_analysis,
            "message": f"Fare analysis completed successfully for ticket '{ticket_no}'.",
        }

    except ValueError as exc:
        return {
            "found": False,
            "analysis": None,
            "message": str(exc),
        }


def _make_json_serializable(value):
    """Convert Decimal values recursively into JSON-serializable values."""

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, dict):
        return {key: _make_json_serializable(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_make_json_serializable(item) for item in value]

    if isinstance(value, tuple):
        return [_make_json_serializable(item) for item in value]

    return value


ticket_tools = [
    get_ticket_by_number,
    get_flights_by_ticket_no,
    get_tickets_by_passenger_id,
    create_ticket,
    delete_ticket_with_dependency_check,
    analyze_ticket_fares,
]
