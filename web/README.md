# SideDeck Demo dashboard (Tailwind CSS)

Standalone React + Vite + Tailwind CSS 3 prototype. It is intentionally **static/read-only**: the displayed count and reconciliation states reflect the owner's sanitized 20 Oct 2026 baseline; there is no API endpoint, credential handling, local database reader, or broker order control. Monetary values are withheld.

## Development

```powershell
cd web
npm install
npm run dev
```

Open the local Vite URL. Run `npm run build` to type-check and compile the UI. Requires Node.js 20+.

## Next integration gate

Develop a local-only, authenticated, read-only backend that exposes a carefully filtered `DemoReconciliation` summary. Do not serve SQLite or any raw eToro snapshot to the browser. Do not add browser-stored API keys. The backend must distinguish stale snapshots, fail closed on discrepancies, and return monetary values only after real-response validation and explicit owner approval. No portfolio order routes are authorized.

## Local baseline API (new)

From the repository root, in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_demo_dashboard_api --db "data\etoro_demo.sqlite3"
```

Then run `npm run dev` in `web`. Vite proxies only `/api` to the loopback Python API. No eToro credentials or internet access are used by this service. It opens the existing SQLite database in read-only mode; if it cannot read a valid baseline it returns HTTP 503. The response contains only baseline timestamp, counts and explicit unavailable statuses—never raw broker IDs, monetary values or a false live reconciliation. Do not expose either development server on public interfaces.

Run `python -m pytest tests/test_p5_demo_dashboard_api.py -q` and `npm run build` for verification.
