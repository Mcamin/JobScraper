from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    """Basic smoke test to verify the API health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
