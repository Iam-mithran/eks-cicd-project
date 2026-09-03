"""An in-memory task store.

Deliberately NOT a database. A real database would mean a container, a
migration step and a connection secret — three things that break during a
live recording and teach nothing about GitHub Actions. Every pod keeps its
own copy, so the data resets on restart. That is fine: the deployment, not
the data, is what we are demonstrating.

Swapping this for PostgreSQL later changes only this file — the API, the
tests, the image and the pipeline all stay exactly as they are.
"""

from itertools import count
from threading import Lock

from app.models import Task, TaskCreate, TaskUpdate


class TaskStore:
    def __init__(self) -> None:
        self._items: dict[int, Task] = {}
        self._ids = count(1)
        # Uvicorn serves requests concurrently; a plain dict update is not
        # atomic across threads. The lock keeps the demo honest.
        self._lock = Lock()

    def list(self) -> list[Task]:
        with self._lock:
            return list(self._items.values())

    def get(self, task_id: int) -> Task | None:
        with self._lock:
            return self._items.get(task_id)

    def create(self, payload: TaskCreate) -> Task:
        with self._lock:
            task = Task(id=next(self._ids), **payload.model_dump())
            self._items[task.id] = task
            return task

    def update(self, task_id: int, payload: TaskUpdate) -> Task | None:
        with self._lock:
            existing = self._items.get(task_id)
            if existing is None:
                return None
            # exclude_unset: a PATCH that omits `status` must not reset it.
            changes = payload.model_dump(exclude_unset=True)
            updated = existing.model_copy(update=changes)
            self._items[task_id] = updated
            return updated

    def delete(self, task_id: int) -> bool:
        with self._lock:
            return self._items.pop(task_id, None) is not None

    def clear(self) -> None:
        """Used by the test fixture so tests never leak state into each other."""
        with self._lock:
            self._items.clear()


store = TaskStore()
