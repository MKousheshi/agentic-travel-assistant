"""Regenerate workflow.png from the compiled LangGraph workflow.

Usage: uv run python scripts/generate_workflow_png.py

Renders via the mermaid.ink API (LangGraph's default `draw_mermaid_png`
backend), so it needs network access; it does not call the LLM.
"""

import pathlib

from app.graph.studio import make_graph

OUTPUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "workflow.png"


def main() -> None:
    graph = make_graph()
    png_bytes = graph.get_graph().draw_mermaid_png()
    OUTPUT_PATH.write_bytes(png_bytes)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
