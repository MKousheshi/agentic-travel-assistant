from langchain_openai import ChatOpenAI

from app.config import get_settings

mini_model = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=get_settings().openai_api_key,
    base_url=get_settings().openai_base_url,
    temperature=0,
)
model = ChatOpenAI(
    model="gpt-4o",
    api_key=get_settings().openai_api_key,
    base_url=get_settings().openai_base_url,
    temperature=0,
)


plan_model = mini_model
capability_model = mini_model
