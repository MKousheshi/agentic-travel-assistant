from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageRequest(BaseModel):
    """Send a new user message on a thread."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    """Resume a thread that is paused on a pending interrupt."""

    model_config = ConfigDict(extra="forbid")

    resume: Any


RunRequest = MessageRequest | ResumeRequest
