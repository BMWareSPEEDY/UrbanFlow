# UrbanFLOW — Command & Dispatch
## Detailed implementation plan

**Submission target:** Veritas AI International High School Hackathon 2026 — Track 4.3: AI + Climate
**Hard deadline:** Sun 15 Nov 2026, 11:59 PM ET = **Mon 16 Nov 2026, 10:29 AM IST**
**Document written:** Sat 14 Nov 2026
**Status of this document:** execution plan. Architecture rationale lives in
`scratch/specs/UF-COMMAND-V1__municipal-flood-command-and-dispatch-spec.md`; this file is the
ordered work list, with file paths, function signatures, formulas, acceptance gates and the
submission checklist.

---

## 0. Read this section first

### 0.1 What we are building, in one sentence

A **municipal flood command centre**: it takes the frozen HydroGINE-v5 depth predictions for the five
Bengaluru catchments, converts them into a ranked, consequence-scored dispatch queue, calculates a
**flood-safe route** for each response unit, and gives the operator a real resource-allocation problem
— because the pump/barrier/warden fleet is entered at startup and is smaller than the number of
critical nodes.

### 0.2 What already exists and must not change

| Asset | Status |
|---|---|
| `app.py`, `core/`, `docs/`, `paper/` | **FROZEN.** No edits without explicit approval. Prediction semantics, benchmarks and paper stay byte-identical. |
| `graphs/*.graphml` | Read-only input. |
| `models/` | Read-only input. |
| `static/command/`, `web/` | **Ours.** Built this weekend. Safe to rewrite. |
| `scratch/` | **Ours.** All briefs, decisions, specs, figures. |

### 0.3 The one thing that needs your decision before we submit

The repository is a copy of a project that existed **before** the hacking window. The hackathon rules
say a team cannot extend a project built before the hackathon, and cannot submit someone else's
project. This is a compliance question, not a technical one, and only you can answer it.

Three honest paths:

1. **Disclose and reframe (recommended).** State plainly in the write-up: *"The depth-prediction model
   is prior work by the same author, treated exactly like a pretrained model that we did not train
   this weekend. Everything submitted — triage, routing, fleet state machine, API, dashboard, audit
   trail, evaluation against baselines — was written during the hacking window."* Cite it in Sources.
   This is defensible: the brief permits pretrained models and says AI must be *central*, which it is,
   because the entire product is a decision layer built on top of that model's output.
2. **Rebuild the predictor from scratch this weekend.** Not possible in the remaining hours, and would
   produce a worse, less honest result.
3. **Change project.** Would waste the work already done.

Decision needed: **1, 2, or 3.** Path 1 changes the write-up's framing section only; it does not change
any code. If you pick 1, the paragraph above goes into the write-up verbatim.

### 0.4 Definition of done

- [ ] `python app.py` serves the original dashboard unchanged.
- [ ] `python -m command.app` serves the command API on `:8000`, health check passes.
- [ ] All five catchments load; node counts match `1,379 / 1,507 / 1,797 / 3,337 / 4,416 = 12,436`.
- [ ] Setup screen asks for fleet counts and those exact numbers drive the queue, KPIs and audit log.
- [ ] Dispatching unit 13 when 12 exist produces an explicit *"no unit available"* event, not a lie.
- [ ] A measurable baseline comparison exists on held-out data, and we report where we lose.
- [ ] Repo is public and readable logged-out.
- [ ] ~1 page write-up using the official template.
- [ ] Optional: ≤2 min demo video.

---

## 1. Current state — verified, not assumed

Verified on 2026-11-14 by running the commands, not by reading docs.

| Thing | Verified value |
|---|---|
| Node / npm / pnpm | 25.9.0 / 11.13.0 / present |
| Python env | `.venv`, networkx 3.6.1, shapely, geopandas, osmnx present |
| `fastapi` | **NOT installed.** Starlette 1.4 + uvicorn 0.52 are. |
| Flask | Installed (that is what `app.py` runs). |
| Frontend build | `web/` builds in ~1.9 s → `static/command/` (1.04 MB JS, 300 kB gzip) |
| Headless check | 0 console errors, 0 page scroll at 1920×1080 and 1366×768 |
| Bengaluru scope | 5 catchments, **12,436 nodes / 29,717 edges**, graphs are **disconnected** |
| Benchmark total | 16 catchments / 76,316 nodes — **never quote this as the live scene** |
| `app.py` anchors | `JUNCTION_NAMES` line 740 · thresholds lines 970/996/1013 · `risk_nodes[:30]` line 1074 |
| Git | `main` = `2b16dec` baseline; `command-layer` = `e6ff2d8` web shell |

