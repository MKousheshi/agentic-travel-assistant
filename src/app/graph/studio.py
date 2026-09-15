from langgraph.graph.state import CompiledStateGraph

from app.graph.build_graph import build_graph
from app.registry import load_capabilities


def make_graph() -> CompiledStateGraph:
    load_capabilities()
    return build_graph()
