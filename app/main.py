"""taskapi — a small FastAPI service, built to be deployed rather than admired.

Everything the pipeline needs from an application is here and nothing else:

  * `/healthz`  — liveness.  "Is the process alive?"      Kubernetes restarts the pod if this fails.
  * `/readyz`   — readiness. "Can it serve traffic yet?"  Kubernetes removes the pod from the
                  Service if this fails. This is what makes a rolling deploy zero-downtime.
  * `/`         — build info. Prints the RELEASE the pipeline stamped in, so a `curl` against
                  the live URL proves WHICH commit is running.
  * `/api/v1/tasks` — a normal CRUD surface, so there is something real to test.

Run it locally:   uvicorn app.main:app --reload
Then open:        http://127.0.0.1:8000/docs
"""

import os
import logging

from fastapi import FastAPI, HTTPException, Response, status

from app import __version__
from app.config import settings
from app.models import Task, TaskCreate, TaskUpdate
from app.storage import store

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(settings.app_name)

app = FastAPI(
    title="Task API",
    version=__version__,
    description="The service the Day 6 GitHub Actions pipeline builds and ships to EKS.",
)


# ── Operational endpoints — the ones Kubernetes and the pipeline call ────────


@app.get("/", tags=["meta"])
def root() -> dict:
    """Build info. The smoke test in the pipeline asserts on this response."""
    return {
        "service": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "release": settings.release,
        "docs": "/docs",
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    """Liveness probe. Cheap on purpose — no I/O, no dependencies.

    A liveness probe that talks to a database is a classic outage: the database
    hiccups, every probe fails, and Kubernetes restarts every pod at once,
    turning a small problem into a full outage.
    """
    return {"status": "ok"}


@app.get("/readyz", tags=["meta"])
def readyz() -> dict:
    """Readiness probe. THIS is where you check dependencies.

    Today the store is in-memory so there is nothing to check. When you swap in
    a real database, ping it here — not in `/healthz`.
    """
    return {"status": "ready", "tasks": len(store.list())}


# ── The actual API ───────────────────────────────────────────────────────────


@app.get("/api/v1/tasks", response_model=list[Task], tags=["tasks"])
def list_tasks() -> list[Task]:
    return store.list()


@app.post(
    "/api/v1/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
)
def create_task(payload: TaskCreate) -> Task:
    task = store.create(payload)
    log.info("task created id=%s title=%s", task.id, task.title)
    return task


@app.get("/api/v1/tasks/{task_id}", response_model=Task, tags=["tasks"])
def get_task(task_id: int) -> Task:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return task


@app.patch("/api/v1/tasks/{task_id}", response_model=Task, tags=["tasks"])
def update_task(task_id: int, payload: TaskUpdate) -> Task:
    task = store.update(task_id, payload)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    log.info("task updated id=%s", task_id)
    return task


@app.delete(
    "/api/v1/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["tasks"],
)
def delete_task(task_id: int) -> Response:
    if not store.delete(task_id):
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    log.info("task deleted id=%s", task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
