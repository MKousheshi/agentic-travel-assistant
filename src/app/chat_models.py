from langchain_openai import ChatOpenAI
from app.config import get_settings

mini_model = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=get_settings().metis_api_key,
    base_url="https://api.metisai.ir/openai/v1",
)
model = ChatOpenAI(
    model="gpt-4o",
    api_key=get_settings().metis_api_key,
    base_url="https://api.metisai.ir/openai/v1",
)
plan_model = model