from dataclasses import asdict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.capabilities.weather.services import WeatherService

# ===========================================================================
# 1. Weather for Flight Origin
# ===========================================================================


class GetFlightOriginWeatherInput(BaseModel):
    flight_id: int = Field(
        ..., description="The ID of the flight to get origin weather for."
    )


@tool(args_schema=GetFlightOriginWeatherInput)
def get_flight_origin_weather(flight_id: int, config: RunnableConfig) -> dict:
    """Retrieve the current weather at a flight's origin airport."""

    # Extract dependencies from config
    session = config.get("configurable", {}).get("session")
    weather_client = config.get("configurable", {}).get("weather_client")

    if not session or not weather_client:
        raise ValueError("Session and weather_client are required in RunnableConfig.")

    service = WeatherService(session=session, weather_client=weather_client)

    try:
        result = service.get_current_weather_for_flight_origin(flight_id)
        return {
            "success": True,
            "weather": asdict(result),
            "message": f"Retrieved weather for flight {flight_id} origin.",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ===========================================================================
# 2. Weather for Flight Destination
# ===========================================================================


class GetFlightDestinationWeatherInput(BaseModel):
    flight_id: int = Field(
        ..., description="The ID of the flight to get destination weather for."
    )


@tool(args_schema=GetFlightDestinationWeatherInput)
def get_flight_destination_weather(flight_id: int, config: RunnableConfig) -> dict:
    """Retrieve the current weather at a flight's destination airport."""

    session = config.get("configurable", {}).get("session")
    weather_client = config.get("configurable", {}).get("weather_client")

    if not session or not weather_client:
        raise ValueError("Session and weather_client are required in RunnableConfig.")

    service = WeatherService(session=session, weather_client=weather_client)

    try:
        result = service.get_current_weather_for_flight_destination(flight_id)
        return {
            "success": True,
            "weather": asdict(result),
            "message": f"Retrieved weather for flight {flight_id} destination.",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ===========================================================================
# 3. Weather for specific Airport
# ===========================================================================


class GetAirportWeatherInput(BaseModel):
    airport_code: str = Field(
        ..., min_length=3, max_length=3, description="IATA code of the airport."
    )


@tool(args_schema=GetAirportWeatherInput)
def get_airport_weather(airport_code: str, config: RunnableConfig) -> dict:
    """Retrieve current weather at a specific airport."""

    session = config.get("configurable", {}).get("session")
    weather_client = config.get("configurable", {}).get("weather_client")

    if not session or not weather_client:
        raise ValueError("Session and weather_client are required in RunnableConfig.")

    service = WeatherService(session=session, weather_client=weather_client)

    try:
        result = service.get_current_weather_for_airport(airport_code)
        # Assuming WeatherLookupResult has a model_dump() or dict representation
        data = result if isinstance(result, dict) else result.model_dump()
        return {
            "success": True,
            "weather": data,
            "message": f"Retrieved weather for airport {airport_code}.",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


weather_tools = [
    get_flight_origin_weather,
    get_flight_destination_weather,
    get_airport_weather,
]
