from app.robinhood.read_service import RobinhoodReadService


def test_selects_agentic_account():
    payload = {
        "data": {
            "accounts": [
                {
                    "account_number": "PRIMARY",
                    "agentic_allowed": False,
                },
                {
                    "account_number": "AGENTIC",
                    "agentic_allowed": True,
                },
            ]
        }
    }
    assert RobinhoodReadService._agentic_account_number(payload) == "AGENTIC"


def test_open_order_count():
    payload = {
        "data": {
            "results": [
                {"state": "filled"},
                {"state": "queued"},
                {"state": "confirmed"},
                {"state": "cancelled"},
                {"state": "partially_filled"},
            ]
        }
    }
    assert RobinhoodReadService._open_order_count(payload) == 3
