from typing import Annotated, Any, Literal, Required, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from app.models import ExecutionPlan, Feedback, StepResult


class ExecutionState(BaseModel):
    current_step_index: int = 0
    results: list[StepResult] = Field(default_factory=list)
    status: Literal[
        "running",
        "waiting_for_user",
        "failed",
        "completed",
    ] = "running"
    pending_question: str | None = None



class WorkflowState(TypedDict, total=False):
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    plan: ExecutionPlan
    feedback: Feedback
    execution: ExecutionState
    user_message: str
    retries: int
    # state: Required[Literal["planning", "evaluation", "execution"]]
