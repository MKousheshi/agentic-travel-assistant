# services/weather/utils.py

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_airport_coordinates(value: str) -> tuple[float, float] | None:
    if not value:
        return None

    s = value.strip()

    # JSON object
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    except (ValueError, TypeError):
        logger.debug("Coordinates value is not a JSON lat/lon object: %r", s)

    # "lat,lon" or "[lat, lon]"
    numbers = re.findall(r"-?\d+(?:\.\d+)?", s)
    if len(numbers) >= 2:
        return float(numbers[0]), float(numbers[1])

    return None
