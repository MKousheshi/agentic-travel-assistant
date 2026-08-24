from datetime import date
from decimal import Decimal
from typing import Any, Optional
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session

from app.capabilities.flight import services

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_json_serializable(value: Any) -> Any:
    """Recursively convert Decimal, date/datetime, and other non-JSON types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _make_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_serializable(item) for item in value]
    return value


# ===========================================================================
# 1. Retrieve flights by ID or flight number
# ===========================================================================


class GetFlightsInput(BaseModel):
    flight_id: Optional[int] = Field(
        None,
        description="Unique integer ID of the flight.",
    )
    flight_no: Optional[str] = Field(
        None,
        min_length=1,
        max_length=6,
        description="Flight number (e.g. 'PG0001', up to 6 characters).",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of flights to return when querying by flight_no.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of records to skip for pagination when querying by flight_no.",
    )

    @model_validator(mode="after")
    def check_at_least_one_identifier(self):
        if self.flight_id is None and not self.flight_no:
            raise ValueError("Must provide either 'flight_id' or 'flight_no'.")
        return self


@tool(args_schema=GetFlightsInput)
def get_flights(
    config: RunnableConfig,
    flight_id: Optional[int] = None,
    flight_no: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Retrieve flight details by either flight_id (single) or flight_no (list)."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError("Session is required in RunnableConfig for get_flights.")

    if flight_id is not None:
        flight = services.get_flight_by_id(session, flight_id)
        if flight is None:
            return {
                "found": False,
                "flight": None,
                "message": f"No flight found with flight_id '{flight_id}'.",
            }
        return {
            "found": True,
            "flight": flight.model_dump(),
            "message": f"Flight {flight_id} retrieved successfully.",
        }

    flights = services.get_flights_by_flight_no(
        session,
        flight_no=flight_no,
        limit=limit,
        offset=offset,
    )
    return {
        "found": len(flights) > 0,
        "count": len(flights),
        "flights": [f.model_dump() for f in flights],
        "message": (
            f"Found {len(flights)} flight(s) for flight_no '{flight_no}'."
            if flights
            else f"No flights found for flight_no '{flight_no}'."
        ),
    }


# ===========================================================================
# 2. Find flights between departure and arrival airports
# ===========================================================================


class FindFlightsBetweenAirportsInput(BaseModel):
    departure_airport: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="3-character IATA/airport code of departure airport (e.g. 'DME').",
    )
    arrival_airport: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="3-character IATA/airport code of arrival airport (e.g. 'LED').",
    )
    scheduled_date: Optional[date] = Field(
        None,
        description="Optional filter by scheduled departure date (YYYY-MM-DD).",
    )
    status: Optional[str] = Field(
        None,
        max_length=20,
        description="Optional filter by flight status (e.g., 'Scheduled', 'On Time', 'Delayed', 'Departed', 'Arrived', 'Cancelled').",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Max records to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    )


@tool(args_schema=FindFlightsBetweenAirportsInput)
def find_flights_between_airports(
    config: RunnableConfig,
    departure_airport: str,
    arrival_airport: str,
    scheduled_date: Optional[date] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Find flights between departure and arrival airports with optional date and status filters."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for find_flights_between_airports."
        )

    flights = services.find_flights_between_airports(
        session=session,
        departure_airport=departure_airport,
        arrival_airport=arrival_airport,
        scheduled_date=scheduled_date,
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "found": len(flights) > 0,
        "count": len(flights),
        "flights": [f.model_dump() for f in flights],
        "message": (
            f"Found {len(flights)} flight(s) from {departure_airport} to {arrival_airport}."
            if flights
            else f"No flights found from {departure_airport} to {arrival_airport}."
        ),
    }


# ===========================================================================
# 3. Show flight status
# ===========================================================================


class GetFlightStatusInput(BaseModel):
    flight_id: int = Field(
        ...,
        description="Unique integer ID of the flight to check status for.",
    )


@tool(args_schema=GetFlightStatusInput)
def get_flight_status(
    flight_id: int,
    config: RunnableConfig,
) -> dict:
    """Show detailed operational status for a specific flight."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError("Session is required in RunnableConfig for get_flight_status.")

    try:
        status_data = services.get_flight_status(session, flight_id=flight_id)
        return {
            "found": True,
            "flight_status": _make_json_serializable(status_data),
            "message": f"Status for flight {flight_id} retrieved successfully.",
        }
    except ValueError as exc:
        return {
            "found": False,
            "flight_status": None,
            "message": str(exc),
        }


