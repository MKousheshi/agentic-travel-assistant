from functools import cache

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from app.chat_models import get_chat_model
from app.models import Feedback, PlannerResponse
from app.prompts.planner import PLANNER_SYSTEM_PROMPT
from app.prompts.validator import VALIDATOR_SYSTEM_PROMPT
from app.registry import registry


# Cached factories build each agent once, from whatever capabilities are
# registered at first use. Registration happens once at startup before any
# agent is built, so a cached agent's catalog never goes stale.
@cache
def get_planner_agent() -> CompiledStateGraph:
    capabilities = registry.all()
    if not capabilities:
        raise RuntimeError(
            "No capabilities are registered; call load_capabilities() before "
            "building agents."
        )
    prompt = PLANNER_SYSTEM_PROMPT.format(
        capability_catalog=registry.catalog(),
        capability_ids=[c.id for c in capabilities],
    )
    return create_agent(
        model=get_chat_model(),
        system_prompt=prompt,
        response_format=ToolStrategy(PlannerResponse),
    )


@cache
def get_eval_agent() -> CompiledStateGraph:
    capabilities = registry.all()
    if not capabilities:
        raise RuntimeError(
            "No capabilities are registered; call load_capabilities() before "
            "building agents."
        )
    prompt = VALIDATOR_SYSTEM_PROMPT.format(
        capability_catalog=registry.catalog(),
        capability_ids=[c.id for c in capabilities],
    )
    return create_agent(
        model=get_chat_model(),
        system_prompt=prompt,
        response_format=ToolStrategy(Feedback),
    )


@cache
def get_synthesizer_model() -> ChatOpenAI:
    return get_chat_model()
