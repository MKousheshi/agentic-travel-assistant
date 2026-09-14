# services/weather/openweather.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .exceptions import (
    WeatherAPIError,
    WeatherAPIInvalidLocationError,
    WeatherAPIInvalidResponseError,
    WeatherAPIRateLimitError,
    WeatherAPITimeoutError,
)


@dataclass
class WeatherLookupResult:
    location_query: str
    temperature_c: float
    feels_like_c: float
    humidity: int
    pressure: int
    weather_main: str
    weather_description: str
    wind_speed: float
    city_name: str
    country: str | None
    raw: dict[str, Any]


class OpenWeatherMapClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openweathermap.org/data/2.5/weather",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def get_weather_by_city(self, city: str) -> WeatherLookupResult:
        if not city or not city.strip():
            raise WeatherAPIInvalidLocationError("City is empty or invalid.")

        params = {
            "q": city.strip(),
            "appid": self.api_key,
            "units": "metric",
        }
        return self._request(params=params, location_query=city.strip())

    def get_weather_by_coords(self, lat: float, lon: float) -> WeatherLookupResult:
        params = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": "metric",
        }
        return self._request(params=params, location_query=f"{lat},{lon}")

    def _request(
        self, params: dict[str, Any], location_query: str
    ) -> WeatherLookupResult:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(self.base_url, params=params)
        except httpx.TimeoutException as e:
            raise WeatherAPITimeoutError("Weather API request timed out.") from e
        except httpx.RequestError as e:
            raise WeatherAPIError(f"Weather API request failed: {e}") from e

        if response.status_code == 429:
            raise WeatherAPIRateLimitError("Weather API rate limit exceeded.")

        if response.status_code == 404:
            raise WeatherAPIInvalidLocationError(
                f"Weather location not found for query: {location_query}"
            )

        if response.status_code >= 500:
            raise WeatherAPIError(f"Weather API server error: {response.status_code}")

        if response.status_code != 200:
            raise WeatherAPIError(
                f"Unexpected weather API status: {response.status_code}"
            )

        try:
            payload = response.json()
        except Exception as e:
            raise WeatherAPIInvalidResponseError(
                "Weather API returned invalid JSON."
            ) from e

        return self._parse_payload(payload, location_query=location_query)

    def _parse_payload(
        self,
        payload: dict[str, Any],
        location_query: str,
    ) -> WeatherLookupResult:
        try:
            main = payload["main"]
            weather = payload["weather"][0]
            wind = payload.get("wind", {})
            city_name = payload["name"]
            sys_info = payload.get("sys", {})
        except (KeyError, IndexError, TypeError) as e:
            raise WeatherAPIInvalidResponseError(
                "Weather API response missing required fields."
            ) from e

        try:
            temperature_c = float(main["temp"])
            feels_like_c = float(main["feels_like"])
            humidity = int(main["humidity"])
            pressure = int(main["pressure"])
            weather_main = str(weather["main"])
            weather_description = str(weather["description"])
            wind_speed = float(wind.get("speed", 0.0))
            country = sys_info.get("country")
        except (KeyError, TypeError, ValueError) as e:
            raise WeatherAPIInvalidResponseError(
                "Weather API response has invalid field types."
            ) from e

        return WeatherLookupResult(
            location_query=location_query,
            temperature_c=temperature_c,
            feels_like_c=feels_like_c,
            humidity=humidity,
            pressure=pressure,
            weather_main=weather_main,
            weather_description=weather_description,
            wind_speed=wind_speed,
            city_name=city_name,
            country=country,
            raw=payload,
        )
