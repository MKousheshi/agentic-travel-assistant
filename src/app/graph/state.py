from typing import Annotated, List, Required, TypedDict, Optional, Any
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from app.models import ExecutionPlan, ExecutionState, ResponseSynthesisInput


class OverallState(TypedDict, total=False):
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    plan: ExecutionPlan
    execution: ExecutionState
    synthesis: ResponseSynthesisInput
    user_message: str
    errors: List[str]
