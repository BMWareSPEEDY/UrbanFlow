# REFERENCE — Baseline System Snapshot

> **Snapshot date:** 2026-11-14. Read directly out of the working tree.
> **Purpose:** every claim the Command Layer makes about "the existing system" must trace to this
> file or be re-read from source. Re-verify numbers before a demo.

---

## 1. Repository state

| Fact | Value |
|---|---|
| Path | `~/PycharmProjects/UrbanFlow-VERITAS AI Hackathon` |
| **Git repository** | **No — the directory is not under version control** |
| Entry point | `app.py` (single file, ~69 KB, ~1,500 lines) |
| Framework | **Flask 3.1.3**, server-rendered Jinja `templates/index.html` |
| Python | 3.13 virtualenv at `.venv` |
| Production source set (per `docs/PRODUCTION.md`) | `app.py`, `templates/`, `static/`, `core/production_v4.py`, 3 legacy `core/train_*.py` |
| Everything else | ~250 scripts, older checkpoints, docs, PDFs — iteration history |

## 2. Existing HTTP API (all on the Flask app)

| Route | Method | Line | Purpose |
|---|---|---|---|
| `/` | GET | 675 | Dashboard (`templates/index.html`) |
| `/presentation` | GET | 680 | Research deck view |
| `/download/deck` | GET | 685 | PPTX download |
| `/download/google-slides-script` | GET | 693 | Slides script download |
| `/api/regions` | GET | 701 | Region catalogue (`REGIONS`) |
| `/api/model-info` | GET | 706 | Architecture string, device, param count |
| `/api/graph-data` | GET | 720 | Nodes + edges + bounds for a region |
| `/api/predict` | POST | 911 | **The inference contract** — depths for every node |
| `/api/storm-playback` | POST | 1080 | 12-frame storm time series |
| `/api/swmm-compare` | POST | 1193 | SWMM vs GNN comparison |
| `/api/mitigation` | POST | 1273 | Mitigation scenarios |
| `/api/historical-validation` | GET | 1384 | Oct-2024 Bengaluru incident validation |
| `/api/model-card` | GET | 1483 | Model card metadata |

There is **no** routing, fleet, POI, dispatch-queue, or audit endpoint. The entire Command Layer is
greenfield.

## 3. Catchments (16 regions in `REGIONS`, `app.py:57`)

| Key | Name | Graph file | Nodes | Edges |
|---|---|---|---|---|
| `hsr` | HSR Layout (Residential Hub) | `bengaluru_complete_graph.graphml` | 1,379 | 3,733 |
| `bellandur` | Bellandur & ORR (Lake Basin) | `bengaluru_bellandur_graph.graphml` | 1,507 | 3,197 |
| `whitefield` | Whitefield (ITPB Corridor) | `bengaluru_whitefield_graph.graphml` | 1,797 | 3,994 |
| `ecity` | Electronic City (Tech Corridor) | `bengaluru_ecity_graph.graphml` | 3,337 | 7,610 |
| `koramangala` | Koramangala & Indiranagar | `bengaluru_koramangala_graph.graphml` | 4,416 | 11,183 |
| **Bengaluru subtotal** | | | **12,436** | **29,717** |
| `tokyo` | Tokyo Metropolitan | `city_tokyo_graph.graphml` | 13,173 | — |
| `london` | London Thames | `city_london_graph.graphml` | 10,528 | — |
| `bangkok` | Bangkok Chao Phraya | `city_bangkok_graph.graphml` | 10,399 | — |
| `hongkong`, `singapore`, `paris`, `nyc`, `chicago`, `berlin`, `mumbai`, `delhi` | see `REGIONS` | `city_*_graph.graphml` | — | — |

`graphs/` holds 65 `.graphml` files; only the 16 referenced by `REGIONS` are production.
The **76,316-node** figure quoted in the docs and the paper is the **sum across all 16 catchments**,
not a single map. The 5 Bengaluru catchments total **12,436** — which matches
`paper/UrbanFLOW_Research_Paper_Master_Technical_Dossier.md` exactly.

