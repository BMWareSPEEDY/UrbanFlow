# UF-COMMAND-V1 — Municipal Flood Command & Dispatch System

**Project:** UrbanFLOW → Operational Decision Layer
**Doc status:** V1.1 — scope, stack and repo decisions resolved (D-01, D-14, D-17)
**Supersedes:** the research-surrogate framing of the previous project
**Companion files:** `../inbox/2026-11-14-01__municipal-flood-command-brief.md` (source brief),
`../reference/2026-11-14__baseline-system-snapshot.md` (what exists today),
`../decisions/decision-log.md` (choices made and still open)

---

## 0. One-paragraph thesis

UrbanFLOW already answers *"how deep will the water be, where, and how fast?"* in ~85 ms. That
answer is useless to a control-room operator, who cannot act on 1,379 numbers. This layer converts
the depth field into **a ranked list of things to do, with a route to get there and a unit to send**
— and then records who approved what. The model is untouched. Everything new happens after the
depth array arrives.

**Product sentence:** *"UrbanFLOW Command tells a municipal control room which six places to
defend first, which roads are already lost, and which pump to send down which safe corridor to
arrive before the peak."*

---

## 1. Scope

### In scope
- Consequence-scored alert triage with municipal asset tagging.
- Operator-selectable conservative safety mode.
- Flood-aware routing with per-vehicle-class passability.
- Simulated fleet state machine with greedy nearest-feasible assignment.
- Single-screen tactical dashboard with an append-only audit trail.

### Deployment scope (D-14)
**All five Bengaluru catchments**: `hsr` (1,379), `bellandur` (1,507), `whitefield` (1,797),
`ecity` (3,337), `koramangala` (4,416) = **12,436 nodes / 29,717 edges**. These are five *separate,
disconnected* graphs, which has three consequences baked into the design below:

1. Triage runs per catchment (one GNN call each) and the five queues are **merged into one ranked
   list** by consequence score.
2. Fleet is **city-wide** (§7.1), so a unit based in HSR may be dispatched to Whitefield. Since the
   graphs share no nodes, that leg uses a **stub route**: great-circle distance between catchment
   centroids ÷ 12 m/s, flagged `inter_catchment: true` in the audit log and drawn as a dashed
   straight line on the map. This is an honest model of the highway leg our street graph omits.
3. KPIs are city-wide sums; the catchment selector becomes a *filter*, not a mode switch.

Never display 76,316 as the live scene — that is the 16-catchment benchmark total.

### Explicitly out of scope (V1)
- Changing model weights, retraining, or re-tuning the surrogate. **Frozen.**
- Altering any existing research claim, benchmark, or `docs/` figure.
- Real actuator integration (gates, pumps, VMS signs). All actuation is **simulated** and labelled.
- Live rainfall ingestion (IMD/radar). Storm input remains the operator's scenario sliders.
- Multi-tenant auth. V1 is a single-operator console; the audit log records an operator name only.
- Real-time optimisation (MILP/VRP). Greedy assignment is sufficient and explainable on stage.

### Non-negotiable constraints
1. `/api/predict` semantics must not change — the research dashboard and the paper depend on it.
2. Every Command Layer number must be traceable to a field that `/api/predict` actually returns.
3. If the model is wrong (it under-predicts the extreme tail — 32.2 % critical recall at
   100 mm/hr), the product must degrade **toward caution**, never toward complacency.

---

## 2. The shift, stated precisely

| | Research surrogate (today) | Command & Dispatch (this build) |
|---|---|---|
| Input | rainfall, duration | rainfall, duration, **+ asset inventory + asset criticality + safety mode** |
| Core computation | GNN forward pass | GNN forward pass → **consequence score → route → assignment** |
| Output unit | 1,379 depths (m) | ~6 ranked orders + 3 corridors + 1 fleet state |
| Success metric | MAE 2.44 cm, F1 90.8 % | **Decisions made before peak inundation** |
| User | reviewer / jury | **control-room operator under time pressure** |
| Failure mode | inaccurate number | **wrong place defended, or a route that drowns a truck** |

