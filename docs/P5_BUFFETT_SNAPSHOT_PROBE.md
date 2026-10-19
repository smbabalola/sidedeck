# P5 Buffett no-LLM snapshot construction diagnostic

This probe is intended for an **already independently validated** `filed_fundamentals.py`-compatible file. It is NOT a converter and deliberately does not treat `data/sofi-quarterly-coverage-v1.json` as a verified upstream financial snapshot. The SEC coverage file has only partial metrics and a different schema.

Command (from SideDeck checkout in PowerShell, where the separate upstream installation lives at `..\ai-hedge-fund`):

```powershell
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Resolve-Path ".\src").Path
    & "..\ai-hedge-fund\.venv\Scripts\python.exe" -m sidedeck.application.p5_buffett_snapshot_probe --fundamentals-json "PATH_TO_VALIDATED_FUNDAMENTALS.json" --ticker SOFI --as-of 2026-10-19
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
```

Do **not** replace the placeholder with the SEC quarterly coverage file: source record requirements differ. The probe parses the strict local fundamentals format, then invokes the installed `BuffettAgent.build_snapshot` with a local, read-only data client, without invoking `predict`, `make_llm`, FDClient or any broker. Snapshot status `CONSTRUCTED_UNVERIFIED` is a compatibility observation only. A failure returns `UNAVAILABLE` and a safe exception type.

Until the upstream Buffett scoring logic's actual required metric set is audited and a complete point-in-time dataset is independently validated, SideDeck must retain `buffett_ready=false`, `approved=false`, `broker_execution=DISABLED`. No real AI calls are authorized by this diagnostic.
