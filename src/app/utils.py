from pydantic import ValidationError


def flatten_validation_errors(
    exc: ValidationError, field_labels: dict[str, str] | None = None
) -> list[dict]:
    """Turn a ValidationError into a compact, LLM-friendly list."""
    out = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(part) for part in err["loc"])
        out.append(
            {
                "field": loc,
                "label": (field_labels or {}).get(
                    loc, loc
                ),  # human name: "departure_date"
                "type": err["type"],  # "missing", "string_type", ...
                "message": err["msg"],
            }
        )
    return out