The last row is the design driver. Every UI decision below is about making the operator's *next
action* unambiguous in under five seconds.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 1 — Inference (EXISTING, untouched)                           │
│  app.py · Flask :5000                                                │
│  POST /api/predict   → nodes[] (depth m), metrics, swmm reference    │
│  POST /api/storm-playback → 12 frames (for time-to-peak)             │
│  GET  /api/graph-data → lat/lng nodes, edge u/v/length/grade          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP (localhost) — depth array in, no writes
┌───────────────────────────────▼──────────────────────────────────────┐
│  Layer 2 — Decision & Routing (NEW)                                  │
│  command/ · Starlette :8000                                          │
│                                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │ A. Triage  │→ │ B. Router  │→ │ C. Fleet   │→ │ D. Audit      │  │
│  │ consequence│  │ penalty-   │  │ state      │  │ append-only   │  │
│  │ scoring    │  │ weighted   │  │ machine +  │  │ JSONL event   │  │
│  │            │  │ Dijkstra   │  │ assignment │  │ log           │  │
│  └────────────┘  └────────────┘  └────────────┘  └───────────────┘  │
│                                                                      │
│  Static, prepared once at startup:                                   │
│    graphs/*.graphml → nx.MultiDiGraph (already in REGION_CACHE)      │
│    data/command/{region}_pois.geojson     ← POIs snapped to nodes    │
│    data/command/{region}_centrality.json  ← network criticality      │
│    data/command/depots.json               ← 6 depots, hand-curated   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ JSON over fetch
┌───────────────────────────────▼──────────────────────────────────────┐
│  Layer 3 — Command Center UI                                         │
│  React 19 + TypeScript + Vite + deck.gl + Tailwind (D-17)            │
│  Source in web/ → `npm run build` → static/command/ (committed)      │
│  Served by Flask, so `python app.py` stays the single demo command   │
│  Map · Queue · Inspector · Fleet strip · Audit terminal              │
└──────────────────────────────────────────────────────────────────────┘
```

**Why a separate service, not more routes in `app.py`:** the decision layer must be hot-editable
during a hackathon without risking the 1,500-line inference file, and it needs its own process so a
routing hang cannot stall the model. `app.py` becomes a pure dependency.

**Cost:** CORS + a second process to start. Mitigation: `scripts/command/dev.sh` starts both, and
Flask proxies `/api/v1/*` to `:8000` in one line so the browser sees one origin.

---

## 4. The data we actually have (verified, not assumed)

| Need | Available? | Source |
|---|---|---|
| Node coordinates | ✅ | `nodes[].lat/lng`, `x/y` (EPSG:32643 for Bengaluru, auto-detected in `app.py:501`) |
| Edge list with length | ✅ | `edges[].u/v/length` |
| Edge grade / slope | ✅ | `edges[].grade` |
| Road class | ✅ | graphml edge attr `highway` (motorway…residential/service) |
| Speed limit | ✅ | graphml edge attr `maxspeed` (string, needs parsing) |
| Lanes | ✅ | graphml edge attr `lanes` |
| Edge polyline geometry | ✅ | graphml edge attr `geometry` — **use this for the map**, not straight u→v lines |
| Intersection degree | ✅ | node attr `street_count` |
| Elevation | ✅ | `nodes[].elevation` |
| Depression / sink | ✅ | derived in `app.py` (`is_sink`, `depression_depth` from DEM spill analysis) |
| Basement flag | ✅ | `nodes[].is_basement` — note: heuristic `imp>0.4 && elev<882`, Bengaluru-specific |
| SWMM reference depth | ✅ | `nodes[].swmm_depth` (display/validation only) |
| **POIs (hospital, underpass, …)** | ❌ | must be created — §5.1 |
| **Depots** | ❌ | must be created — §5.2 |
| **Fleet** | ❌ | simulated — §7 |

Node counts per catchment and the rainfall/duration clamps are in the reference snapshot §3–§4.
**Triage must read `nodes[]`, not `risk_nodes[]`** (which is truncated to 30 — conflict C-9).

---

## 5. Module A — Risk Triage & Critical Asset Engine

### 5.1 Asset tagging (one-off preparation)

**Primary source: OSM Overpass** via the already-installed `osmnx`. Targets:

| Class | OSM selector | Why it matters |
|---|---|---|
| `underpass` | `tunnel=building_passage`, `layer=-1` highway segments, `covered=yes` | Sump geometry; first to drown, last to drain |
| `hospital` | `amenity=hospital`, `amenity=clinic` (large) | Access road must stay open |
| `fire_station` | `amenity=fire_station` | Dispatch origin |
| `power_substation` | `power=substation` | Flooded substation = multi-day outage |
| `transit_hub` | `railway=station`, `public_transport=station`, `highway=bus_station` | Mass-casualty risk |
| `school` | `amenity=school` | Shelter / vulnerable population |

Output: `data/command/{region}_pois.geojson`, **each feature snapped to the nearest graph node**
within 60 m using `shapely.STRtree` on node points; unsnapped features are dropped and counted.

**Fallback (mandatory, because hackathon networks fail):** the existing `JUNCTION_NAMES` table in
`app.py:740` already encodes ground truth in plain English — *"Silk Board Underpass Ramp"*,
*"Central Mall Bellandur Underpass"*, *"Passport Seva Kendra Underpass"*, *"Agara Lake Outfall
Channel"*. Parse keywords (`underpass → underpass`, `hospital|clinic → hospital`,
`transit|station|metro → transit_hub`, `tech park|mall → transit_hub`) and assign the matching
graph node. Rule: **if Overpass returns < 5 POIs for a region, use the name-derived set.** Never
ship an empty POI layer.

### 5.2 Depots

Six hand-curated depots per region, each snapped to the nearest node that is (a) not `is_basement`
and (b) in the top 40th percentile of elevation — a depot that floods is not a depot. Seeded from
POIs (fire stations, BBMP ward offices), stored in `data/command/depots.json`:

```json
{ "region": "hsr",
  "depots": [
    { "id": "DEP-HSR-01", "name": "HSR Sector 2 Yard", "node_id": "12345",
      "lat": 12.9081, "lng": 77.6412, "elevation": 894.2,
      "asset_classes": ["pump", "warden"] }
  ] }
```

### 5.3 The threshold ladder — one source of truth

Today the codebase carries **three different ladders** (reference snapshot §5, conflict C-3). The
Command Layer owns exactly one, in `command/config.py`, and the UI renders from it:

| Band | Normal mode | Red-Alert mode | Automated action |
|---|---|---|---|
| Dry / observe | `< 0.05 m` | `< 0.05 m` | none (map colour only) |
| **Watch** | `0.08 – 0.14 m` | `0.08 – 0.14 m` | pre-position standby unit, queue a P3 alert |
| **Barrier Closure** | `0.15 – 0.29 m` | **`0.09 – 0.24 m`** | barrier close + traffic diversion, queue P2 |
| **Active Pumping** | `≥ 0.30 m` | **`≥ 0.25 m`** | pump truck dispatch, queue P1 |

`alert_floor = 0.08` in both modes: it matches the existing `risk_nodes` filter and corresponds to
the depth at which a kerb is overtopped and traffic behaviour changes.

**Why Red-Alert moves `0.15→0.09` and `0.30→0.25` and not lower:** the measured failure mode at
100 mm/hr is *critical recall 32.2 %* — the model misses two-thirds of >0.30 m nodes. Dropping the
pump trigger to 0.25 m recovers a large share of those misses at a known cost in false positives
(precision 97.8 % → ~93 % estimated). That trade is acceptable for a *barrier*, which is cheap and
reversible, and is why the barrier trigger moves the most. Both offsets are `config.py` constants,
not magic numbers, and the UI shows the delta ("Red-Alert: trigger lowered 6 cm — estimated 3 extra
closures per storm").

### 5.4 Severity (depth → 0..1)

```python
S = clamp01((depth_m - 0.05) / (0.40 - 0.05))
```

Linear from 5 cm to 40 cm, saturating above. Rationale: interpretable, monotone, and defensible in
one sentence on stage — *"severity is depth mapped onto the 5-to-40-centimetre band that matters for
vehicles and people."* A saturating curve (`1 - exp(-d/0.15)`) is a V2 option; do not ship two
curves in V1.

### 5.5 Asset criticality weight (A)

Max over all POIs snapped to the node (if several, the highest class wins):

| Class | A |
|---|---|
| `underpass` | 1.00 |
| `transit_hub`, `hospital` | 0.95 |
| `fire_station` | 0.90 |
| `power_substation` | 0.85 |
| `school` | 0.70 |
| arterial edge (`highway ∈ {motorway, trunk, primary}`) | 0.60 |
| default street | 0.25 |

### 5.6 Vulnerability (V) — from the DEM features the model already computes

```python
V = clamp01(0.45 * is_sink + 0.35 * min(1.0, depression_depth / 0.30) + 0.20 * is_basement)
```

Captures "water will stand here and stay", not just "water is deep here right now".

### 5.7 Network criticality (N)

A node that floods on a dead-end lane costs nothing; a node that floods on the only link between a
hospital and the arterial grid costs the city. Precomputed once per region at startup, cached to
disk:

```python
bc = nx.betweenness_centrality(G, k=min(400, n), weight="length", seed=7)  # sampled, deterministic
N  = percentile_rank(bc[node])          # 0..1 within the catchment
```

For graphs under 2,000 nodes, use exact betweenness (`k=None`). Cache key includes graph mtime.

### 5.8 Consequence score

```
CS = 100 × (0.45·S + 0.30·A + 0.15·V + 0.10·N)
```

Weights live in `command/config.py` as `TRIAGE_WEIGHTS` and must sum to 1.0 (asserted at import).

| Tier | CS | Operator meaning |
|---|---|---|
| **P1** | ≥ 70 | Act now. Top of the queue. |
| **P2** | 50–69 | Act this storm cycle. |
| **P3** | 30–49 | Watch / pre-position. |
| suppressed | < 30 | Map colour only; keep out of the queue. |

**Why consequence scoring beats sorting by depth — the demo line:** a 0.28 m residential sag scores
`100×(0.45·0.657 + 0.30·0.25 + 0.15·0.9 + 0.10·0.2) = 47` → P3. A 0.19 m hospital access road
scores `100×(0.45·0.40 + 0.30·0.95 + 0.15·0.5 + 0.10·0.8) = 59` → P2. *The shallower node outranks
the deeper one.* That is the whole module, in one comparison.

### 5.9 Output contract

**Alert granularity — one alert per asset, not per node.** A single underpass spans dozens of
grid nodes; a naive "every node ≥ 0.08 m" feed produces 40 alerts for the same ramp and the operator
dispatches three pumps to one location. Deduplicate on `(catchment, asset_cluster_id)` keeping the
highest-consequence node, and carry the cluster's node count and extent on the card
(`affected_nodes: 38`). Only unclustered street nodes fall back to per-node alerts. This rule is
worth more than any threshold tuning: it is the difference between a feed and a queue.

```json
{ "node_id": "1042", "junction_name": "Silk Board Underpass Ramp",
  "depth_m": 0.21, "depth_cm": 21.0, "band": "barrier",
  "priority": "P1", "consequence_score": 78.4,
  "components": { "severity": 0.457, "asset": 1.0, "vulnerability": 0.62, "network": 0.91 },
  "assets": ["underpass"], "action": "barrier_closure",
  "recommended_units": ["BAR-03"], "ttp_min": 34,
  "confidence": { "swmm_delta_cm": 4.1, "status": "MATCH", "mode": "red_alert" } }
```

`confidence.swmm_delta_cm` and `status` come straight from `/api/predict`'s `error_cm` / `status`
fields — this is what makes the Node Inspector honest rather than a black box.

---

## 6. Module B — Dynamic Flood-Aware Routing

### 6.1 Graph model

Reuse the exact production graph. Do **not** rebuild from OSM: `app.py` already holds
`REGION_CACHE[region]['graph']` as a `MultiDiGraph` with `length`, `grade`, `highway`, `maxspeed`,
`lanes`, `geometry`. The Command service loads the same `.graphml` files and asserts node-set
equality with `/api/graph-data` at boot (fail loudly if they diverge — a silently different graph is
the worst possible bug here).

**Snapping** arbitrary lat/lng (a click, a POI) to a node: nearest node within 80 m, else nearest
edge midpoint (and insert a temporary node). Never route from a raw coordinate.

### 6.2 Free-flow speed by road class

Parsed once at load: `maxspeed` (handles `"30 mph"`, `"40"`, `"50 km/h"`, null) → fallback table:

| `highway` | v₀ (m/s) |
|---|---|
| motorway / trunk | 22 / 18 |
| primary / secondary | 14 / 12 |
| tertiary | 10 |
| residential | 8 |
| service / living_street | 6 |
| default | 9 |

Apply a vehicle multiplier: pump truck ×0.80, ambulance/fire ×1.00, warden ×0.90.

### 6.3 Depth → speed derating (single mechanism, no double-counting)

```python
def passability_factor(depth_m, d_impass, d_safe=0.05):
    if depth_m <= d_safe:            return 1.0
    if depth_m >= d_impass:          return math.inf          # impassable
    return ((d_impass - depth_m) / (d_impass - d_safe)) ** 1.5

w(edge) = length_m / (v_effective * passability_factor(depth[u..v]))
```

This reproduces the brief's requested shape exactly — normal below 10 cm, steeply penalised in the
middle, infinite at the axle depth — from **one** physically-motivated expression instead of a
hand-tuned congestion constant. At `d_imp = 0.30`: 15 cm → 2.2× slower, 20 cm → 5.7×, 25 cm → 17×,
30 cm → impassable. At `d_imp = 0.25`: 15 cm → 3.1×, 20 cm → 8.7×, 25 cm → impassable.

**Edge depth** = `max(depth[u], depth[v])`. Conservative on purpose: entering a flooded node is the
risk.

**Vehicle profiles** (`command/config.py:VEHICLE_PROFILES`):

| Class | d_impass | Note |
|---|---|---|
| `pump_truck` | **0.25 m** | heavy, low air intake — the brief's axle figure |
| `ambulance`, `fire_engine` | **0.30 m** | high clearance, but >30 cm is a retrieval, not a rescue |
| `warden` | **0.20 m** | light vehicle / motorcycle |
| `civilian` (baseline only) | 0.20 m | used to draw the "standard GPS" route |

Also: edges inside a closed barrier's zone get `w = ∞` (Module C writes this back into the router),
and `oneway` is respected.

### 6.4 Algorithms

| Need | Algorithm | Complexity (4,416-node catchment) |
|---|---|---|
| One corridor depot → incident | `nx.bidirectional_dijkstra` / A* with haversine heuristic | < 5 ms |
| ETA from **any** depot to a target | `nx.multi_source_dijkstra(G, sources=all_depot_nodes)` — one run per vehicle class, then O(1) lookup per alert | ~20 ms per class |
| "Standard GPS" comparison route | same graph, all depths set to 0 | < 5 ms |
| All-pairs fallback (rare) | cached Dijkstra from each depot | 6 × 15 ms |

**Caching:** `scenario_key = sha1(region, rain_mmhr, duration_min, mode)`. The reweighted graph and
the multi-source distance maps are memoised on that key with an LRU of 4. Slider drags must not
re-run routing; routing runs on **commit** (debounce 250 ms).

**The comparison the demo turns on:** compute both routes, render standard in red (dashed, with a
"flooded at 3 junctions" badge), safe in green, and show `+N min` added detour time. If the safe
route is *impossible* (no path), say so explicitly — "no flood-safe corridor exists, escalate to
boat/NDRF" is a valid and impressive output.

### 6.5 Inter-catchment legs (required by D-14)

The five Bengaluru graphs share no node IDs, so `nx.shortest_path` returns `NetworkXNoPath` across
catchments. A pump in HSR must still be able to reach Whitefield. Model the missing leg explicitly:

```python
if origin_region != target_region:
    stub_km   = haversine(centroid[origin_region], centroid[target_region]) / 1000.0
    stub_min  = stub_km * 1000.0 / 12.0 / 60.0      # 12 m/s ≈ 43 km/h average arterial speed
    total_min = (route_to_catchment_exit_min
                 + stub_min
                 + route_from_catchment_entry_min
                 + config.INTER_CATCHMENT_PENALTY_MIN)
    inter_catchment = True
```

Rules: the stub is always drawn as a **dashed straight line**, always carries
`inter_catchment: true` in the payload and the audit log, and always adds a **20-minute assumption
penalty** to reflect the fact that the unit is leaving its own jurisdiction — a real-world cost
(home-ward returns, fuel, handover) that keeps intra-catchment units naturally preferred. Expose the
penalty as `config.INTER_CATCHMENT_PENALTY_MIN` and show it as its own line item in the ETA
breakdown, never folded silently into the total.

---

## 7. Module C — Resource Allocation & Fleet State Tracker

### 7.1 Inventory — one city-wide pool (D-15)

`data/command/fleet.json`. Twelve pumps is the **whole city**, not per catchment. That scarcity is
the product: at 95 mm/hr across five catchments the triage layer flags far more critical nodes than
twelve units can cover, so the operator must choose, and the consequence score is what makes the
choice defensible.

A "pump" here is a real municipal object: a trailer-mounted diesel pump set (1,000–3,000 L/min,
BBMP/fire-service operated), towed to a flooded underpass, hoses dropped into the standing water and
run out to the nearest storm drain, canal, or lake outfall. It is the primary physical remedy for an
underpass, because the water will not drain on its own once the outfall is surcharged.

| Class | Count | Capability | Bound to |
|---|---|---|---|
| `pump` | 12 | 1,500 L/min dewatering; clears a 0.30 m node in ~45–90 simulated minutes | free-roaming, any node |
| `barrier` | 8 | automated underpass gate + diversion signage | **one underpass POI each**, pre-assigned at boot |
| `warden` | 6 | traffic diversion squad; 2 personnel + light vehicle | free-roaming |

Assets are **stationary at depots until dispatched**. Barriers are the exception: each is bound to a
specific underpass at boot and its lifecycle is *triggered by depth*, not by operator approval — the
operator gets a 60 s veto window instead. That is the "automated infrastructure trigger" in the
brief, and it is only defensible because a gate is cheap and reversible.

### 7.2 State machine

```
pump:    IDLE → ASSIGNED → EN_ROUTE → ON_SITE → DEWATERING → RETURNING → IDLE
barrier: IDLE → PENDING_CLOSE(60s veto window) → CLOSING → CLOSED → REOPENING → IDLE
warden:  IDLE → ASSIGNED → EN_ROUTE → ON_SITE → RETURNING → IDLE
```

Every transition appends an audit event with `ts`, `asset_id`, `from`, `to`, `cause`, `actor`
(`system` | operator name), and `scenario_key`. Transitions are idempotent on
`(asset_id, cause_hash)` so a double-click cannot dispatch two pumps.

**Simulated clock.** Wall-clock ETA countdowns are unusable in a 4-minute demo. The service
maintains `sim_now` and exposes `POST /api/v1/fleet/tick {minutes: 5}`. The UI offers a "1 min = 1 s"
accelerated clock toggle. Every timestamp in the audit log is `sim_now`, with `wall_ts` alongside.

### 7.3 Greedy nearest-feasible assignment

Runs whenever triage produces a P1/P2 alert. Per alert:

```
1. required_class = action → {pump, barrier, warden}
2. candidates = assets[required_class] where status == IDLE and depot_distance_ok
3. For each candidate: eta = multi_source_dist[candidate.depot][target_node] / 60
   (one multi-source run per class already computed in §6.4 — this is a lookup, not a search)
4. feasible = (eta + MOBILIZE_MIN + SAFETY_MIN) <= ttp_min
   MOBILIZE_MIN = 5, SAFETY_MIN = 5
5. if no candidate feasible:
       emit recommendation = "pre_position" at the nearest dry staging node
       (a node reachable from the depot with depth < 0.05 whose own route to the target is < 15 min)
6. else pick argmin(eta); tie-break by capacity, then by lower CS-handled-so-far (load balance)
7. do NOT auto-assign. Return the recommendation; assignment happens on operator Approve.
```

**ETA vs time-to-peak is the product's core promise.** `ttp_min` is derived from
`/api/storm-playback`: run the 12-frame series, take `argmax` per node, and convert
`ttp = (frame_index / 11) × total_duration_min`. If playback is unavailable, fall back to
`ttp = 0.6 × duration_min` and flag `ttp_source: "heuristic"` in the payload so the UI can say
"estimated".

**One pump, one job.** A pump dispatched to a P1 is unavailable for the next alert for
`DEWATERING_MIN = 45` simulated minutes. This is what makes the "Available Pumps: 7" KPI move, and
it is the reason the operator must choose rather than approve everything. Without scarcity there is
no decision, and without a decision there is no product.

### 7.4 Output: the dispatch queue card

```json
{ "alert_id": "ALT-0007", "node_id": "1042", "junction_name": "Silk Board Underpass Ramp",
  "priority": "P1", "consequence_score": 78.4, "depth_cm": 21.0, "band": "barrier",
  "action": "barrier_closure", "assets": ["underpass"],
  "recommended": { "unit": "BAR-03", "depot": "DEP-HSR-01", "eta_min": 11,
                   "added_vs_standard_min": 4, "feasible": true, "ttp_min": 34,
                   "arrives_before_peak": true },
  "alternatives": [ { "unit": "BAR-05", "eta_min": 19, "feasible": false } ],
  "confidence": { "swmm_delta_cm": 4.1, "status": "MATCH" } }
```

---

## 8. Module D — Command Center UI

### 8.1 Layout (100vh, no scroll)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ [A] TELEMETRY & CONTROL  ·  64px                                              │
│ Catchment ▾ │ Rain ──●── 95 mm/hr │ Duration ──●── 60 min │ [RED-ALERT ●]     │
│ Latency 86 ms · Critical 23 · Blocked 4.2 km · Pumps 6/12 · Queue 6 · ETA 11m  │
├──────────────────────────────────────────────┬────────────────────────────────┤
│                                              │ [C] LIVE DISPATCH QUEUE  30%   │
│                                              │ ┌────────────────────────────┐ │
│ [B] DIGITAL TWIN MAP  70%                    │ │ P1  78  Underpass  ●●●●●   │ │
│                                              │ │ 21 cm · Silk Board Ramp    │ │
│  · road edges by depth: cyan→amber→crimson   │ │ BAR-03 · ETA 11m · peak 34m│ │
│  · pulsing crimson = P1                      │ │ [Approve & Dispatch] [×]   │ │
│  · icons: depot ▣ hospital ✚ underpass ⊓     │ └────────────────────────────┘ │
│  · green corridor / red standard route       │  … P2 cards, scroll within     │
│  · click node → Inspector Card               │     panel only                 │
│                                              │                                │
├──────────────────────────────────────────────┴────────────────────────────────┤
│ [D] SITUATION LOG & AUDIT TRAIL  ·  180px, monospace, auto-scroll             │
│ 14:02:11Z  INFER  hsr 95mm/hr 60m red_alert  nodes=1379  86ms                 │
│ 14:02:11Z  TRIAGE P1=3 P2=3 P3=11  suppressed=402                             │
│ 14:02:14Z  GATE   BAR-03 → PENDING_CLOSE  node=1042 d=0.21m  veto 60s         │
│ 14:02:38Z  OPER   ak  APPROVED BAR-03  eta=11m  route=4.1km  +4m vs std       │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Map rendering decisions

- **deck.gl `PathLayer`** for edges using the graphml `geometry` polyline (not u→v chords — chords
  in a curved road network look broken), with per-vertex colour via binary attributes and
  `updateTriggers` keyed on `scenario_key`.
- **`ScatterplotLayer`** for nodes at `radiusMinPixels 2`, negligible above 0.05 m so the map is not
  a wall of dots.
- **`IconLayer`** for POIs (atlas sprite, 4 glyphs), **`PathLayer`** ×2 for standard (red, dashed via
  `dashArray` in a `TextLayer`-free custom shader or simply opacity + width variance) and safe route.
- Pulsing: CSS-animated overlay ring on a separate `ScatterplotLayer` with a sine-modulated radius,
  **respecting `prefers-reduced-motion`** (static ring instead).
- Rendering budget: 11,183 edges + 4,416 nodes must hold **≥ 50 FPS** on integrated graphics.
  Verify with the deck.gl FPS meter before styling.

### 8.3 Node Inspector Card

Appears on click, anchored to the node, dismissible with `Esc`. Fields, in this order (operator
need order, not data-model order):

1. Depth now (`21.0 cm`) + band chip + priority chip
2. Consequence score, with the four component bars (S / A / V / N) — *this is the "why", and it is
   the screen a judge will photograph*
3. Asset tags, and the junction name
4. Terrain: elevation, upstream slope, sink depression, `is_sink`
5. Confidence: `swmm_depth`, `error_cm`, `status` — framed honestly as *"SWMM reference differs by
   4.1 cm (MATCH)"*
6. `[Dispatch Nearest Unit]` (primary) · `[Reroute here]` (secondary)

### 8.4 Queue behaviour

- Sorted by CS desc, never by depth.
- Max 6 visible cards, the rest collapsed into "+11 more alerts".
- Approve → card mutates in place into a **live dispatch card**: unit, ETA countdown, `Cancel` for
  30 s, then irreversible.
- Dismiss → requires a reason from a 3-option menu (`false alarm` / `already handled` /
  `insufficient confidence`), because dismissal is the label that would train a future policy.
- Keyboard: `1–6` focus card, `Enter` approve, `Esc` dismiss, `R` reset scenario. A control room
  runs on keyboards, not mice.

### 8.5 Visual tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0B0F14` | canvas |
| `--panel` | `#111823` | panels, 1px `#1E2A38` border |
| `--text` | `#E6EDF5` | primary |
| `--muted` | `#8B9AAB` | labels |
| `--cyan` | `#22D3EE` | 0.05–0.14 m |
| `--amber` | `#F59E0B` | 0.15–0.29 m |
| `--crimson` | `#EF4444` | ≥ 0.30 m + pulsing |
| `--green` | `#34D399` | safe route, available assets |
| `--red-alert` | `#FB7185` | mode indicator only |

Type: Inter (UI) + JetBrains Mono (log, all numerics). Numbers use tabular figures so digits do not
jitter as values update.

---

## 9. API contract — `command/` service (Starlette, `:8000`)

All endpoints under `/api/v1`. All responses include `scenario_key` so the UI can discard stale
payloads (out-of-order slider responses are the #1 source of "the map is lying" bugs).

| Method | Path | Purpose |
|---|---|---|
| GET | `/bootstrap?region=` | config, thresholds, fleet, POIs, depots, graph meta, centrality |
| POST | `/scenario` | run inference proxy + triage; returns depths, queue, KPIs, blocked length |
| POST | `/route` | `{region, origin, target, vehicle_class, mode}` → standard + safe + delta |
| POST | `/dispatch/approve` | `{alert_id, unit_id, operator}` → asset locked, route, ETA |
| POST | `/dispatch/dismiss` | `{alert_id, reason, operator}` |
| POST | `/fleet/tick` | advance `sim_now` by N minutes, fire transitions |
| GET | `/fleet` | current asset states, positions along route |
| GET | `/audit?since=` | append-only events |
| GET | `/health` | dependency checks (model reachable, graph node-count match) |

### `POST /scenario`

```json
// request
{ "region": "hsr", "rainfall_mmhr": 95, "duration_min": 60,
  "mode": "red_alert", "operator": "ak" }

// response (abridged)
{ "scenario_key": "hsr:95:60:red_alert",
  "metrics": { "inference_ms": 86, "gnn_ms": 12.4, "critical_nodes": 23,
               "blocked_km": 4.2, "pumps_available": 6, "queue_size": 6,
               "mean_eta_min": 11 },
  "queue": [ /* dispatch cards, §7.4, max 6 */ ],
  "suppressed_count": 402,
  "depths": { "1042": 0.21, "1043": 0.07 },   // sparse: only nodes > 0.02 m
  "blocked_edges": [ [ "u", "v" ], ... ] }