**Safe-to-quote model benchmarks** (from the existing benchmark JSON, do not re-derive):

| Rainfall | MAE | NSE | F1 | Critical precision | Critical recall | Within 15 cm |
|---|---|---|---|---|---|---|
| 50 mm/hr | 2.44 cm | 0.9128 | 90.8 % | — | — | 96.7 % |
| 100 mm/hr | 17.93 cm | — | 86.4 % | 97.8 % | **32.2 %** | — |

API latency measured 32–169.8 ms, mean 85.5 ms.

The **32.2 % critical recall at 100 mm/hr** is the single most important number in this project, and
the entire Red-Alert design exists because of it. Lead with it.

### 1.1 Known open work in `web/` (10 minutes)

The setup screen is written (`web/src/components/SetupScreen.tsx`) and `App.tsx` already passes
`operator` and `onReconfigure` into `ControlBar`, and `fleet={{pumps,barriers,wardens}}` into
`DispatchQueue`. `DispatchQueue` is updated. **`ControlBar.tsx` is not** — it still declares neither
prop, so the tree does not typecheck. Task 0 below fixes exactly that.

---

## 2. Scope and the resource model

### 2.1 Scope

Five Bengaluru catchments: `koramangala` (4,416), `ecity` (3,337), `whitefield` (1,797),
`bellandur` (1,507), `hsr` (1,379). Total **12,436 nodes**.

The graphs are **disconnected** — separate `.graphml` files sharing no node IDs. Consequences:

1. Triage runs per catchment, five queues merged by consequence score.
2. Fleet is **city-wide**, so a unit can cross catchments — which requires an explicit stub leg
   (§7.2), because Dijkstra cannot cross a graph that has no connecting edges.
3. KPIs are city-wide sums; the catchment selector is a **filter**, not a mode switch.

### 2.2 The fleet, and why the user enters it

A "pump" is a real municipal object: a trailer-mounted diesel pump set, 1,000–3,000 L/min, towed to a
flooded underpass, hoses dropped into the standing water and run out to the nearest storm drain, canal
or lake outfall. BBMP and the fire service operate them. It is the primary physical remedy for an
underpass, because water will not drain on its own once the outfall is surcharged.

So a unit is **a location, a state, and a clock**:

| Property | Value |
|---|---|
| Depots | 6, one or two per catchment |
| States | `IDLE → EN_ROUTE → ON_SITE → DEWATERING → RETURNING → IDLE` |
| Speed | 0.8 × road speed |
| Impassable at | standing water ≥ 0.25 m (pump truck), 0.20 m (warden) |
| Work time | ~45–90 simulated minutes to clear a 0.30 m node |
| Barriers | bound to one underpass POI each; triggered by depth, operator has a 60 s veto |
| Wardens | 2 personnel + light vehicle; diversion and cordon |

