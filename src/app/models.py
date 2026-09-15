from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStepDraft(BaseModel):
    capability_id: str = Field(
        description=(
            "The exact ID of a capability from the provided capability catalog "
            "that should be used for this step."
        )
    )
    action: str = Field(
        description=(
            "A concise imperative description of the work to perform, such as "
            "'Find available flights', 'Create a booking', or 'Cancel ticket'."
        )
    )

    goal: str = Field(
        description=(
            "The concrete outcome that must be achieved for this step to be "
            "considered successful. Describe the result, not the method."
        )
    )

    reason: str = Field(
        description=(
            "Why this step is necessary and why it must occur after any "
            "preceding steps."
        )
    )


class PlanStep(PlanStepDraft):
    step_id: int = Field(
        description="Unique identifier generated for this plan step.",
    )


class StepResult(BaseModel):
    message: str
    data: dict[str, Any]
    step: PlanStep


class ExecutionPlan(BaseModel):
    user_query: str = Field(
        min_length=1,
        description=(
            "The user's original request, preserved verbatim. Do not rewrite, "
            "summarize, or add assumptions."
        ),
    )
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


class PlanResponse(BaseModel):
    kind: Literal["plan"] = Field(
        description=(
            "Use 'plan' when the request can be planned safely with the "
            "available capabilities and available user information."
        )
    )
    response: ExecutionPlan = Field(
        description=(
            "The execution plan to return when the request is fully actionable."
        )
    )


class ClarificationResponse(BaseModel):
    kind: Literal["clarification"] = Field(
        description=(
            "Use 'clarification' when essential information is missing, the "
            "request is ambiguous, or the request cannot be fulfilled using "
            "the available capabilities."
        )
    )
    response: Clarification = Field(
        description=(
            "A clarification request or explanation of why the request cannot "
            "be fulfilled."
        )
    )


PlannerResponse = PlanResponse | ClarificationResponse


class CapabilitySuccess(BaseModel):
    status: Literal["success"] = "success"
    message: str = Field(
        description="A human-readable result of the successful operation."
    )
    data: dict[str, Any] = Field(default_factory=dict)


class CapabilityNeedsInformation(BaseModel):
    status: Literal["needs_information"] = "needs_information"
    message: str = Field(
        description="A short explanation of why more information is required."
    )
    missing_fields: list[str] = Field(
        description="The fields that must be provided by the user."
    )
    question: str = Field(
        description="The exact question that should be shown to the user."
    )
    context: dict[str, Any] = Field(default_factory=dict)


class CapabilityFailure(BaseModel):
    status: Literal["failure"] = "failure"
    message: str = Field(description="A user-friendly explanation of the failure.")
    reason: str = Field(description="The technical or business reason for the failure.")
    # retryable: bool = False
    # error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


CapabilityResult = CapabilitySuccess | CapabilityNeedsInformation | CapabilityFailure


class Feedback(BaseModel):
    validated: bool = Field(
        description=(
            "Whether the execution plan is valid and sufficiently satisfies "
            "the user's request. Set to true only when the plan is safe, "
            "complete, logically ordered, and executable using the available "
            "capabilities."
        )
    )

    message: str = Field(
        description=(
            "A concise validation result. If validated is true, briefly state "
            "that the plan is valid. If validated is false, explain the exact "
            "problems that must be corrected, including the affected step or "
            "steps and the required change. Do not propose a completely new "
            "plan and do not include information unrelated to plan validation."
        )
    )


class Confirmation(BaseModel):
    message: str
    data: dict[str, Any]
    confirmed: bool = False
