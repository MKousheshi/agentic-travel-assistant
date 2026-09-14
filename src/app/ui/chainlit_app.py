import json
import os
import uuid
from typing import Any

import chainlit as cl
import httpx
from httpx_sse import aconnect_sse

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# These nodes' output is already shown via `token`/`message` events (`synth`)
# or never carries anything user-relevant (`exit`). Their `node` events also
# always arrive after `synth`'s tokens have already streamed into the answer
# message, so rendering them as steps would show up trailing after the
# answer instead of before it.
_HIDDEN_STEP_NODES = {"synth", "exit"}


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("thread_id", str(uuid.uuid4()))


async def _run(body: dict[str, Any]) -> None:
    thread_id = cl.user_session.get("thread_id")
    answer: cl.Message | None = None

    try:
        async with (
            httpx.AsyncClient(
                base_url=API_BASE_URL, timeout=httpx.Timeout(10, read=None)
            ) as client,
            aconnect_sse(
                client, "POST", f"/threads/{thread_id}/stream", json=body
            ) as event_source,
        ):
            response = event_source.response
            if response.is_error:
                await response.aread()
                detail = response.text
                try:
                    detail = response.json().get("detail", detail)
                except ValueError:
                    pass
                await cl.ErrorMessage(
                    f"Request rejected ({response.status_code}): {detail}"
                ).send()
                return
            async for sse in event_source.aiter_sse():
                if sse.event == "node":
                    data = sse.json()
                    if data["node"] in _HIDDEN_STEP_NODES:
                        continue
                    async with cl.Step(name=data["node"], type="tool") as step:
                        step.output = json.dumps(
                            data["output"], indent=2, ensure_ascii=False
                        )
                elif sse.event == "token":
                    if answer is None:
                        answer = cl.Message(content="")
                    await answer.stream_token(sse.json()["content"])
                elif sse.event == "message":
                    content = sse.json()["content"]
                    if answer is not None:
                        answer.content = content
                        await answer.update()
                    else:
                        await cl.Message(content=content).send()
                elif sse.event == "interrupt":
                    value = sse.json()["value"]
                    content = (
                        f"{value['message']}\n{value['data']}"
                        if isinstance(value, dict) and "message" in value
                        else str(value)
                    )
                    payload = value if isinstance(value, dict) else {"value": value}
                    actions = [
                        cl.Action(name="confirm", payload=payload, label="Confirm"),
                        cl.Action(name="cancel", payload=payload, label="Cancel"),
                    ]
                    await cl.Message(content=content, actions=actions).send()
                elif sse.event == "error":
                    await cl.ErrorMessage(sse.json()["detail"]).send()
                elif sse.event == "end":
                    break
    except httpx.HTTPError as exc:
        await cl.ErrorMessage(f"Backend unreachable: {exc}").send()


@cl.action_callback("confirm")
async def on_confirm(action: cl.Action) -> None:
    await action.remove()
    await _run({"resume": {**action.payload, "confirmed": True}})


@cl.action_callback("cancel")
async def on_cancel(action: cl.Action) -> None:
    await action.remove()
    await _run({"resume": {**action.payload, "confirmed": False}})


@cl.on_message
async def on_message(message: cl.Message) -> None:
    if not message.content.strip():
        # An attachment-only message (no text) has nothing for the agent to
        # act on; the backend would otherwise reject it with a 422.
        await cl.Message(content="Please include a text message.").send()
        return
    await _run({"message": message.content})


@cl.on_chat_end
async def on_chat_end() -> None:
    thread_id = cl.user_session.get("thread_id")
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
            await client.delete(f"/threads/{thread_id}")
    except httpx.HTTPError:
        pass