```

`depths` is deliberately sparse — sending 1,379 depths twice per slider move is wasted bandwidth and
the map only needs the flooded subset plus a client-side cache from `/bootstrap`.

### `POST /route`

```json
{ "standard":  { "path": ["n1","n2"], "minutes": 9.0, "distance_km": 3.1,
                 "flooded_crossings": 3, "feasible": true },
  "safe":      { "path": ["n1","n7"], "minutes": 13.0, "distance_km": 4.1,
                 "flooded_crossings": 0, "feasible": true },
  "delta_min": 4.0, "vehicle_class": "pump_truck", "scenario_key": "hsr:95:60:red_alert" }
```

---

## 10. Build plan

### Repository layout (new, additive)

```
command/
  __init__.py
  app.py           # Starlette routes only
  config.py        # thresholds, weights, vehicle profiles, fleet spec — single source of truth
  engine.py        # loads REGION_CACHE-equivalent graph + POIs + centrality at boot
  triage.py        # Module A
  routing.py       # Module B
  fleet.py         # Module C
  audit.py         # append-only JSONL, fsync on write
  schemas.py       # request/response validation (dataclasses + manual checks, no pydantic dep)
  state.py         # in-process scenario + fleet state, threading.Lock
scripts/command/
  prepare_pois.py      # Overpass → GeoJSON → snapped node ids (+ name fallback)
  prepare_depots.py
  precompute_centrality.py
  dev.sh               # start Flask :5000 + uvicorn :8000
  smoke.sh             # curl the full happy path
