"""Shared test fixtures.

`client` gives every test a fresh, empty store. Without the `store.clear()`,
tests would pass alone and fail together the moment they run in a different
order — the single most common "but it works on my machine" CI failure.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import store


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    with TestClient(app) as test_client:
        yield test_client
    store.clear()
