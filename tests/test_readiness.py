from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.robinhood.read_service import robinhood_read_service


client = TestClient(app)


def test_ready_when_robinhood_disabled(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_mcp_enabled", False)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"ready": True, "robinhood": "disabled"}


def test_ready_when_robinhood_connected(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_mcp_enabled", True)
    monkeypatch.setattr(
        robinhood_read_service.snapshot,
        "connection_state",
        "connected",
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"ready": True, "robinhood": "connected"}


def test_not_ready_when_robinhood_degraded(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_mcp_enabled", True)
    monkeypatch.setattr(
        robinhood_read_service.snapshot,
        "connection_state",
        "degraded",
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"ready": False, "robinhood": "degraded"}
    }


def test_not_ready_when_robinhood_authentication_required(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_mcp_enabled", True)
    monkeypatch.setattr(
        robinhood_read_service.snapshot,
        "connection_state",
        "authentication_required",
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"ready": False, "robinhood": "authentication_required"}
    }
