from typing import Literal

from pydantic import BaseModel, Field


class Capability(BaseModel):
    id: str
    description: str
    is_enable: bool = Field(default=True)


# class PlanStep(BaseModel):
#     capability_id: str
#     reason: str
#     # depends_on: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    capability_id: str = Field(
        description=(
            "The exact ID of a capability from the provided capability catalog "
            "that should be used for this step."
        )
    )
    reason: str = Field(
        description=(
            "Why this capability must be executed at this point in the plan, "
            "including any dependency on earlier steps."
        )
    )


class ExecutionPlan(BaseModel):
    goal: str = Field(
        description=(
            "A concise statement of the user goal that this execution plan "
            "will accomplish."
        )
    )
    steps: list[PlanStep] = Field(
        default_factory=list,
        description=(
            "The minimal ordered list of capability invocations required to "
            "achieve the goal. Steps must be linearly executable: every "
            "prerequisite of a step must appear before that step."
        ),
    )


class Clarification(BaseModel):
    user_message: str = Field(
        description=(
            "A concise message asking the user for the missing information "
            "needed to create a valid plan, or explaining that the request "
            "cannot be fulfilled with the available capabilities."
        )
    )


class PlannerResponse(BaseModel):
    kind: Literal["plan", "clarification"]
    response: ExecutionPlan | Clarification = Field(
        description=(
            "Return ExecutionPlan when the request can be planned safely with "
            "the available capabilities and available user information. "
            "Return Clarification when essential information is missing, the "
            "request is ambiguous, or the request cannot be fulfilled using "
            "the available capabilities."
        )
    )
