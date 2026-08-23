from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from app.models import PlannerResponse, Feedback
from app.chat_models import plan_model
from app._capabilities import registry
from app.prompts.prompts import PLANNER_SYSTEM_PROMPT, VALIDATOR_SYSTEM_PROMPT

# planner_llm = plan_model.with_structured_output(PlannerResponse)

PLANNER_PROMPT = PLANNER_SYSTEM_PROMPT.format(
    capability_catalog=registry.catalog(),
    capability_ids=[c.id for c in registry.all()],
)
planner_agent = create_agent(
    model=plan_model,
    system_prompt=PLANNER_PROMPT,
    response_format=ToolStrategy(PlannerResponse),
)

VALIDATOR_PROMPT = VALIDATOR_SYSTEM_PROMPT.format(
    capability_catalog=registry.catalog(),
    capability_ids=[c.id for c in registry.all()],
)
eval_agent = create_agent(
    model=plan_model,
    system_prompt=VALIDATOR_PROMPT,
    response_format=ToolStrategy(Feedback),
)
