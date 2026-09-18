from app.robinhood.normalize import (
    count_records,
    find_first_list,
    find_first_number,
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