## 4. `/api/predict` — the contract the Command Layer consumes

**Request**

```json
{ "region": "hsr", "rainfall_mmhr": 95, "duration_min": 60 }
```

Clamps enforced in `run_region_inference` (`app.py:848`): **rainfall 20–300 mm/hr**, **duration
15–120 min**. Values outside are silently clamped.

**Response (abridged)**

```json
{
  "status": "success",
  "region": "hsr",
  "metrics": {
    "gnn_time_ms": 12.4, "swmm_time_ms": 14233.0, "speedup_ratio": 1148.0,
    "total_flooded_nodes": 412, "total_nodes": 1379, "flooded_pct": 29.9,
    "max_depth_m": 0.71, "avg_depth_m": 0.084, "total_volume_m3": 57932.0,
    "basement_risk_count": 63, "rainfall_mmhr": 95.0, "duration_min": 60.0
  },
  "nodes":            [ /* ALL nodes, see field table */ ],
  "risk_nodes":       [ /* depth > 0.08 m, sorted desc, TRUNCATED TO 30 */ ],
  "basement_alerts":  [ /* is_basement && depth > 0.12 m */ ],
  "dispatch_recommendations": [ /* max 6, text strings */ ],
  "rwa_alert":        { /* resident-welfare-association bulletin text */ }
}
```

**Per-node fields** (`nodes[]`, `app.py:981`)

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | str | graphml node id | |
| `junction_name` | str | hand-written name table (`JUNCTION_NAMES`) | ~15 names per region, then generated fallback |
| `gnn_depth` | float (m) | model, rounded 4dp | **the primary signal** |
| `swmm_depth` | float (m) | stored SWMM reference, scaled by rainfall/duration | **display only — never fed back** |
| `risk_level` | enum | `Safe` / `Watch` / `Advisory` / `Critical` | see thresholds |
| `is_basement` | bool | `impervious_ratio > 0.4 and elevation < 882.0` | Bengaluru-tuned heuristic |
| `depth_cm` | float | `gnn_depth * 100` | |
| `elevation` | float | DEM | |
| `upstream_slope` | float | `compute_upstream_slope()` | |
| `flow_dx`, `flow_dy` | float | `compute_flow_direction()` | |

`risk_nodes[]` adds: `impervious_ratio`, `error_cm`, `status` (`MATCH` / `OVER` / `UNDER`,
MATCH if `|gnn − swmm| < 0.15 m`).

**Graph payload** (`/api/graph-data`): `nodes[]` carry `x, y, lat, lng, elevation,
impervious_ratio, manning_n, swmm_depth, is_basement, upstream_slope, flow_dx, flow_dy`;
`edges[]` carry `u, v, length` (metres), `grade`. Edge keys are **implicitly available** in the
NetworkX MultiDiGraph (`REGION_CACHE[key]['graph']`) but not serialised.

## 5. Thresholds as they exist in code (do not guess these)

| Where | Thresholds |
|---|---|
| `risk_level` (`app.py:970`) | `> 0.05` Watch · `> 0.15` Advisory · `> 0.30` Critical |
| `risk_nodes` filter (`app.py:996`) | `> 0.08` m |
| `total_flooded_nodes` (`app.py:967`) | `> 0.05` m |
| `basement_alerts` (`app.py:1013`) | `is_basement && > 0.12` m |
| `generate_dispatch_recommendations` (`app.py:247`) | `≥ 0.35` CRITICAL pump · `≥ 0.15` HIGH crew · `≥ 0.05` ADVISORY monitor; capped at 6 |
| Hazard definition in the research claims | `≥ 0.15` m (hazard) · `> 0.30` m (critical) |
| `swmm_depth` status MATCH | `|Δ| < 0.15` m |

## 6. Benchmark facts safe to quote on stage

Source: `docs/benchmark_report.md`, `docs/IRIS_Portal_Synopsis.md`,
`paper/UrbanFLOW_Research_Paper_Master_Technical_Dossier.md`.

