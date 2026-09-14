import asyncio
from typing import Annotated, Any

from fastapi import Depends, Request


def get_graph(request: Request) -> Any:
    return request.app.state.graph


def get_lock(request: Request, thread_id: str) -> asyncio.Lock:
    """
    One lock per thread, so concurrent requests on the same thread serialize
    instead of racing the thread's shared DB session and checkpoint.
    """
    locks: dict[str, asyncio.Lock] = request.app.state.locks
    lock = locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[thread_id] = lock
    return lock


def get_session(request: Request, thread_id: str) -> Any:
    """Lazily create and cache the one DB session a thread's runs share."""
    sessions: dict[str, Any] = request.app.state.sessions
    session = sessions.get(thread_id)
    if session is None:
        session = request.app.state.session_factory()
        sessions[thread_id] = session
    return session


GraphDep = Annotated[Any, Depends(get_graph)]
LockDep = Annotated[asyncio.Lock, Depends(get_lock)]
SessionDep = Annotated[Any, Depends(get_session)]
