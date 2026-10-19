from sidedeck.application.p5_sec_ttm import derive_ttm_net_income


def fact(start, end, filed, value, form="10-Q", accn="a"):
    return {"start": start, "end": end, "filed": filed, "val": value,
            "form": form, "accn": accn}


def payload(rows):
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}


def test_ttm_reconstructs_from_original_filed_components():
    records = payload([
        fact("2024-01-01", "2024-03-31", "2024-05-01", 20, accn="q124"),
        fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K", "fy24"),
        fact("2025-01-01", "2025-03-31", "2025-05-01", 35, accn="q125"),
    ])
    rows = derive_ttm_net_income(records, "2025-05-02")
    current = next(r for r in rows if r["report_period"] == "2025-03-31")
    assert current["value"] == 115
    assert current["filing_date"] == "2025-05-01"
    assert {s["accession"] for s in current["components"]} == {"fy24", "q124", "q125"}


def test_cutoff_excludes_unpublished_quarter():
    records = payload([
        fact("2024-01-01", "2024-03-31", "2024-05-01", 20),
        fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K"),
        fact("2025-01-01", "2025-03-31", "2025-05-01", 35),
    ])
    assert all(r["report_period"] != "2025-03-31"
               for r in derive_ttm_net_income(records, "2025-04-01"))


def test_missing_prior_ytd_does_not_invent_ttm():
    records = payload([
        fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K"),
        fact("2025-01-01", "2025-03-31", "2025-05-01", 35),
    ])
    assert all(r["report_period"] != "2025-03-31"
               for r in derive_ttm_net_income(records, "2025-06-01"))


def test_later_restatement_does_not_replace_original():
    records = payload([
        fact("2024-01-01", "2024-03-31", "2024-05-01", 20, accn="original"),
        fact("2024-01-01", "2024-03-31", "2025-04-01", 60, accn="restated"),
        fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K"),
        fact("2025-01-01", "2025-03-31", "2025-05-01", 35),
    ])
    result = derive_ttm_net_income(records, "2025-06-01")
    assert next(r["value"] for r in result if r["report_period"] == "2025-03-31") == 115