web/                   # React 19 + TS + Vite + Tailwind source (D-17)
  src/
    App.tsx
    components/  ControlBar · MapCanvas · DispatchQueue · NodeInspector
                 FleetStrip · AuditTerminal
    layers/      roads.ts · nodes.ts · routes.ts · pois.ts   (deck.gl layer factories)
    state/       scenario.ts (zustand or useReducer), types.ts
    lib/         api.ts · format.ts
  index.html · vite.config.ts · tailwind.config.ts
static/command/        # BUILD OUTPUT (committed) — served by Flask, no Node at demo time
data/command/          # generated, committed for demo determinism
scratch/               # this documentation
```

### Milestones

| # | Deliverable | Acceptance criteria | Est. |
|---|---|---|---|
| **M0** | Scaffold | `uvicorn command.app:app` serves `/health`; node-count parity check against `/api/graph-data` passes for all 16 regions; `web/` builds to `static/command/`; `git init` **done** (commit `2b16dec`) | 3 h |
| **M1** | Module A | `POST /scenario` returns ≥ 1 P1 on a 95 mm/hr Bengaluru storm; the hospital-vs-residential ranking inversion (§5.8) is demonstrated in a unit test | 6 h |
| **M2** | Module B | Route returns a safe detour with `flooded_crossings = 0` where the standard route has ≥ 1; impassable depth yields `feasible: false` rather than a wrong route | 6 h |
| **M3** | Module C | Approve locks a unit; a second approve gets a different unit; `pumps_available` decrements; `tick` drives ETA to 0 and back to IDLE | 5 h |
| **M4** | Module D | 50 FPS with 11k edges; 100vh no-scroll at 1366×768 and 1920×1080; keyboard path works end-to-end without a mouse | 8 h |
| **M5** | Integration | Demo script §11 runs start-to-finish in under 4 minutes with no manual reload; audit log contains every transition | 3 h |

Total ≈ 30 focused hours. M1 and M2 are the load-bearing modules; if time collapses, ship them and
simplify the UI, never the reverse.

### Build evidence (measured 2026-11-14, commit-pending)

**M0 partially landed.** `web/` builds and serves; the shell renders the real four-zone layout with
synthetic data shaped exactly like the future API payload.

| Claim | Evidence |
|---|---|
| Build pipeline works | `npm run build` → `static/command/` (1.04 MB JS / 300 kB gzip, 1.9 s) |
| No Node needed at demo time | traffic is served from `static/command/`, Flask untouched (no `app.py` change) |
| 100vh, no page scroll | headless Chromium: `scrollHeight == innerHeight` at 1920×1080 **and** 1366×768 |
| Four zones render | queue / control bar / audit log / 2 canvases detected; 6 deduped alert cards |
| No runtime errors | 0 console errors, 0 page errors at both viewports |
| Interaction works | rainfall 45→110 + Red-Alert toggle repopulates the queue, triggers lower (8/9/25 cm shown) |
| Thresholds render from config | legend text derives from `THRESHOLDS`, not hard-coded strings |

Screenshots: `scratch/figures/command-1920x1080.png`, `command-1366x768.png`, `command-red-alert.png`.

**Caveat on the FPS number.** Headless Chromium renders through SwiftShader (no GPU), so it reports
9–10 FPS for 3,640 edges. That is a software-raster floor, **not** a GPU measurement, and it must not
be quoted as the performance result. The real check is the `Render` KPI in the top bar on a GPU
browser at 11,183 edges (Koramangala alone) — that is the M4 gate.

### Definition of done (global)
- No change to `/api/predict`, `/api/storm-playback`, `docs/`, or `paper/`.
- Every number in the UI is either from the model or from `config.py` — no inline literals in JS.
- `scratch/decisions/decision-log.md` updated for every irreversible choice.
- The audit log survives a service restart (append-only file, not memory).

---

## 11. Demo script (4 minutes, judge-facing)

| t | Beat | What is on screen | What you say |
|---|---|---|---|
| 0:00 | **Calm** | 15 mm/hr, all cyan/green, 12/12 pumps idle, latency 86 ms | "This is the same model — 2.44 cm MAE, 76,316 nodes benchmarked, 85 ms. We changed what happens next." |
| 0:30 | **Escalate** | Drag to 95 mm/hr, toggle Red-Alert. Queue populates in ~100 ms | "Six places to defend, ranked by consequence, not depth." |
| 1:00 | **Rank inversion** | Click the P2 card at 19 cm and the P3 card at 28 cm | "The shallower one is ranked higher — it's a hospital access road. The deeper one is a dead-end lane." |
| 1:30 | **Dispatch** | Approve P1. Green corridor draws, red standard route shows 3 flooded crossings | "The GPS route drives through 21 cm of water. The flood-safe detour adds 4 minutes and arrives 23 minutes before peak." |
| 2:15 | **Scarcity** | Approve three more; pumps 12→8; one alert turns `infeasible`, recommends pre-position | "We have twelve pumps and six simultaneous crises. The system tells you what it cannot do." |
| 3:00 | **Ambulance** | Hospital → residential call; reroute around two submerged arterials | "This is the case that kills people: a route that looks fine and is not." |
| 3:30 | **Audit** | Scroll the log; show the gate veto window | "Every automated gate close and every human approval is on the record. This is what a municipal inquiry would ask for." |

Numbers above are illustrative; **replace them with measured values before the demo** and record
them in `scratch/reference/`.

---

## 12. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Model under-predicts the extreme tail (32.2 % critical recall at 100 mm/hr) → a real hazard is not queued | Certain (measured) | High | Red-Alert mode as default when rain > 80 mm/hr; show `confidence` on every card; state the limitation on the model card rather than hide it |
| R-2 | No version control during a large rewrite | ~~Certain today~~ **mitigated** | High | Done: repo initialised, baseline commit `2b16dec`, work on branch `command-layer` (D-01) |
| R-3 | POI data unavailable offline | Medium | High | Name-derived fallback (§5.1) is mandatory, not optional |
| R-4 | Map jank at 11k edges | Medium | Medium | deck.gl binary attributes; measure FPS at M0, not M4 |
| R-5 | Second process breaks the single-command demo | Medium | High | `dev.sh` + Flask proxy path; smoke test in CI-less `smoke.sh` |
| R-6 | Routing produces a route through 0.24 m water and someone calls it "unsafe" | Low | High | Per-class `d_impass` documented in UI tooltip; never claim "safe", say "flood-safe for a pump truck at 0.25 m" |
| R-7 | Judges read "automated gate lock" as a real actuator | Medium | High | Persistent `SIMULATION` badge on the barrier panel; audit log marks `actor: system(simulated)` |
| R-8 | Threshold sprawl (three ladders already exist) | High | Medium | One `config.py`; a unit test asserting the UI and service agree |

---

## 13. Open questions for the author

**Resolved:** catchment scope = all five (D-14) · fleet pool = recommended city-wide (D-15,
explanation pending reply) · stack = React/TS/Vite/deck.gl/Tailwind (D-17) · repo = git, branch
`command-layer` (D-01).

1. **Fleet realism (D-15):** shared city-wide pool (12 pumps for the whole city — creates scarcity,
   needs a stub route between catchments) or per-catchment pools (simpler, no tension)? See
   `decisions/decision-log.md` → *D-15 explained*.
2. **Time-to-peak source:** is the 12-frame `/api/storm-playback` good enough, or do you want a
   dedicated per-node TTP endpoint added to `app.py`? (Adding it is ~30 lines and does not touch the
   prediction path — but it is a change to the frozen file, so it needs your explicit yes.)
3. **Slider ranges:** the app clamps rain to 20–300 and duration to 15–120, but the brief asks for
   10–120 and 15–180. Align the UI to the clamps, or relax the clamps? (Relaxing changes what the
   model is being asked for — not recommended without a re-check.)
4. **Rainfall source:** sliders only, or also a "load a real event" preset (e.g. Oct-2024 Bengaluru
   100 mm/hr) for credibility?
5. **Audit persistence:** flat JSONL on disk (recommended) or SQLite (queryable, more moving parts)?
6. **Who is the operator?** Single named operator for the demo, or a fake multi-user model with
   handover?

---

## 14. Glossary

| Term | Meaning here |
|---|---|
| **CS** | Consequence Score, 0–100, §5.8 |
| **Band** | Watch / Barrier / Pump, §5.3 |
| **`d_impass`** | Depth at which a vehicle class cannot proceed, §6.3 |
| **TTP** | Time to peak inundation at a node, derived from storm playback, §7.3 |
| **Feasible** | `ETA + mobilise + safety ≤ TTP` |
| **Pre-position** | Move a unit to a dry staging node near the hazard when it cannot arrive in time |
| **Red-Alert** | Conservative mode lowering action triggers; compensates measured low-bias |
| **Suppressed** | CS < 30; shown on the map, excluded from the queue |
| **Scenario key** | `region:rain:duration:mode`; the cache and staleness identity for everything |
