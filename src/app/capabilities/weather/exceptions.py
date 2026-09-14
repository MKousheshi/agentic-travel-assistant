# services/weather/exceptions.py


class WeatherServiceError(Exception):
    """Base error for weather service."""


class FlightNotFoundError(WeatherServiceError):
    """Raised when flight does not exist."""


class AirportNotFoundError(WeatherServiceError):
    """Raised when airport does not exist."""


class WeatherAPIError(WeatherServiceError):
    """Base error for upstream weather API problems."""


class WeatherAPITimeoutError(WeatherAPIError):
    """Raised when OpenWeatherMap times out."""


class WeatherAPIRateLimitError(WeatherAPIError):
    """Raised when OpenWeatherMap rate limits the request."""


class WeatherAPIInvalidLocationError(WeatherAPIError):
    """Raised when city/location is invalid or not resolvable."""


class WeatherAPIInvalidResponseError(WeatherAPIError):
    """Raised when upstream response is missing expected fields or malformed."""