# ===========================================================================
# 4. Analyze actual_departure and actual_arrival based on status
# ===========================================================================


class AnalyzeFlightScheduleInput(BaseModel):
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of flight schedule comparisons to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    )


@tool(args_schema=AnalyzeFlightScheduleInput)
def analyze_flight_schedules(
    config: RunnableConfig,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Analyze actual vs scheduled departures and arrivals across flights based on status."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for analyze_flight_schedules."
        )

    try:
        analysis = services.get_flight_status(
            session=session,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "analysis": _make_json_serializable(analysis),
            "message": "Flight schedule analysis completed successfully.",
        }
    except Exception as exc:
        return {
            "success": False,
            "analysis": None,
            "message": str(exc),
        }


# ===========================================================================
# 5. Find the aircraft associated with a flight or aircraft_code
# ===========================================================================


class GetAircraftInput(BaseModel):
    flight_id: Optional[int] = Field(
        None,
        description="Unique integer ID of the flight to get the assigned aircraft for.",
    )
    aircraft_code: Optional[str] = Field(
        None,
        min_length=3,
        max_length=3,
        description="3-character aircraft code (e.g. '773', 'SU9') to list assigned flights.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Max flight records to return when querying by aircraft_code.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Offset for pagination when querying by aircraft_code.",
    )

    @model_validator(mode="after")
    def check_at_least_one_identifier(self):
        if self.flight_id is None and not self.aircraft_code:
            raise ValueError("Must provide either 'flight_id' or 'aircraft_code'.")
        return self


@tool(args_schema=GetAircraftInput)
def get_aircraft_for_flight(
    config: RunnableConfig,
    flight_id: Optional[int] = None,
    aircraft_code: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Find the aircraft assigned to a flight, or list flights operated by an aircraft code."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_aircraft_for_flight."
        )

    if flight_id is not None:
        aircraft = services.get_aircraft_for_flight(session, flight_id=flight_id)
        if aircraft is None:
            return {
                "found": False,
                "aircraft": None,
                "message": f"No aircraft found for flight_id '{flight_id}'.",
            }
        return {
            "found": True,
            "aircraft": aircraft.model_dump(),
            "message": f"Aircraft for flight {flight_id} retrieved successfully.",
        }

    flights = services.get_flights_by_aircraft_code(
        session,
        aircraft_code=aircraft_code,
        limit=limit,
        offset=offset,
    )
    return {
        "found": len(flights) > 0,
        "count": len(flights),
        "flights": [f.model_dump() for f in flights],
        "message": (
            f"Found {len(flights)} flight(s) operated by aircraft '{aircraft_code}'."
            if flights
            else f"No flights found operated by aircraft '{aircraft_code}'."
        ),
    }


# ===========================================================================
# 6. Analyze high-traffic routes and their associated revenue
# ===========================================================================


class AnalyzeHighTrafficRoutesInput(BaseModel):
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of routes to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of route records to skip for pagination.",
    )


@tool(args_schema=AnalyzeHighTrafficRoutesInput)
def analyze_high_traffic_routes(
    config: RunnableConfig,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Analyze high-traffic routes and calculate their traffic volume and associated revenue."""

    session: Optional[Session] = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for analyze_high_traffic_routes."
        )

    try:
        report = services.analyze_high_traffic_routes(
            session=session,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "data": _make_json_serializable(report),
            "message": "High-traffic routes and revenue analyzed successfully.",
        }
    except Exception as exc:
        return {
            "success": False,
            "data": None,
            "message": str(exc),
        }


flight_tools = [
    analyze_high_traffic_routes,
    get_flights,
    find_flights_between_airports,
    get_flight_status,
    analyze_flight_schedules,
    get_aircraft_for_flight,
]
