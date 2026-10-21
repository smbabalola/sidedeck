# SD-024 ETF distribution evidence boundary

The new `sd024_etf_distribution_evidence` module is an offline, fail-closed
parser for SPY/QQQ corporate-action records. It accepts only owner-supplied
licensed evidence or a clearly identified public source, validates split ratios,
distribution amounts, ex-date/payment-date ordering and duplicate records, and
rejects authenticated/paid-source labels.

The parser does not fetch data and no ETF records were available in the
approved local evidence set. Therefore SPY/QQQ corporate-action status remains
`NOT_ASSESSED`. A split-adjusted close remains a price-only benchmark; a total-
return benchmark requires complete distributions and an explicit reinvestment
convention. Broker execution remains disabled.

Evidence: `src/sidedeck/application/sd024_etf_distribution_evidence.py` and
`tests/test_sd024_etf_distribution_evidence.py`.
