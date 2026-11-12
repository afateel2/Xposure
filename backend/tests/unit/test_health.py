from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_expected_shape():
    """DB/Qdrant are very likely down in a unit-test environment (no docker
    compose running) — this only asserts the endpoint responds with the
    right shape and never raises, not that every dependency is up. M1's
    guardrail is "no silent fallback, visible error state": a down
    dependency must show reachable=False, never a swallowed exception."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert "reachable" in body["db"]
    assert "reachable" in body["qdrant"]
    assert "reachable" in body["llm"]
