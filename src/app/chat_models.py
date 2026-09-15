from functools import cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@cache
def get_chat_model() -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
        # Without an explicit timeout, the underlying httpx client is built
        # with Timeout(timeout=None) — no timeout at all, overriding even the
        # OpenAI SDK's own default. A stalled connection to an
        # OpenAI-compatible endpoint would then hang a graph run forever with
        # no way for the user (or `stream_run`'s error handling) to see it.
        timeout=60,
    )
