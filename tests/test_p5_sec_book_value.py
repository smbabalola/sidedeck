from sidedeck.application.p5_sec_book_value import book_value_per_share_evidence


def row(tag, unit, value, accession="0001818874-26-000099"):
    return {"form": "10-Q", "end": "2026-06-30", "filed": "2026-08-06",
            "accn": accession, "val": value}


def source(equity, shares, *, accession="0001818874-26-000099"):
    return {"facts": {"us-gaap": {
        "StockholdersEquity": {"units": {"USD": [row("StockholdersEquity", "USD", equity)]}},
        "CommonStockSharesOutstanding": {"units": {"shares": [
            row("CommonStockSharesOutstanding", "shares", shares, accession)]}},
    }}}


def test_matched_filed_equity_and_shares_is_audit_only():
    result = book_value_per_share_evidence(source(1200, 100), "2026-10-19")
    assert result["matched_periods"] == 1
    assert result["observations"][0]["book_value_per_share_preview"] == 12
    assert result["buffett_ready"] is False
    assert result["broker_execution"] == "DISABLED"


def test_mismatched_filing_accession_never_joins():
    result = book_value_per_share_evidence(
        source(1200, 100, accession="0001818874-26-000123"), "2026-10-19")
    assert result["matched_periods"] == 0
    assert result["rejected"][0]["reason"] == "missing_or_ambiguous_same_period_same_filing_shares"


def test_future_filing_not_visible_at_cutoff():
    result = book_value_per_share_evidence(source(1200, 100), "2026-07-01")
    assert result["matched_periods"] == 0


def test_missing_share_observation_does_not_invent_bvps():
    data = source(1200, 100)
    del data["facts"]["us-gaap"]["CommonStockSharesOutstanding"]
    result = book_value_per_share_evidence(data, "2026-10-19")
    assert not result["observations"]
