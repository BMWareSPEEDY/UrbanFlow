# `web/` — UrbanFLOW Command Center (React + TS + deck.gl)

I took Decision D-17 for this layer: it builds into `../static/command/` and is served by Flask, so my
demo is still `python app.py` — **no Node required at demo time.**

## Commands

```bash
cd web
npm install          # once

npm run dev          # http://localhost:5173 — proxies /api/v1 → :8000 and /api → :5000
npm run build        # tsc -b && vite build → ../static/command/
npm run typecheck    # tsc -b --noEmit

node scripts/verify.mjs   # headless: console errors, no-scroll, FPS, screenshots
```

`verify.mjs` expects a served build. I either run `npm run dev`, or serve the built output:

```bash
npx vite preview --port 4173     # then node scripts/verify.mjs
```

Screenshots land in `../scratch/figures/`.

## What is real vs. synthetic right now

| Piece | Status |
|---|---|
| `src/lib/scoring.ts` | **Real.** Consequence score, band ladder, priorities, passability. I still need to write the mirror of `command/triage.py` — the constants must match. |
| `src/lib/mock.ts` | **Synthetic.** Five real Bengaluru catchments, real junction names from `app.py:740`, gaussian depth field driven by the rainfall slider. I still replace `mockScene()` with a fetch to `/api/v1/scenario`. |
| Map layers | **Real** deck.gl `PathLayer` / `ScatterplotLayer`, OSM basemap via MapLibre (token-free). I draw edge geometry as straight lines here; production uses the graphml `geometry` polylines. |
| Fleet / ETA / routes | **Synthetic.** I have not built modules C and B yet. |
| Audit log | **Synthetic**, but append-only in shape and written on every user action. |

## Conventions

- I keep tokens in `src/index.css` under `@theme` and never hard-code hex values in components.
- I never use colour literals for depth bands outside `scoring.ts` (`BAND_COLOR`).
- I use the `.tnum` class for numbers so digits do not jitter as values update.
- The page must never scroll; I let panels scroll internally.
