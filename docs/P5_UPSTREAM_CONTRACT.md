# P5: installed AI Hedge Fund contract verification (no LLM or orders)

The existing SideDeck `hedge_fund_bridge.py` expects the older upstream interfaces `hedge_fund.signals.buffett.BuffettAgent`, `hedge_fund.data.models.FinancialMetrics`, `hedge_fund.data.client.FDClient`, and `hedge_fund.llm.make_llm`. The current upstream repository has evolved, so these interfaces must be verified **in the particular upstream virtual environment actually installed on your machine**, rather than assumed from the latest GitHub main branch.

Run in PowerShell from the SideDeck checkout, using the existing upstream environment (adjust path if different):

```powershell
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Resolve-Path ".\src").Path
    & "..\ai-hedge-fund\.venv\Scripts\python.exe" -m sidedeck.application.p5_upstream_contract
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
```

The output lists whether the four required modules and symbols exist, and the available `FinancialMetrics` model field names when exposed through Pydantic. This does **not** load credentials, call an LLM, create a strategy signal, retrieve market data or touch a broker.

If `installed_upstream_legacy_bridge_contract` is `MISSING`, do **not** try an authenticated Buffett run. Reconcile the exact installed upstream version/API first, then implement a version-specific research adapter with contract tests.

The 20 matched SEC periods are **source coverage**, not 20 validated upstream `FinancialMetrics` records. The Buffett dataset still requires correct, contemporaneous margins, growth, debt and valuation measures. Never fill these with synthetic zeroes or rename generic liabilities as debt. P5 research and broker execution remain NO-GO.
