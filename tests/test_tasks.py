"""CRUD behaviour — the tests that make a red pipeline mean something."""

import pytest


def test_list_is_empty_to_start(client):
    assert client.get("/api/v1/tasks").json() == []


def test_create_returns_201_and_the_task(client):
    response = client.post("/api/v1/tasks", json={"title": "Write the pipeline"})
    assert response.status_code == 201

    body = response.json()
    assert body["id"] == 1
    assert body["title"] == "Write the pipeline"
    assert body["status"] == "todo"  # the default
    assert body["created_at"]


def test_created_task_can_be_fetched(client):
    created = client.post("/api/v1/tasks", json={"title": "Ship it"}).json()
    fetched = client.get(f"/api/v1/tasks/{created['id']}").json()
    assert fetched == created


def test_patch_changes_only_the_fields_sent(client):
    created = client.post(
        "/api/v1/tasks",
        json={"title": "Deploy to EKS", "description": "keep me"},
    ).json()

    updated = client.patch(f"/api/v1/tasks/{created['id']}", json={"status": "done"}).json()

    assert updated["status"] == "done"
    assert updated["description"] == "keep me"  # untouched
    assert updated["title"] == "Deploy to EKS"  # untouched


def test_delete_removes_the_task(client):
    created = client.post("/api/v1/tasks", json={"title": "Temporary"}).json()

    assert client.delete(f"/api/v1/tasks/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{created['id']}").status_code == 404


@pytest.mark.parametrize("task_id", [1, 42, 9999])
def test_missing_task_returns_404(client, task_id):
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},  # title is required
        {"title": ""},  # min_length=1
        {"title": "x" * 121},  # max_length=120
        {"title": "ok", "status": "nope"},  # not a valid Status
    ],
)
def test_invalid_payloads_are_rejected_with_422(client, payload):
    assert client.post("/api/v1/tasks", json=payload).status_code == 422
