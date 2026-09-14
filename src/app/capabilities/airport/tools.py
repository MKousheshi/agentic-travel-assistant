from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.capabilities.airport import services
from app.db.schemas import Flight

# ===========================================================================
# 1. Search for an airport by airport_code
# ===========================================================================


class GetAirportByCodeInput(BaseModel):
    airport_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Unique 3-character IATA/airport code (e.g., 'DME', 'LED', 'SVO').",
    )


@tool(args_schema=GetAirportByCodeInput)
def get_airport_by_code(
    airport_code: str,
    config: RunnableConfig,
) -> dict:
    """Search and retrieve airport entity by its unique 3-character airport code."""

    session: Session | None = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_airport_by_code."
        )

    airport = services.get_airport_by_code(
        session=session, airport_code=airport_code.upper()
    )

    if airport is None:
        return {
            "found": False,
            "airport": None,
            "message": f"No airport found with code '{airport_code}'.",
        }

    return {
        "found": True,
        "airport": airport.model_dump(),
        "message": f"Airport '{airport_code}' retrieved successfully.",
    }


# ===========================================================================
# 2. Search for an airport based on city
# ===========================================================================


class SearchAirportsByCityInput(BaseModel):
    city: str = Field(
        ...,
        min_length=1,
        description="Name of the city to search airports for (e.g., 'Moscow', 'St. Petersburg').",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of airports to return.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    )


@tool(args_schema=SearchAirportsByCityInput)
def search_airports_by_city(
    config: RunnableConfig,
    city: str,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search for airports located in a specific city."""

    session: Session | None = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for search_airports_by_city."
        )

    airports = services.search_airports_by_city(
        session=session,
        city=city,
        limit=limit,
        offset=offset,
    )

    return {
        "found": len(airports) > 0,
        "count": len(airports),
        "airports": [a.model_dump() for a in airports],
        "message": (
            f"Found {len(airports)} airport(s) in city '{city}'."
            if airports
            else f"No airports found in city '{city}'."
        ),
    }


# ===========================================================================
# 3. Display airport_name, city, coordinates, and timezone
# ===========================================================================


class GetAirportDetailsInput(BaseModel):
    airport_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="3-character airport code (e.g., 'DME').",
    )
    lang: str = Field(
        "en",
        description="Language code for localized names (e.g., 'en', 'ru'). Defaults to 'en'.",
    )


@tool(args_schema=GetAirportDetailsInput)
def get_airport_details(
    config: RunnableConfig,
    airport_code: str,
    lang: str = "en",
) -> dict:
    """Display localized airport details including airport_name, city, coordinates, and timezone."""

    session: Session | None = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_airport_details."
        )

    try:
        details = services.get_airport_details(
            session=session,
            airport_code=airport_code.upper(),
            lang=lang,
        )
        return {
            "found": True,
            "details": details,
            "message": f"Airport details for '{airport_code}' retrieved successfully.",
        }
    except ValueError as exc:
        return {
            "found": False,
            "details": None,
            "message": str(exc),
        }


# ===========================================================================
# 4. Find incoming and outgoing flights of an airport
# ===========================================================================


class GetAirportFlightsInput(BaseModel):
    airport_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="3-character airport code (e.g., 'DME').",
    )
    direction: Literal["incoming", "outgoing", "both"] = Field(
        "both",
        description="Direction of flights to fetch: 'incoming' (arrivals), 'outgoing' (departures), or 'both'.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum number of flights to return per direction.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of flight records to skip for pagination.",
    )


@tool(args_schema=GetAirportFlightsInput)
def get_airport_flights(
    config: RunnableConfig,
    airport_code: str,
    direction: Literal["incoming", "outgoing", "both"] = "both",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Find incoming (arrivals) and/or outgoing (departures) flights for an airport."""

    session: Session | None = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for get_airport_flights."
        )

    airport_code_clean = airport_code.upper()
    incoming_flights: list[Flight] = []
    outgoing_flights: list[Flight] = []

    if direction in ("incoming", "both"):
        incoming_flights = services.get_incoming_flights(
            session=session,
            airport_code=airport_code_clean,
            limit=limit,
            offset=offset,
        )

    if direction in ("outgoing", "both"):
        outgoing_flights = services.get_outgoing_flights(
            session=session,
            airport_code=airport_code_clean,
            limit=limit,
            offset=offset,
        )

    result_data: dict[str, Any] = {}
    if direction in ("incoming", "both"):
        result_data["incoming"] = [f.model_dump() for f in incoming_flights]
    if direction in ("outgoing", "both"):
        result_data["outgoing"] = [f.model_dump() for f in outgoing_flights]

    total_count = len(incoming_flights) + len(outgoing_flights)
    return {
        "found": total_count > 0,
        "airport_code": airport_code_clean,
        "direction": direction,
        "total_returned": total_count,
        "flights": result_data,
        "message": (
            f"Retrieved {len(incoming_flights)} arrival(s) and {len(outgoing_flights)} departure(s) for '{airport_code_clean}'."
            if total_count > 0
            else f"No flights found for airport '{airport_code_clean}' with direction '{direction}'."
        ),
    }


# ===========================================================================
# 5. Resolve destination/origin city or location for Weather capability
# ===========================================================================


class ResolveWeatherLocationInput(BaseModel):
    airport_code: str | None = Field(
        None,
        min_length=3,
        max_length=3,
        description="3-character airport code (e.g. 'DME') to resolve location coordinates/city.",
    )
    flight_id: int | None = Field(
        None,
        description="Flight ID to resolve origin and destination locations for weather lookup.",
    )
    lang: str = Field(
        "en",
        description="Language code for resolved location names (e.g., 'en', 'ru'). Defaults to 'en'.",
    )


@tool(args_schema=ResolveWeatherLocationInput)
def resolve_weather_location(
    config: RunnableConfig,
    airport_code: str | None = None,
    flight_id: int | None = None,
    lang: str = "en",
) -> dict:
    """Resolve geographic location, city, and coordinates from an airport code or flight ID for weather lookup."""

    session: Session | None = (
        config.get("configurable", {}).get("session", None) if config else None
    )
    if not session:
        raise ValueError(
            "Session is required in RunnableConfig for resolve_weather_location."
        )

    if airport_code is None and flight_id is None:
        return {
            "resolved": False,
            "location_data": None,
            "message": "Must provide either 'airport_code' or 'flight_id' to resolve weather location.",
        }

    try:
        if flight_id is not None:
            location_data = services.resolve_flight_origin_destination(
                session=session,
                flight_id=flight_id,
                lang=lang,
            )
            return {
                "resolved": True,
                "type": "flight",
                "flight_id": flight_id,
                "location_data": location_data,
                "message": f"Resolved origin and destination weather locations for flight {flight_id}.",
            }

        location_data = services.resolve_weather_location_by_airport(
            session=session,
            airport_code=airport_code.upper(),
            lang=lang,
        )
        return {
            "resolved": True,
            "type": "airport",
            "airport_code": airport_code.upper(),
            "location_data": location_data,
            "message": f"Resolved weather location for airport '{airport_code.upper()}'.",
        }

    except ValueError as exc:
        return {
            "resolved": False,
            "location_data": None,
            "message": str(exc),
        }


airport_tools = [
    get_airport_by_code,
    search_airports_by_city,
    get_airport_details,
    get_airport_flights,
    resolve_weather_location,
]
