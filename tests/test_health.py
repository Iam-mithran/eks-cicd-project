"""The probes Kubernetes calls. If these break, every rollout hangs."""


def test_healthz_is_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_root_exposes_release_info(client):
    """The pipeline's smoke test asserts on exactly these keys."""
    body = client.get("/").json()
    assert body["service"]
    assert body["version"]
    assert "release" in body
    assert "environment" in body
