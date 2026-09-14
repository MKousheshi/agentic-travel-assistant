from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver

from app.api.routers import health, threads


def create_app(
    graph: Any = None,
    session_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        nonlocal graph, session_factory

        if graph is None:
            from app.registry import load_capabilities

            load_capabilities()

            from app.graph.build_graph import build_graph

            graph = build_graph(MemorySaver())

        if session_factory is None:
            from sqlmodel import Session

            from app.db.engine import engine

            session_factory = lambda: Session(engine)

        app.state.graph = graph
        app.state.session_factory = session_factory
        app.state.sessions = {}
        app.state.locks = {}

        yield

        for session in app.state.sessions.values():
            session.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(threads.router)

    return app


app = create_app()
