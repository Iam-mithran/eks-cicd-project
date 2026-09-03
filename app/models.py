"""Request/response models.

Pydantic validates every incoming payload before your code sees it, so the
API returns a clean 422 instead of blowing up with a KeyError. The tests in
`tests/test_tasks.py` lean on that — a validation rule you break here fails
CI in seconds.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskCreate(BaseModel):
    """What a client must send to POST /api/v1/tasks."""

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    status: Status = Status.todo


class TaskUpdate(BaseModel):
    """PATCH body — every field optional, only what is sent gets changed."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: Status | None = None


class Task(TaskCreate):
    """What the API returns."""

    id: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
