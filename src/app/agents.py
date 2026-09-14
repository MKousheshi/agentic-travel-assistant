from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from app.chat_models import mini_model, plan_model
from app.models import Feedback, PlannerResponse
from app.prompts.planner import PLANNER_SYSTEM_PROMPT
from app.prompts.validator import VALIDATOR_SYSTEM_PROMPT
from app.registry import registry

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

synthesizer_model = mini_model
