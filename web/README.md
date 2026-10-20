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
