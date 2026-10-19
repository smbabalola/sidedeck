from pathlib import Path

import pytest

from sidedeck.application.tradingview_import import import_tradingview_csv


def write(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "fills.csv"
    target.write_text(body, encoding="utf-8")
    return target


HEAD = "execution_id,timestamp,symbol,side,quantity,price,status,fee\n"


def test_only_filled_executions_are_staged(tmp_path: Path) -> None:
    path = write(tmp_path, HEAD
                 + "pending-1,2026-10-19T13:00:00Z,AAPL,BUY,1,343.46,working,0\n"
                 + "fill-1,2026-10-19T14:00:00Z,AAPL,BUY,1,343.46,filled,0\n"
                 + "fill-1,2026-10-19T14:00:00Z,AAPL,BUY,1,343.46,filled,0\n")
    report = import_tradingview_csv(path, portfolio_id="tradingagents")
    assert len(report.fills) == 1
    assert report.ignored_unfilled == 1
    assert report.duplicate_rows == 1
    assert report.fills[0].portfolio_id == "tradingagents"


@pytest.mark.parametrize("body", [
    HEAD + "one,2026-10-19T14:00:00,AAPL,BUY,1,343.46,filled,0\n",
    HEAD + "one,2026-10-19T14:00:00Z,AAPL,BUY,-1,343.46,filled,0\n",
    HEAD + "one,2026-10-19T14:00:00Z,AAPL,BUY,1,NaN,filled,0\n",
    HEAD + "one,2026-10-19T14:00:00Z,AAPL,BUY,1,343.46,unknown,0\n",
    HEAD + "one,2026-10-19T14:00:00Z,AAPL,BUY,1,343.46,filled,0\n"
           + "one,2026-10-19T14:00:00Z,AAPL,BUY,2,343.46,filled,0\n",
])
def test_invalid_executions_fail_closed(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValueError):
        import_tradingview_csv(write(tmp_path, body), portfolio_id="ai-trading")


def test_wrong_headers_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="normalized"):
        import_tradingview_csv(write(tmp_path, "Symbol,Side,Price\nAAPL,Buy,343.46\n"),
                               portfolio_id="tradingagents")


def test_unauthorized_portfolio_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="authorized"):
        import_tradingview_csv(write(tmp_path, HEAD), portfolio_id="other")
