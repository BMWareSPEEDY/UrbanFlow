# `web/` — UrbanFLOW Command Center (React + TS + deck.gl)

Decision D-17. Builds into `../static/command/` and is served by Flask, so the demo is still
`python app.py` — **no Node required at demo time.**

## Commands

```bash
cd web
npm install          # once

npm run dev          # http://localhost:5173 — proxies /api/v1 → :8000 and /api → :5000
npm run build        # tsc -b && vite build → ../static/command/
npm run typecheck    # tsc -b --noEmit

node scripts/verify.mjs   # headless: console errors, no-scroll, FPS, screenshots
```

`verify.mjs` expects a served build. Either run `npm run dev`, or serve the built output:

```bash
npx vite preview --port 4173     # then node scripts/verify.mjs
```

Screenshots land in `../scratch/figures/`.

## What is real vs. synthetic right now

| Piece | Status |
|---|---|
| `src/lib/scoring.ts` | **Real.** Consequence score, band ladder, priorities, passability. Mirror of `command/triage.py` to be written — the constants must match. |
| `src/lib/mock.ts` | **Synthetic.** Five real Bengaluru catchments, real junction names from `app.py:740`, gaussian depth field driven by the rainfall slider. Replace `mockScene()` with a fetch to `/api/v1/scenario`. |
| Map layers | **Real** deck.gl `PathLayer` / `ScatterplotLayer`, OSM basemap via MapLibre (token-free). Edge geometry is straight lines here; production uses the graphml `geometry` polylines. |
| Fleet / ETA / routes | **Synthetic.** Module C and B do not exist yet. |
| Audit log | **Synthetic**, but append-only in shape and written by every user action. |

## Conventions

- Tokens live in `src/index.css` under `@theme`. Do not hard-code hex values in components.
- No colour literals for depth bands outside `scoring.ts` (`BAND_COLOR`).
- Numbers use the `.tnum` class so digits do not jitter as values update.
- The page must never scroll. Panels scroll internally.
