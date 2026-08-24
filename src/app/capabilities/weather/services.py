# services/weather/service.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Literal

from sqlmodel import Session, select

from app.db.schemas import Flight, Airport 
from .openweather import OpenWeatherMapClient, WeatherLookupResult
from .exceptions import (
    FlightNotFoundError,
    AirportNotFoundError,
    WeatherAPIInvalidLocationError,
)
from .utils import parse_airport_coordinates


WeatherTarget = Literal["origin", "destination"]


@dataclass
class FlightWeatherResult:
    flight_id: int
    flight_no: str
    status: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    departure_airport: str
    arrival_airport: str
    target: WeatherTarget

    airport_code: str
    airport_name: Optional[dict[str, Any]]
    city: Optional[dict[str, Any]]
    location_query: str

    weather: dict[str, Any]


class WeatherService:
    def __init__(self, session: Session, weather_client: OpenWeatherMapClient) -> None:
        self.session = session
        self.weather_client = weather_client

    # -------------------------
    # Public flight-based APIs
    # -------------------------

    def get_current_weather_for_flight_origin(self, flight_id: int) -> FlightWeatherResult:
        flight = self._get_flight_by_id(flight_id)
        airport = self._get_airport_by_code(flight.departure_airport)

        return self._build_flight_weather_result(
            flight=flight,
            airport=airport,
            target="origin",
        )

    def get_current_weather_for_flight_destination(self, flight_id: int) -> FlightWeatherResult:
        flight = self._get_flight_by_id(flight_id)
        airport = self._get_airport_by_code(flight.arrival_airport)

        return self._build_flight_weather_result(
            flight=flight,
            airport=airport,
            target="destination",
        )

    # -------------------------
    # Pagination-friendly list API
    # -------------------------

    def list_flight_weather(
        self,
        target: WeatherTarget,
        limit: int = 20,
        offset: int = 0,
    ) -> list[FlightWeatherResult]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        stmt = select(Flight).offset(offset).limit(limit)
        flights = self.session.exec(stmt).all()

        results: list[FlightWeatherResult] = []
        for flight in flights:
            airport = self._get_airport_by_code(
                flight.departure_airport if target == "origin" else flight.arrival_airport
            )
            results.append(
                self._build_flight_weather_result(
                    flight=flight,
                    airport=airport,
                    target=target,
                )
            )
        return results

    # -------------------------
    # Internal helpers
    # -------------------------

    def _get_flight_by_id(self, flight_id: int) -> Flight:
        flight = self.session.get(Flight, flight_id)
        if not flight:
            raise FlightNotFoundError(f"Flight {flight_id} not found.")
        return flight

    def _get_airport_by_code(self, airport_code: str) -> Airport:
        airport = self.session.get(Airport, airport_code)
        if not airport:
            raise AirportNotFoundError(f"Airport '{airport_code}' not found.")
        return airport

    def _build_flight_weather_result(
        self,
        flight: Flight,
        airport: Airport,
        target: WeatherTarget,
    ) -> FlightWeatherResult:
        location_query, weather = self._resolve_and_fetch_weather(airport)

        return FlightWeatherResult(
            flight_id=flight.flight_id,
            flight_no=flight.flight_no,
            status=flight.status,
            scheduled_departure=flight.scheduled_departure,
            scheduled_arrival=flight.scheduled_arrival,
            departure_airport=flight.departure_airport,
            arrival_airport=flight.arrival_airport,
            target=target,
            airport_code=airport.airport_code,
            airport_name=airport.airport_name,
            city=airport.city,
            location_query=location_query,
            weather={
                "temperature_c": weather.temperature_c,
                "feels_like_c": weather.feels_like_c,
                "humidity": weather.humidity,
                "pressure": weather.pressure,
                "weather_main": weather.weather_main,
                "weather_description": weather.weather_description,
                "wind_speed": weather.wind_speed,
                "city_name": weather.city_name,
                "country": weather.country,
            },
        )

    def _resolve_and_fetch_weather(self, airport: Airport) -> tuple[str, WeatherLookupResult]:
        # 1) Prefer coordinates if valid
        coords = parse_airport_coordinates(airport.coordinates)
        if coords is not None:
            lat, lon = coords
            weather = self.weather_client.get_weather_by_coords(lat=lat, lon=lon)
            return f"{lat},{lon}", weather

        # 2) Fall back to city name from airport.city JSON
        city_name = self._extract_city_name(airport.city)
        if city_name:
            weather = self.weather_client.get_weather_by_city(city_name)
            return city_name, weather

        # 3) No location information available
        raise WeatherAPIInvalidLocationError(
            f"Airport '{airport.airport_code}' has no usable coordinates or city."
        )

    def _extract_city_name(self, city_value: Optional[dict[str, Any]]) -> Optional[str]:
        if not city_value:
            return None

        # Handle common shapes:
        # {"en": "Tehran"}
        # {"name": "Tehran"}
        # {"fa": "تهران", "en": "Tehran"}
        for key in ("en", "name", "city", "title"):
            value = city_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        # fallback: first string value
        for value in city_value.values():
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None
