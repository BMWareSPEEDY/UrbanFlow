# INBOX — 2026-11-14-01 — Municipal Flood Command & Dispatch Brief

> **Status:** raw capture, verbatim in substance, lightly normalised for typography only.
> **Do not edit.** Distilled into `specs/UF-COMMAND-V1__…`. Decisions raised by this brief are in
> `decisions/decision-log.md`.

**Context stated by the author:** this repo is a copy of a previous, more research-oriented
project. The intent is to *remap* it — step up from a prediction engine to an operational
product. Keep a scratch directory of these notes for later reference.

---

## The brief

To turn UrbanFLOW from a pure prediction engine into an autonomous **Municipal Flood Command &
Dispatch System**, build an **Operational Decision Layer** on top of the existing HydroGINE-v5 API.

Rather than changing how the model predicts water depth, change **what happens after the GeoJSON
leaves the model** — turning raw centimetre depth values across thousands of nodes into ranked
emergency actions, safe evacuation routes, and live resource tracking.

### 1. Core conceptual shift

| | Before (research surrogate) | After (command & dispatch wrapper) |
|---|---|---|
| Input | Rainfall (`I · Δt`) | Live/simulated storm scenario **+** current city resource state |
| Output | Predicted water depth (cm) at 76,316 street junctions | Prioritised dispatch orders, dynamic safe corridors, automated infrastructure triggers |

### 2. Four core modules

**Module A — Risk Triage & Critical Asset Engine (the brain).** Raw depths are noisy for human
operators. Post-process depth into **consequence-weighted severity**:

- *Asset tagging:* overlay static municipal POIs onto the street graph — underpasses, hospitals,
  fire stations, power substations, major transit hubs. 0.25 m on a dead-end residential lane is
  low priority; 0.25 m at an underpass or hospital access road is a critical emergency.
- *Dynamic safety-margin mode:* the model has a known conservative low-bias under extreme
  100 mm/hr storms. Give the operator a **Normal Mode** vs **Red-Alert Conservative Mode** toggle
  that lowers the hazard trigger (e.g. 0.15 m → 0.08–0.10 m) so emergencies are not missed.
- *Action classification:*
  - **Watch (0.08–0.14 m)** — pre-position standby units.
  - **Barrier Closure (0.15–0.29 m)** — automated underpass gate lock + traffic diversion.
  - **Active Pumping Required (≥ 0.30 m)** — immediate dewatering pump truck dispatch.

**Module B — Dynamic Flood-Aware Routing Engine.** Emergency vehicles cannot use standard
shortest-path GPS when streets flood.

- *Penalty-weighted graph:* reuse the exact road graph `G=(V,E)`; update edge weights every time
  the rainfall slider changes.
  - `< 0.10 m` → normal travel-time weights.
  - `0.10–0.25 m` → steep congestion/slowdown penalty.
  - `≥ 0.25 m` (axle/exhaust ingestion) → **impassable (∞)**.
- *Live corridor computation:* operator clicks **Dispatch Depot → Incident Site** (or
  **Hospital → Emergency Call**) and immediately sees **Standard Route** (blocked/flooded in red)
  vs **UrbanFLOW Safe Detour** (green), plus the added travel time.

**Module C — Resource Allocation & Fleet State Tracker.** Give the operator a finite pool of assets.

- *Simulated inventory:* e.g. **12 mobile dewatering pumps**, **8 automated underpass barriers**,
  **6 traffic warden squads** at known depots across the catchment.
- *Greedy / nearest-available assignment:* when a node crosses critical threshold, compute the
  fastest **flood-safe** route from available depots, recommend the optimal unit, and show **ETA**
  against the **predicted time to peak inundation**.

**Module D — Command Center UI.** Dark-mode, single-screen tactical dashboard, no scrolling,
four zones:

1. **Top telemetry & control bar** — catchment selector (benchmarked Bengaluru sub-catchments);
   storm simulator (rainfall **10–120 mm/hr**, duration **15–180 min**, conservative safety margin
   toggle); live KPI strip (inference latency ms, critical nodes flagged, blocked road km,
   available pumps).
2. **Centre interactive digital twin map (~70% of screen)** — road edges coloured by depth
   (cyan → amber → pulsing crimson); icons for depots, hospitals, underpasses, active pumps;
   clicking a pulsing hazard opens a **Node Inspector Card** with exact depth (cm), local terrain
   metrics (sink depression / slope), historical SWMM validation error margin, and a one-click
   **"Dispatch Nearest Unit"** button.
3. **Right-side live dispatch queue** — ranked feed sorted by **consequence score**, not raw depth.
   Each card: **`[Approve & Dispatch]`** (locks a pump, draws its route, starts an ETA countdown)
   and **`[Dismiss / False Alarm]`**.
4. **Bottom situation log & audit trail** — terminal-style live log of every inference run,
   automated barrier trigger, and human approval, with timestamps.

### 3. Recommended tech stack (clean separation of concerns)

- **Inference layer (existing):** current Python/PyTorch HydroGINE-v5 FastAPI/Flask service
  returning GeoJSON.
- **Decision & routing layer (new Python service):** FastAPI + **NetworkX** (real-time
  penalty-weighted routing, greedy pump-to-node matching) + **Shapely/GeoPandas** (snapping POIs to
  graph nodes once at startup).
- **Frontend dashboard:** React + TypeScript + **Mapbox GL JS** (or Deck.gl / Leaflet) + Tailwind,
  using Deck.gl `PathLayer` and `ScatterplotLayer` — handles 76,000+ nodes at 60 FPS.

### 4. End-to-end demo workflow

1. **Baseline calm state** — 15 mm/hr light rain, all roads green, 12 pumps idle, latency badge
   ~85 ms.
2. **Cloudburst escalation** — drag rainfall to 95 mm/hr, toggle Red-Alert ON. Within ~100 ms major
   underpasses pulse crimson and 6 high-priority alerts populate the queue.
3. **Tactical response** — `[Approve & Dispatch]` the top underpass alert; map draws the flood-safe
   detour from the nearest depot avoiding two submerged arterials; pump status → *En Route
   (ETA: 11 min)*.
4. **Emergency rerouting** — test an ambulance corridor hospital → residential zone; system
   reroutes around flooded junctions that standard GPS would drive straight into.
