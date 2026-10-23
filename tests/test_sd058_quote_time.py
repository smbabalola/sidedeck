"""Friday retry pilot a51e41fa: live eToro rates `date` was a naive ISO string.

eToro documents `date` only as "date-time of the price in the system" (no offset stated).
A naive stamp is read as UTC *only* because the existing freshness gate then verifies it:
every real non-UTC zone is >= 30 minutes away, far outside the 60 s age / 5 s skew bounds.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sidedeck.domain.etoro_demo_orders import (
    EXPLICIT_OFFSET, MAX_QUOTE_AGE_SECONDS, MAX_QUOTE_SKEW_SECONDS, NAIVE_AS_UTC,
    EtoroDemoOrderError, parse_fresh_quote,
)

NOW = datetime(2026, 10, 23, 18, 1, 19, tzinfo=timezone.utc)


def quote(date):
    return {"results": [{"instrumentId": 1004, "bid": 526.10, "ask": 526.30, "date": date,
                         "quoteType": "realtime"}]}


def naive(moment):
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


@pytest.mark.parametrize("date", [
    (NOW - timedelta(seconds=2)).isoformat(),                                  # +00:00
    (NOW - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),           # Z
    (NOW - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=-4))).isoformat(),
    (NOW - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=1))).isoformat(),
])
def test_offset_aware_fresh_quotes_are_accepted(date):
    q = parse_fresh_quote(quote(date), instrument_id=1004, now=NOW)
    assert q.observed_at == NOW - timedelta(seconds=2)
    assert q.time_basis == EXPLICIT_OFFSET


@pytest.mark.parametrize("stamp", [
    naive(NOW - timedelta(seconds=2)),
    (NOW - timedelta(seconds=1, microseconds=250000)).replace(tzinfo=None).isoformat(),
])
def test_fresh_naive_utc_quote_is_accepted_and_marked(stamp):
    q = parse_fresh_quote(quote(stamp), instrument_id=1004, now=NOW)
    assert q.time_basis == NAIVE_AS_UTC
    assert q.observed_at.tzinfo is timezone.utc
    assert 0 <= (NOW - q.observed_at).total_seconds() <= MAX_QUOTE_AGE_SECONDS


@pytest.mark.parametrize("offset", [timedelta(hours=1), timedelta(hours=-4),
                                    timedelta(hours=5, minutes=45), timedelta(minutes=30),
                                    timedelta(minutes=-30), timedelta(hours=-1)])
def test_naive_local_time_from_any_real_non_utc_zone_is_rejected(offset):
    # A genuinely fresh quote written as naive *local* wall time in a non-UTC zone.
    local_wall = (NOW - timedelta(seconds=2) + offset).replace(tzinfo=None).isoformat()
    with pytest.raises(EtoroDemoOrderError, match="stale or future-dated"):
        parse_fresh_quote(quote(local_wall), instrument_id=1004, now=NOW)


@pytest.mark.parametrize("date", [
    naive(NOW - timedelta(seconds=MAX_QUOTE_AGE_SECONDS + 1)),                 # stale naive
    (NOW - timedelta(seconds=MAX_QUOTE_AGE_SECONDS + 1)).isoformat(),          # stale aware
    naive(NOW + timedelta(seconds=MAX_QUOTE_SKEW_SECONDS + 1)),                # future naive
    (NOW + timedelta(seconds=MAX_QUOTE_SKEW_SECONDS + 1)).isoformat(),         # future aware
])
def test_stale_and_future_quotes_still_fail_closed(date):
    with pytest.raises(EtoroDemoOrderError, match="stale or future-dated"):
        parse_fresh_quote(quote(date), instrument_id=1004, now=NOW)


@pytest.mark.parametrize("date", ["", "not-a-date", "2026-13-40T25:61:00", "18:01:17",
                                  "2026-10-23", None, 1761242477, 1761242477.0,
                                  ["2026-10-23T18:01:17"]])
def test_malformed_or_wrongly_typed_quote_time_is_rejected(date):
    with pytest.raises(EtoroDemoOrderError, match="invalid"):
        parse_fresh_quote(quote(date), instrument_id=1004, now=NOW)


def test_naive_local_clock_is_refused():
    with pytest.raises(EtoroDemoOrderError, match="clock"):
        parse_fresh_quote(quote(naive(NOW)), instrument_id=1004, now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("fmt", ["{d}T{t}.1234567", "{d} {t}.1234567", "{d}t{t}", "{d}T{t}"])
def test_dotnet_style_naive_stamps_parse(fmt):
    moment = NOW - timedelta(seconds=3)
    stamp = fmt.format(d=moment.strftime("%Y-%m-%d"), t=moment.strftime("%H:%M:%S"))
    q = parse_fresh_quote(quote(stamp), instrument_id=1004, now=NOW)
    assert q.time_basis == NAIVE_AS_UTC and 2 < (NOW - q.observed_at).total_seconds() <= 3