| Metric | 50 mm/hr reference | Literal 100 mm/hr stress |
|---|---|---|
| Nodes | 76,316 (16 catchments) | 76,316 |
| MAE | **2.44 cm** | **17.93 cm** |
| RMSE | 9.29 cm | 52.17 cm |
| NSE | **0.9128** | — |
| ≤15 cm agreement | 96.7 % | 79.4 % |
| Hazard F1 (≥0.15 m) | **90.8 %** | **86.4 %** |
| Critical precision (>0.30 m) | — | 97.8 % |
| **Critical recall (>0.30 m)** | — | **32.2 %** |
| Bengaluru-5 F1 | — | 78.9 % (recall 43.2 %, MAE 17.27 cm) |
| HTTP latency | 32.0–169.8 ms, **avg 85.5 ms** | same |
| Speedup vs SWMM 5.2 | ~1,310×–8,690× | same |

**The 32.2 % critical recall is the empirical justification for Red-Alert Conservative Mode.**
The model under-predicts depth in the extreme tail; lowering the trigger threshold is the
compensating control. This is a defensible engineering argument, not a hack.

## 7. Frontend as it stands

| Fact | Value |
|---|---|
| Templating | Jinja2, `templates/index.html` (635 lines) |
| Scripts | Vanilla JS, `static/js/main.js` (1,252 lines), no modules, no bundler |
| Styles | `static/css/styles.css` (1,539 lines), hand-written |
| Map | **Leaflet 1.9.4** (unpkg CDN) |
| Charts | Chart.js 4.4.1 (jsDelivr CDN) |
| React / TypeScript / Tailwind / deck.gl / Mapbox | **None present** |
| Build step | **None** — Flask serves `static/` directly |
| External network at runtime | Required (unpkg + jsDelivr CDN) |

## 8. Dependencies relevant to the new work

Already installed: `networkx 3.6.1`, `shapely 2.1.2`, `geopandas 1.1.4`, `osmnx 2.1.1`,
`pyproj 3.7.2`, `pydeck 0.9.3`, `numpy 2.5.1`, `pandas 3.0.5`, **`starlette 1.4.0`**,
**`uvicorn 0.52.1`**, `pyswmm 2.1.0`, `torch 2.13.0+cu126`, `torch-geometric 2.8.0.post1`.

**Not installed: `fastapi`.** The intended decision layer is therefore buildable on Starlette +
uvicorn without adding a framework, or `fastapi` must be added.

## 9. Conflicts between the brief and the code

| # | Brief says | Code does | Consequence |
|---|---|---|---|
| C-1 | Rainfall slider `10–120 mm/hr` | clamps `20–300` | 10–19 mm/hr requests silently become 20. Slider must be aligned or the clamp relaxed. |
| C-2 | Duration `15–180 min` | clamps `15–120` | 121–180 min silently becomes 120. |
| C-3 | Watch `0.08–0.14`, Barrier `0.15–0.29`, Pump `≥0.30` | `risk_level` at `0.05/0.15/0.30`; dispatch at `0.05/0.15/0.35` | Three different threshold ladders exist today. The Command Layer must own **one** ladder. |
| C-4 | Red-Alert lowers hazard trigger to `0.08–0.10` | no such mode | New feature; must not mutate `app.py` response semantics. |
| C-5 | "76,316 street junctions" as the live map | 1,379–13,173 per catchment | 76,316 is the benchmark total, not one scene. Say "12,436 in the Bengaluru scene, 76,316 benchmarked globally". |
| C-6 | FastAPI + React + TS + Tailwind + Mapbox/deck.gl | Flask + vanilla JS + Leaflet | Requires a build toolchain that does not exist yet. See decision D-02. |
| C-7 | GeoJSON leaves the model | `/api/predict` returns **JSON**, not GeoJSON | Trivial: either add a GeoJSON serialiser or consume the existing JSON. |
| C-8 | "automated underpass gate lock" | no actuator integration exists | Must be modelled and labelled as **simulated** actuation. |
| C-9 | `risk_nodes` as the alert source | truncated to **30** rows | A queue built on `risk_nodes` silently loses alerts when >30 nodes exceed 0.08 m (it can be 400+). Must triage from `nodes[]`. |
