# UrbanFLOW Command & Dispatch

Municipal flood command, resource directive generation, and public transit rerouting built on top of the frozen `HydroGINE-v5` (`EnsembleFloodPredictorV4`) hydraulic Graph Neural Network across five Bengaluru street networks (**12,436 junctions / 29,717 road edges**).

## What It Does

Instead of only predicting nodal flood depths, UrbanFLOW translates `HydroGINE-v5` depth predictions into two coordinated municipal workflows:

1. **Municipal Resource & Water-Asset Directives (`command/triage.py`, `command/fleet.py`):**
   - Operators configure starting shift inventory (`0–30` Mobile Pumps, `0–24` Underpass Barriers, `0–24` Traffic Wardens), target jurisdiction, storm intensity, and operating mode (`Normal` vs `Red-Alert`) at startup.
   - Scores every junction using the closed-form Consequence Score (`0.45 * Severity + 0.30 * Asset + 0.15 * Vulnerability + 0.10 * Network`), spatially deduplicates nearby flooded segments (`200 m` STRtree + union-find clustering), and outputs explicit **WHERE / WHAT / WHEN** deployment orders constrained to actual unit availability.
   - Tracks full unit state machines (`IDLE -> EN_ROUTE -> DEWATERING -> RETURNING -> IDLE`, plus a `60 s` barrier closure veto window), explicit shortage refusals (`no_unit`, earliest freeing unit & peak lead time), inter-catchment `+20 min` transfer penalties across disconnected Bengaluru catchments, and an append-only JSONL audit log (`data/command/logs/`).

2. **Public Transit & Bus Safety Rerouting (`command/transit.py`, `command/routing.py`):**
   - Monitors key Bengaluru BMTC commuter bus corridors (`500D`, `500A`, `201R`, `335E`, `356C`, `KIA-7A`) and any map-selected `Origin -> Destination` pair.
   - Compares **Flood-Naive paths (red)** against **HydroGINE Flood-Safe detours (emerald)** using vehicle clearance profiles (`bus`, `pump_truck`, `ambulance`, `fire_engine`, `warden`, `civilian`) while respecting active closed underpass barriers.

## Quickstart

```bash
# 1. Start the unified Command API & built Deck.gl frontend on :8000
.venv/bin/python -m command.app
# Open http://127.0.0.1:8000/

# 2. Or build UI & launch via helper script
./scripts/command/dev.sh

# 3. Verify original frozen predictor dashboard still runs independently
.venv/bin/python app.py

# 4. Run smoke test against running server
./scripts/command/smoke.sh
```

### Tests & Offline Evaluation

```bash
# Run Gate A–D & Loader Parity unit/API tests (24 tests)
.venv/bin/python -m unittest discover -s command/tests -v

# Run held-out EPA SWMM 5.2 baseline evaluation (writes scratch/evaluation/)
.venv/bin/python -m command.evaluate

# Frontend typecheck, build, and headless Playwright check
cd web && npm run typecheck && npm run build
```

## Architecture & Key Paths

- `command/` — standalone Decision & Dispatch backend (`config.py`, `loader.py`, `triage.py`, `routing.py`, `fleet.py`, `transit.py`, `state.py`, `audit.py`, `schemas.py`, `app.py`, `evaluate.py`).
- `web/` — React + TypeScript + Deck.gl + Tailwind CSS command UI compiled into `static/command/`.
- `data/command/` — pre-snapped municipal POIs (`pois.json`), 6 high-ground SCC depots (`depots.json`), percentile betweenness (`betweenness.json`), compact PyG graph cache (`pyg_bengaluru_50.pt`), and genuine EPA SWMM 5.2 node truth (`eval_swmm_truth.json`).
- Frozen unmodified files: `app.py`, `core/`, `graphs/`, `docs/`, `paper/`.

## Evaluated Performance (Held-Out EPA SWMM 5.2 Ground Truth)

Measured offline on held-out catchments (`whitefield`, `ecity`, `koramangala`) at dispatch budget `N = 12` against `swmm_depth >= 0.30 m` at critical municipal assets (`ASSET_WEIGHT >= 0.85`):

- **100 mm/hr:** Consequence Triage (`Ours`) reaches **Recall@12 = 0.750** vs Persistence `50 mm/hr` (`0.500`), Raw Depth Order (`0.000`), and Random Wet (`0.010`).
- **Spatial Deduplication (`95 mm/hr`, all 12,436 nodes):** `3,714` raw flooded nodes -> `3,463` eligible -> **`169` clustered directives** (`294 ms` cold 5-catchment triage on CPU, `30.65 ms` warm).
- **Routing (`koramangala`, 4,416 nodes):** `30.06 ms` for 20 flooded routes (`1.50 ms/route`).

## Disclosure & Known Limitations

- **Simulation vs Live Hardware:** All fleet counts, barrier closures, audit logs, and commuter bus corridors operate on an in-memory **SIMULATION** model — no real SCADA gates, pumps, or BMTC telematics feeds are connected.
- **Low-Rainfall Regime (`20 mm/hr`):** Minimal surface ponding yields zero held-out critical junctions `>= 0.30 m`, so ranking baselines tie at zero.
- **Extreme Cloudbursts (`>= 100 mm/hr`):** Frozen `HydroGINE-v5` under-predicts tail flood depths on severe cloudbursts (`32.2%` critical recall); enabling **Red-Alert Mode** lowers Barrier/Pump action triggers (`0.09 m` / `0.25 m`) to compensate defensively.
- **Disconnected Catchments:** Cross-catchment dispatches use an explicit `20.0 min` transfer penalty across an off-graph arterial corridor stub.
