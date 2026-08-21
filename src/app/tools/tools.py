from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


DateUnit = Literal["days", "weeks", "months", "years"]

SQLITE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


class ComputedDate(BaseModel):
    """
    A datetime result designed for SQLite storage.

    Store `utc_datetime` in a SQLite DATETIME column and `timezone`
    in a separate TEXT/VARCHAR column.
    """

    utc_datetime: str = Field(
        description=(
            "UTC datetime formatted for a SQLite DATETIME column. "
            "Format: YYYY-MM-DD HH:MM:SS.ffffff. "
            "Example: '2026-07-06 08:30:00.000000'."
        ),
        examples=["2026-07-06 08:30:00.000000"],
    )

    timezone: str = Field(
        description=(
            "Original UTC offset from from_date, stored separately in SQLite. "
            "Format: ±HH:MM. Example: '+03:30'."
        ),
        examples=["+03:30", "+00:00"],
    )

    local_datetime: str = Field(
        description=(
            "The calculated local datetime including its UTC offset, in ISO-8601 "
            "format. Useful for displaying the date to the user. "
            "Example: '2026-07-06T12:00:00+03:30'."
        ),
        examples=["2026-07-06T12:00:00+03:30"],
    )


def _parse_aware_datetime(value: str) -> datetime:
    """
    Accept ISO-8601 values with either a T or SQLite-style space separator.

    Valid examples:
    - 2026-07-01T12:00:00+03:30
    - 2026-07-01 12:00:00+03:30
    - 2026-07-01T08:30:00Z
    """
    normalized = value.strip()

    # Python's fromisoformat accepts +00:00, not Z in older Python versions.
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "from_date must be an ISO-8601 datetime with a timezone offset. "
            "Examples: '2026-07-01T12:00:00+03:30' or "
            "'2026-07-01 12:00:00+03:30'."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "from_date must include a timezone offset, such as '+03:30' or 'Z'. "
            "Do not pass a timezone-naive datetime."
        )

    return parsed


def _add_months(value: datetime, amount: int) -> datetime:
    """
    Add calendar months while safely handling unequal month lengths.

    Example:
    2026-01-31 + 1 month -> 2026-02-28
    """
    total_months = value.year * 12 + (value.month - 1) + amount

    target_year, target_month_index = divmod(total_months, 12)
    target_month = target_month_index + 1

    last_day = calendar.monthrange(target_year, target_month)[1]
    target_day = min(value.day, last_day)

    return value.replace(
        year=target_year,
        month=target_month,
        day=target_day,
    )


def _add_years(value: datetime, amount: int) -> datetime:
    """
    Add calendar years while safely handling leap days.

    Example:
    2024-02-29 + 1 year -> 2025-02-28
    """
    target_year = value.year + amount
    last_day = calendar.monthrange(target_year, value.month)[1]
    target_day = min(value.day, last_day)

    return value.replace(year=target_year, day=target_day)


def _format_utc_offset(value: datetime) -> str:
    """Convert +0330 to +03:30."""
    offset = value.strftime("%z")

    if not offset:
        return "+00:00"

    return f"{offset[:3]}:{offset[3:]}"


@tool
def compute_date(
    from_date: str,
    amount: int,
    unit: DateUnit,
) -> ComputedDate:
    """
    Perform reliable calendar date arithmetic.

    Use this tool whenever a user requests a date relative to another date,
    such as "tomorrow", "5 days from July 1", "next month", or
    "two years after the booking date".

    Important instructions:
    - `from_date` MUST be a complete ISO-8601 datetime including its UTC offset.
    - Do not invent the current date. Use the current datetime provided in context.
    - For a named calendar date, include a time and timezone offset before calling.
    - Use positive `amount` for future dates and negative `amount` for past dates.

    Args:
        from_date:
            Starting datetime with a timezone offset.

            Valid examples:
            - "2026-07-01T12:00:00+03:30"
            - "2026-07-01 12:00:00+03:30"
            - "2026-07-01T08:30:00Z"

        amount:
            Number of units to add or subtract.

            Examples:
            - 1 means one day/week/month/year after from_date.
            - -3 means three days/weeks/months/years before from_date.

        unit:
            The calendar unit to apply. Must be exactly one of:
            "days", "weeks", "months", or "years".

    Returns:
        A SQLite-ready UTC datetime, the original timezone offset for a separate
        SQLite timezone field, and a local ISO-8601 datetime for display.

    Examples:
        compute_date(
            from_date="2026-06-20T14:30:00+03:30",
            amount=1,
            unit="days",
        )
        -> {
            "utc_datetime": "2026-06-21 11:00:00.000000",
            "timezone": "+03:30",
            "local_datetime": "2026-06-21T14:30:00+03:30"
        }

        compute_date(
            from_date="2026-07-01T00:00:00+03:30",
            amount=5,
            unit="days",
        )
        -> {
            "utc_datetime": "2026-07-05 20:30:00.000000",
            "timezone": "+03:30",
            "local_datetime": "2026-07-06T00:00:00+03:30"
        }
    """
    start = _parse_aware_datetime(from_date)

    if unit == "days":
        from datetime import timedelta

        result = start + timedelta(days=amount)

    elif unit == "weeks":
        from datetime import timedelta

        result = start + timedelta(weeks=amount)

    elif unit == "months":
        result = _add_months(start, amount)

    elif unit == "years":
        result = _add_years(start, amount)

    else:
        # Defensive guard; Literal already validates this for normal tool calls.
        raise ValueError(f"Unsupported unit: {unit!r}")

    utc_result = result.astimezone(timezone.utc)

    return ComputedDate(
        # Intentionally no timezone suffix: designed for SQLite DATETIME storage.
        utc_datetime=utc_result.replace(tzinfo=None).strftime(SQLITE_DATETIME_FORMAT),
        # Preserve the original offset in a separate SQLite TEXT column.
        timezone=_format_utc_offset(result),
        # Use this for user-facing confirmation messages.
        local_datetime=result.isoformat(),
    )
