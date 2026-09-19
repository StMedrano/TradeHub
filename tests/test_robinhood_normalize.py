from app.robinhood.normalize import (
    count_records,
    find_first_list,
    find_first_number,
    mcp_result_to_data,
)


def test_find_nested_buying_power():
    payload = {
        "data": {
            "total_value": "12500.50",
            "buying_power": {
                "buying_power": "3000.25",
                "display_currency": "USD",
            },
        }
    }
    assert find_first_number(payload, ("total_value",)) == 12500.50
    assert find_first_number(payload, ("buying_power",)) == 3000.25


def test_find_results_list():
    payload = {"data": {"results": [{"symbol": "AAPL"}, {"symbol": "MSFT"}]}}
    assert find_first_list(payload, ("results",)) == [
        {"symbol": "AAPL"},
        {"symbol": "MSFT"},
    ]


def test_count_records_from_results():
    payload = {"data": {"results": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}}
    assert count_records(payload) == 3



def test_extract_candidate_records_handles_single_nested_objects():
    from app.robinhood.normalize import extract_candidate_records

    payload = {
        "data": {
            "chain": {
                "id": "chain-1",
                "symbol": "SPY",
            }
        }
    }

    rows = extract_candidate_records(payload)
    assert len(rows) == 1
    assert rows[0]["id"] == "chain-1"


def test_is_effectively_empty_nested_payload():
    from app.robinhood.normalize import is_effectively_empty

    assert is_effectively_empty({"data": {"results": []}})
    assert not is_effectively_empty({"data": {"realized_pnl": 0}})



class _FakeResult:
    def __init__(self, structured):
        self.structuredContent = structured
        self.content = []


def test_mcp_result_decodes_json_structured_content():
    payload = _FakeResult(
        '{"data":{"results":[{"realized_pnl":"12.34"}]}}'
    )

    decoded = mcp_result_to_data(payload)

    assert decoded == {
        "data": {
            "results": [
                {"realized_pnl": "12.34"}
            ]
        }
    }


def test_mcp_result_decodes_fenced_json_structured_content():
    payload = _FakeResult(
        '```json\n{"data":{"results":[]}}\n```'
    )

    decoded = mcp_result_to_data(payload)

    assert decoded == {"data": {"results": []}}
