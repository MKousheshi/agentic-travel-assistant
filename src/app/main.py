from langchain_openai import ChatOpenAI
from .config import get_settings

from app.graph.build_graph import build_graph

def main():
    # settings = get_settings()
    # llm = ChatOpenAI(
    #     model="deepseek/deepseek-v4-flash",
    #     api_key=settings.openrouter_api_key,
    #     base_url="https://openrouter.ai/api/v1",
    # )
    graph = build_graph()
    
    result = graph.invoke({})
    print(result)
