from typing import Required, TypedDict, Optional, Any


class OverallState(TypedDict, total=False):
    user_input: str
    intent: str
    book_ref: str
    booking_result: Optional[dict]
    response: str
    error: str
