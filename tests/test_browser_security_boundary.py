from fastapi.testclient import TestClient

from app.main import app
from app.robinhood.read_service import RobinhoodSnapshot, robinhood_read_service


def test_dashboard_does_not_render_robinhood_account_number(monkeypatch):
    """Brokerage identifiers may be persisted server-side but never sent to the browser."""
    secret_account = "SECRET-ACCOUNT-123456"
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        agentic_account_number=secret_account,
        equity=10000.0,
        buying_power=5000.0,
        cash=2500.0,
        open_equity_positions=1,
        open_option_positions=0,
        open_orders=0,
    )
    monkeypatch.setattr(robinhood_read_service, "snapshot", snapshot)

    # The dashboard depends on startup-created database tables, so exercise it
    # inside the application lifespan.
    with TestClient(app) as client:
        response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    assert secret_account not in response.text
    assert "agentic_account_number" not in response.text
    assert "account_number" not in response.text


def test_health_does_not_render_robinhood_account_number(monkeypatch):
    secret_account = "SECRET-ACCOUNT-654321"
    monkeypatch.setattr(
        robinhood_read_service,
        "snapshot",
        RobinhoodSnapshot(
            connection_state="connected",
            agentic_account_number=secret_account,
        ),
    )

    # Health is database-independent. Do not start a second application
    # lifespan here: the singleton Robinhood read service owns asyncio
    # primitives created by the first lifespan and must not be rebound to a
    # second TestClient event loop.
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert secret_account not in response.text
    assert "agentic_account_number" not in response.text
    assert "account_number" not in response.text
