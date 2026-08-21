from typing import Annotated, List, Required, TypedDict, Optional, Any
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from app.models import ExecutionPlan
class OverallState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: ExecutionPlan
    # intent: str
    # book_ref: str
    # booking_result: Optional[dict]
    user_message: str
    # error: str