**At 95 mm/hr across five catchments, triage flags far more than twelve critical nodes.** The operator
therefore cannot do everything, and the product exists to make the choice defensible. That is the
entire thesis. If the fleet is large enough to cover every alert, the product has no tension — so the
setup screen must also show the operator when they have chosen an unrealistically large fleet.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 3 — Command Centre UI                    DONE (mock data)      │
│ React 19 + TS + Vite + deck.gl + Tailwind → static/command/          │
│ Served by Flask; `python app.py` stays the single demo command       │
└───────────────────────────────▲──────────────────────────────────────┘
                                │ JSON /api/v1/*
┌───────────────────────────────┴──────────────────────────────────────┐
│ Layer 2 — Command API                          TO BUILD              │
│ command/app.py — Flask on :8000, zero new dependencies               │
│ session · scenario · dispatch · dismiss · tick · log                 │
└───────────────────────────────▲──────────────────────────────────────┘
                                │
┌───────────────────────────────┴──────────────────────────────────────┐
│ Layer 1 — Decision core                        TO BUILD              │
│ triage.py    nodes → consequence-scored, deduped alerts               │
│ routing.py   depot → node flood-safe path, ETA, detour               │
│ fleet.py     inventory, state machine, greedy feasible assignment    │
│ audit.py     append-only JSONL, fsync per event                      │
└───────────────────────────────▲──────────────────────────────────────┘
                                │ read-only
┌───────────────────────────────┴──────────────────────────────────────┐
│ Layer 0 — Frozen predictor                     DO NOT TOUCH          │
│ app.py · core/production_v4.py · models/ · graphs/                   │
└──────────────────────────────────────────────────────────────────────┘
```

### Why Flask on :8000 and not FastAPI

`fastapi` is not installed. Starlette and uvicorn are, but installing FastAPI adds a dependency and a
new failure mode at 3 AM. Flask is already the project's web framework, the team already knows it, and
nothing in this API needs async. So: a **second, standalone Flask app** in `command/app.py` on port
8000. The original `app.py` is never imported, never modified, never even started by the demo if you
don't want to.

If `flask-cors` is missing, add the header in a 3-line `after_request` hook. Do not install anything.

---

## 4. Target repository layout

```
command/                        # NEW — the entire weekend contribution
  __init__.py
  app.py                        # Flask API, :8000
  config.py                     # single source of truth for every constant
  loader.py                     # graphs, POIs, junction names — cached singletons
  triage.py                     # Module A
  routing.py                    # Module B
  fleet.py                      # Module C
  audit.py                      # append-only JSONL
  evaluate.py                   # baseline comparison (CLI)
  scenarios.py                  # named storm presets
  tests/
    test_triage.py
    test_routing.py
    test_fleet.py
    test_parity.py              # node counts must match app.py
data/command/
  fleet.json                    # default inventory seed
  pois.json                     # OSM POIs + name-derived fallback
  betweenness.json              # cached normalised network criticality per catchment
  logs/audit-YYYYMMDD.jsonl     # runtime, gitignored
web/
  src/components/ControlBar.tsx # Task 0 fix
  src/lib/api.ts                # NEW — typed fetch layer
  src/state/session.ts          # NEW — replaces mock
static/command/                 # build output, committed
scratch/
  specs/                        # existing
  decisions/                    # existing
  figures/                      # screenshots
  evaluation/                   # NEW — generated baseline tables for the write-up
```

---

## 5. Module A — Triage (`command/triage.py`)

### 5.1 Purpose

Turn a depth field into a **ranked queue of decisions**, not a ranked list of pixels.

### 5.2 Inputs

Per catchment: node id, lon/lat, predicted `depth_m`, elevation, and the node's assets. Depth comes
from the frozen model exactly as `app.py` produces it today — triage never re-predicts.

### 5.3 Formula

```python
S = clamp01((depth_m - 0.05) / (0.40 - 0.05))        # severity, linear in the 5–40 cm band
A = ASSET_WEIGHT[primary_asset]                       # 1.00 underpass … 0.25 street
V = clamp01(0.45 * (depth_m > 0.18)                  # impassable for most vehicles
          + 0.35 * min(1.0, depth_m / 0.30)          # proportional sink
          + 0.20 * sink_ratio)                        # local drainage deficit, 0..1
N = betweenness_normalised[node]                      # cached; 0 if absent
CS = round(100 * (0.45*S + 0.30*A + 0.15*V + 0.10*N), 1)
```

Weights sum to 1.0 and are **asserted** in `config.py`. Depth dominates, but cannot override asset
criticality — that inversion (a 24 cm hospital access road beating a 41 cm residential lane) is the
demo's proof that this is a decision tool and not a threshold filter.

### 5.4 Threshold ladder — one place only

`command/config.py`:

```python
THRESHOLDS = {
    "normal":    {"alert_floor": 0.08, "barrier": 0.15, "pump": 0.30},
    "red_alert": {"alert_floor": 0.08, "barrier": 0.09, "pump": 0.25},
}
```

Red-Alert lowers the **action** triggers and leaves the alert floor alone. Rationale: the measured
failure is missed deep nodes (32.2 % critical recall), not false alarms (97.8 % precision). Aggression
belongs on the cheap reversible action (barrier), less on the scarce one (pump).

The existing ladders inside `app.py` (lines 970/996/1013) are **not** touched. They serve the old
dashboard. `config.py` is the new ladder and the UI legend reads from it.

### 5.5 Deduplication — the rule that matters most

A single underpass spans dozens of nodes. Naive `depth >= 0.08` produces 40 alerts for one ramp and
the operator sends three pumps to one place.

```python
# 1. collect all nodes above alert_floor
# 2. build shapely Point per node
# 3. cluster with a 200 m radius (STRtree, union-find)
# 4. within a cluster keep the max-CS node as the representative
# 5. attach affected_nodes = len(cluster), extent_m = cluster diameter
# 6. barrier actions bind to the cluster's underpass POI, not to a node
```

Only unclustered street nodes fall back to per-node alerts. Measure the effect and put it in the
write-up: *"dedup reduced 412 raw threshold crossings to 27 dispatches on the 95 mm/hr scenario."*
That single number is worth more than any threshold tuning.

### 5.6 Output contract

```json
{
  "alert_id": "hsr-c04",
  "catchment": "hsr",
  "representative_node": "hsr-1832",
  "name": "Silk Board Underpass Ramp",
  "depth_m": 0.31,
  "score": 78.4,
  "priority": "P1",
  "band": "pump",
  "components": {"S": 0.74, "A": 1.0, "V": 0.71, "N": 0.62},
  "assets": ["underpass"],
  "affected_nodes": 38,
  "action": "pump_dispatch",
  "time_to_peak_min": 22
}
```

### 5.7 Time-to-peak

The existing `/api/storm-playback` gives 12 frames. Use it: TTP = index of the frame with max depth for
that node, × frame spacing. **No change to `app.py`.** If a dedicated endpoint is ever wanted, it is
~30 lines and needs your explicit approval because it edits the frozen file — **not required for V1**.

### 5.8 Acceptance gate A

- Parity: per-catchment node counts equal `1,379 / 1,507 / 1,797 / 3,337 / 4,416`.
- Determinism: same input → byte-identical output, twice.
- Speed: full five-catchment triage + clustering **< 400 ms**.
- Assert `sum(WEIGHTS.values()) == 1.0` at import.
- Golden test: one hand-computed node reproduces its score to 0.01.

---

## 6. Module B — Routing (`command/routing.py`)

### 6.1 Edge cost with water

```python
def passability(depth_m, vehicle):          # 1.0 = free flow, 0 < f < 1 = slowed, inf = blocked
    d_safe = 0.05
    d_imp  = {"pump_truck": 0.25, "warden": 0.20, "ambulance": 0.30, "civilian": 0.20}[vehicle]
    if depth_m <= d_safe:  return 1.0
    if depth_m >= d_imp:   return float("inf")
    return ((d_imp - depth_m) / (d_imp - d_safe)) ** 1.5

edge_cost = length_m / (speed_mps * passability(depth_m, vehicle))
```

Dijkstra on `edge_cost`. A flooded edge is expensive before it is impossible — that is what produces
the "standard route 9 min / flood-safe route 11 min" comparison the demo hangs on. If no path exists
at all, return `{"reachable": false, "reason": "all corridors >0.25 m"}` and let the UI say so.

### 6.2 Inter-catchment legs (required)

```python
if origin_region != target_region:
    stub_km   = haversine(centroid[origin], centroid[target]) / 1000.0
    stub_min  = stub_km * 1000.0 / 12.0 / 60.0          # 12 m/s ≈ 43 km/h arterial
    total_min = (route_to_catchment_exit
                 + stub_min
                 + route_from_catchment_entry
                 + config.INTER_CATCHMENT_PENALTY_MIN)   # 20 min
    inter_catchment = True
```

Rules: always drawn dashed, always `inter_catchment: true` in payload and audit log, always shows the
20-minute jurisdiction penalty as its **own line item**, never folded into the total. The penalty is a
real-world cost (fuel, handover, home-ward expectation) and it keeps intra-catchment units naturally
preferred.

### 6.3 Acceptance gate B

- Route from a depot to a known node returns a polyline whose endpoints are the depot and the node.
- Raising depth on the only corridor makes `reachable` flip to false.
- An inter-catchment request returns `inter_catchment: true` and a non-zero penalty line.
- 100 routes in **< 250 ms** total (graphs cached in memory).

---

## 7. Module C — Fleet (`command/fleet.py`)

### 7.1 Inventory comes from the operator

`data/command/fleet.json` holds *defaults*; the **session** overrides them with the numbers typed on the
setup screen. Server-side validation: `1 ≤ pumps ≤ 30`, `0 ≤ barriers ≤ 24`, `0 ≤ wardens ≤ 24`.
If a fleet is large enough to cover every P1/P2 alert, return a `fleet_oversized: true` flag so the UI
can say *"this configuration removes the dispatch problem — realistic municipal pools are 8–15."*

### 7.2 State machine

```
IDLE ──dispatch──> EN_ROUTE ──arrive──> ON_SITE ──start──> DEWATERING
                                                              │
IDLE <──release── RETURNING <──complete───────────────────────┘

BARRIER:  IDLE ──depth trigger──> PENDING_CLOSE ──60 s no veto──> CLOSED
                                  ^ operator veto → STANDBY
```

Every transition writes an audit event. Work time: `45 + 45 * (depth_m / 0.30)` minutes, clamped.

### 7.3 Assignment — greedy nearest feasible, explicitly not a VRP

```python
def assign(alert, fleet):
    candidates = [u for u in fleet
                  if u.status == "IDLE" and u.capability == alert.action.capability]
    feasible = [(u, route(alert)) for u in candidates if route.reachable]
    if not feasible:
        return Infeasible(reason="no_unit",
                          nearest_free=min(candidates, key=distance),
                          nearest_eta_min=...,
                          peak_in_min=alert.time_to_peak_min)
    return min(feasible, key=lambda ur: ur.route.eta_min)
```

Deterministic, explainable in one sentence on stage, < 1 ms. A solver would be defensible engineering
and indefensible demo pacing.

### 7.4 The scarcity path (do not skip this)

When `assign` returns `Infeasible`, the UI must show, in words:

> *No pump available. Nearest free unit is 38 min away; peak is in 22 min. Escalate to mutual aid or
> accept inundation.*

This is the moment the product earns its existence. It must be a first-class state, not a silent
`disabled` button.

### 7.5 Acceptance gate C

- Assigning 13 alerts with `pumps: 12` yields exactly 12 assignments and 1 explicit `no_unit` event.
- Setting `pumps: 0` yields 100 % `no_unit` and no crash.
- A pump cannot be assigned twice; a `DEWATERING` pump is not a candidate.
- Barrier veto inside 60 s cancels the closure and logs who vetoed.

---

## 8. Module D — API (`command/app.py`)

Flask, port 8000, `threaded=True`. All responses JSON. Manual CORS header — no `flask-cors`
dependency.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{ok, catchments, nodes, version}` |
| POST | `/api/v1/session` | Create session from setup-screen config |
| GET | `/api/v1/scenario` | `rain, duration, mode, region` → full scene |
| POST | `/api/v1/dispatch` | `{session_id, alert_id}` → assignment or infeasible |
| POST | `/api/v1/dismiss` | `{session_id, alert_id, reason}` |
| POST | `/api/v1/mode` | `{session_id, mode}` |
| POST | `/api/v1/tick` | `{session_id, minutes}` → advance simulated clock |
| GET | `/api/v1/fleet` | live inventory + states |
| GET | `/api/v1/log?since=n` | audit events after sequence n |
| GET | `/api/v1/evaluation` | baseline comparison table for the write-up |

Session request body — **this is the contract for the setup screen**:

```json
{
  "operator": "duty-officer",
  "region": "all",
  "rain_mm_hr": 95,
  "duration_min": 60,
  "mode": "red_alert",
  "fleet": {"pumps": 12, "barriers": 8, "wardens": 6}
}
```

Response includes `session_id`, `node_count`, `edge_count`, `inference_ms`, `alerts[]`, `fleet`,
`scarcity: {"critical_nodes": 23, "pumps": 12, "shortfall": 11}`.

### 8.1 Acceptance gate D

- `curl :8000/health` → node counts match the five catchments.
- Session with `pumps: 0` succeeds and reports 100 % shortfall.
- Two concurrent sessions do not share fleet state.
- Every mutating endpoint appends an audit event.

---

## 9. Frontend wiring

### 9.1 Task 0 — unbreak the tree (10 min)

`web/src/components/ControlBar.tsx` needs two props added to `Props` and rendered:

```ts
operator: string
onReconfigure: () => void
```

Render the operator name next to the `SIMULATION` badge, and a small `Settings` button that calls
`onReconfigure`. `App.tsx` already passes both.

### 9.2 Replace mock with API

New `web/src/lib/api.ts`:

```ts
const BASE = import.meta.env.DEV ? '/api/v1' : 'http://127.0.0.1:8000/api/v1'
export async function createSession(cfg: CommandConfig): Promise<Session>
export async function fetchScenario(s: SessionId, q: ScenarioQuery): Promise<Scene>
export async function dispatch(s: SessionId, alertId: string): Promise<Assignment>
export async function tick(s: SessionId, minutes: number): Promise<Scene>
```

Keep `mockScene()` behind `?mock=1` as a **fallback**, not a default. If the API is down mid-demo, the
UI must degrade to the mock with a visible banner rather than a white screen. That is a 10-line guard
and it has saved more hackathon demos than any feature.

### 9.3 What stays synthetic, and says so

| Piece | After wiring |
|---|---|
| Depth field | **Real** (frozen model) |
| Consequence score, bands, priorities | **Real** |
| Alert clustering | **Real** |
| Routes, ETAs, detours | **Real** (Stub leg flagged) |
| Fleet state + clock | **Real** (simulated time, labelled) |
| Actuation | **Simulated** — permanent `SIMULATION` badge |
| POIs | **Real** OSM, fallback name-derived |

---

## 10. Audit trail (`command/audit.py`)

Append-only JSONL, one line per event, `flush()` + `os.fsync()` per write.

```json
{"seq":41,"ts":"2026-11-14T14:09:12Z","sim":"14:09:12Z","actor":"duty-officer",
 "action":"dispatch_approved","alert":"hsr-c04","unit":"PUMP-03","eta_min":11.4,
 "inter_catchment":false,"config_hash":"a91f2c"}
```

Why a file and not SQLite: durability, and *"it is a file I can `tail -f` on stage"*. SQLite is the V2
path if the operator model grows. Record the **input** that caused every output — a municipal inquiry
asks what the system was told, not only what it said.

---

## 11. Evaluation — beat a baseline, honestly

This section is what makes the judges take it seriously. "Our dashboard looks good" scores nothing;
"our queue finds 4.2× more asset-critical nodes in its first 12 slots than sorting by depth" scores
everything.

### 11.1 The claim to test

> Given a storm scenario the triage layer has not been tuned on, does consequence ranking put
> **asset-critical** flooded nodes into the **first N dispatch slots** more often than simple
> baselines?

`N` = the fleet size, because that is the only number that matters operationally.

### 11.2 Baselines

| Baseline | Definition | Why it is fair |
|---|---|---|
| B0 — persistence | assume tomorrow's depth = today's depth | the brief explicitly asks for a persistence baseline |
| B1 — depth order | sort flagged nodes by `depth_m` descending | the obvious "dumb" baseline a reviewer would demand |
| B2 — random | sample N from flagged nodes | floor, to prove the metric isn't trivially high |

### 11.3 Metric

`Recall@N` and `Precision@N` for the label **critical** = `depth ≥ pump_threshold` **and**
`asset_weight ≥ 0.85` (underpass / hospital / transit / fire / substation). Report both, and report the
N that a real city has (12).

### 11.4 Protocol (no leakage)

1. **Split by catchment**, not by random node — random node splits leak spatial autocorrelation and
   judges penalise exactly this.
2. Tune nothing on the test catchments. Weights are fixed in `config.py` before the split is touched.
3. Test on **held-out storm intensities** (`60 / 85 / 100 mm/hr`) not present in the tuning set.
4. Report the table even if we lose on one row.

### 11.5 Deliverable

`command/evaluate.py` writes `scratch/evaluation/baseline-comparison.md`:

| Scenario | Method | Recall@12 | Precision@12 | Asset-critical hit |
|---|---|---|---|---|
| 85 mm/hr, held-out | B0 persistence | … | … | … |
| | B1 depth order | … | … | … |
| | **Ours (consequence)** | … | … | … |

Plus one paragraph where we lose — most likely **low-rainfall scenarios**, where almost nothing floods,
so ranking is noise and depth order is as good as anything. Say that out loud.

---

## 12. Timeline — remaining hours

Deadline is Mon 16 Nov 10:29 IST. Sequence is ordered by **risk retired per hour**, not by elegance.

| # | Block | Est. | Gate at the end |
|---|---|---|---|
| 0 | Fix `ControlBar` props; commit | 0.25 h | tree typechecks |
| 1 | `command/config.py` + `loader.py` + parity test | 1.5 h | node counts match `app.py` |
| 2 | `command/triage.py` + clustering + tests | 3 h | Gate A |
| 3 | `command/app.py` health + `/scenario` | 2 h | `curl` returns a real scene |
| 4 | Wire frontend to `/scenario` (kill mock) | 2 h | real map, real queue |
| 5 | `command/routing.py` + tests | 3 h | Gate B |
| 6 | `command/fleet.py` + state machine + tests | 3 h | Gate C |
| 7 | Dispatch / dismiss / tick endpoints + audit | 2 h | Gate D |
| 8 | `evaluate.py` + baseline table | 2.5 h | numbers exist |
| 9 | Setup screen → session; scarcity UI; `no_unit` card | 2 h | fleet numbers drive everything |
| 10 | Demo rehearsal ×3, bug freeze | 1.5 h | 2:00 run-through, no dead ends |
| 11 | README (official template) + write-up + sources | 2 h | submitted |

≈ 26.75 h. **M1 and M2 are load-bearing.** If time collapses, ship triage + API + queue and cut the
inspector, the FPS badge and the video. Never the reverse.

### 12.1 Freeze points

- **T−12 h:** no new features. Only bugs and wording.
- **T−6 h:** no code changes at all except regressions that break the demo path.
- **T−2 h:** submit. Do not use the last two hours; upload failures are real.

---

## 13. Submission checklist

### Repository
- [ ] Public, opens **logged out** in a private window.
- [ ] `README.md` is the official template, not a research readme.
- [ ] `LICENSE` present.
- [ ] No secrets, no `.venv`, no `node_modules`, no multi-hundred-MB `.pt` caches.
- [ ] `static/command/` committed so the demo needs no Node.
- [ ] One-command run documented: `pip install -r requirements.txt && python app.py`.

### Write-up (~1 page, official template)
- [ ] Track: **AI + Climate**.
- [ ] Problem · What we built · What we added this weekend · How it works · Results · Where it fails ·
      Next · Sources.
- [ ] Named decision-maker: **BBMP ward-level flood response officer / Traffic Police control room**.
- [ ] Every dataset, model, tool and AI assistant cited.
- [ ] The pre-existing-model disclosure paragraph (if you chose Path 1).

### Video (optional, ≤2 min)
- [ ] 1920×1080, readable at 720p.
- [ ] No dead air, no mouse hunting, no terminal scrolling.

### Team
- [ ] Names, school, roles.
- [ ] Credits: OSM contributors, HydroGINE-v5 prior work, deck.gl, MapLibre, the hackathon organisers.

---

## 14. Write-up draft (official template)

> **Track:** AI + Climate
>
> **The problem.** Bengaluru floods at the junction, not at the city. BBMP's flood response runs on
> phone calls and memory: when a cloudburst hits, someone decides which of a dozen underpasses gets
> the first pump. That decision is made under time pressure, with no ranking, and the consequences are
> asymmetric — a flooded hospital access road and a flooded residential lane look identical on a
> rainfall map but are not the same emergency.
>
> **What we built.** A command centre that converts flood-depth predictions into a ranked dispatch
> queue, calculates flood-safe routes for response units, and makes the resource shortage explicit
> rather than hiding it.
>
> **What we added this weekend.** The depth predictor is prior work by the same author, treated as a
> pretrained model we did not train: everything here — triage, consequence ranking, alert clustering,
> routing, the fleet state machine, the API, the dashboard, the audit trail and the evaluation — was
> written during the hacking window.
>
> **How it works.** Five Bengaluru catchments (12,436 nodes) are scored with
> `0.45·severity + 0.30·asset + 0.15·vulnerability + 0.10·network`, clustered so one underpass is one
> dispatch rather than forty, routed with water-aware edge costs, and assigned greedily to the nearest
> feasible unit from a fleet the operator declares at startup.
>
> **Results.** [evaluation table]. At 100 mm/hr the underlying model has 97.8 % critical precision but
> only **32.2 % critical recall** — which is why Red-Alert lowers the barrier trigger to 9 cm. Clustering
> reduced N raw threshold crossings to M dispatches.
>
> **Where it fails.** Low-rainfall scenarios, where ranking is mostly noise. The model under-predicts
> deep ponding at extreme intensity, so recall — not precision — is the binding constraint. Inter-catchment
> travel is a centroid stub, not a real highway route. Actuation is simulated; nothing here closes a
> real gate.
>
> **Next.** Real SCADA integration, a 311 call feed, and per-node time-to-peak from the model directly.

---

## 15. Video script (2:00)

| t | Shot | Line |
|---|---|---|
| 0:00–0:12 | Setup screen | "This is the fleet a real municipality has. Twelve pumps, eight barriers — not twelve per ward, twelve for the city." |
| 0:12–0:25 | Type 12 → Enter | "The city does not get to invent units. What you enter is what exists." |
| 0:25–0:45 | Map, 45 mm/hr | "Five catchments, twelve thousand nodes, from a depth model that runs in under 200 milliseconds." |
| 0:45–1:05 | Raise to 95 mm/hr, queue fills | "At ninety-five an hour, twenty-three nodes cross the critical threshold. We have twelve pumps." |
| 1:05–1:25 | Open a card, show score breakdown | "The queue is ranked by consequence, not depth. This hospital access road is shallower than that lane and outranks it." |
| 1:25–1:45 | Approve, route draws, ETA vs peak | "Eleven minutes to arrive, peak in twenty-two. Feasible. The standard route is underwater, so we take the flood-safe corridor." |
| 1:45–2:00 | Pump 13 request → refusal card | "And the thirteenth request says no. Nearest free pump thirty-eight minutes away. That is the honest answer, and it is the whole point." |

---

## 16. Where this fails — write these down, do not hide them

1. **Critical recall at extreme rainfall is 32.2 %.** The model misses two thirds of the worst nodes at
   100 mm/hr. Red-Alert partially compensates; it does not fix it.
2. **Low-rainfall ranking is weak.** When little floods, the score discriminates poorly.
3. **Inter-catchment travel is a stub**, centroid-to-centroid at 12 m/s. Not a real highway route.
4. **Road graph ≠ water.** Depth is per node; the model does not know culvert geometry or drain
   capacity between nodes.
5. **Actuation is simulated.** No SCADA, no authority, no real gate.
6. **Fleet ETAs assume free-flow arterial speed.** Real Bengaluru traffic at peak is worse.
7. **Five catchments, not the whole city.** 12,436 nodes, not 76,316.

---

## 17. Sources to cite

- **Model:** HydroGINE-v5 ensemble, prior work by the author (`core/production_v4.py`). Benchmarks from
  `data/benchmarks/`.
- **Graphs:** OpenStreetMap via OSMnx; five Bengaluru catchments.
- **POIs:** OSM Overpass API, with name-derived fallback from `JUNCTION_NAMES`.
- **Basemap:** OpenStreetMap raster tiles via MapLibre GL — © OpenStreetMap contributors, ODbL.
- **Tools:** Python, Flask, NetworkX, Shapely, GeoPandas, React 19, TypeScript, Vite, deck.gl, Tailwind.
- **AI assistants used:** list them honestly, including this one.
- **Hackathon:** Veritas AI International High School Hackathon 2026 guide and project briefs.

---

## 18. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **Pre-existing repo breaches rule 2** | **Critical** | §0.3 — disclose and reframe, or change plan. Needs your decision. |
| API not ready at demo time | High | `?mock=1` fallback + visible banner; build never breaks |
| OSM tiles blocked at judging | Medium | Cache a small tile set locally; map still renders offline |
| Graph load slow on cold start | Medium | Cache graphs to `.pkl` on first load |
| Losing track of the frozen boundary | High | Branch `command-layer`; never touch `app.py`/`core/`; parity test guards it |
| Running out of time mid-module | High | Freeze points at §12.1; triage + API + queue ship first |
| Judges see 9 fps in a recording | Low | Never quote headless FPS; measure on GPU |

---

## 19. Decisions still open

| ID | Question | Recommendation |
|---|---|---|
| **Rules** | Path 1 / 2 / 3 (§0.3) | **Path 1 — disclose and reframe** |
| D-15 | City-wide fleet vs per-catchment pools | **City-wide.** Per-catchment deletes the scarcity that is the product. |
| D-13 | Slider ranges vs model clamps (20–120 mm/hr, 15–120 min) | **Align UI to the clamps.** Relaxing changes what the model is asked for. |
| — | May I add a ~30-line per-node TTP endpoint to `app.py`? | **Not needed.** Derive TTP from storm-playback frames. |
| — | Demo video or write-up only? | Write-up is mandatory; video is the difference between "good" and "remembered". |

---

## 20. First commands when we resume

```bash
cd "/Users/ashishpaliwal/PycharmProjects/UrbanFlow-VERITAS AI Hackathon"
git checkout command-layer

# 1. unbreak the tree (Task 0)
$EDITOR web/src/components/ControlBar.tsx    # add operator + onReconfigure
cd web && npm run typecheck && npm run build && cd ..

# 2. scaffold the decision core
mkdir -p command/tests data/command/logs scratch/evaluation
touch command/__init__.py command/config.py command/loader.py

# 3. prove parity before writing any logic
python -m pytest command/tests/test_parity.py -q
```

Parity first. If the node counts disagree, every score after that is built on a wrong map.
