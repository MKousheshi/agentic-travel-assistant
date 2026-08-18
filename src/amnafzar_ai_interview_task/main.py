from langchain_openai import ChatOpenAI
from .config import Settings


def main():
    settings = Settings()
    llm = ChatOpenAI(
        model="deepseek/deepseek-v4-flash",
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    result = llm.invoke("Say hello in one sentence.")
    print(result.content)
