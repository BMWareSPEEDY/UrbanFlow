# Decision Log

> Append-only. Never delete an entry — supersede it and mark the old one `SUPERSEDED by D-xx`.
> Every irreversible choice made while building the Command Layer gets a row here, with the
> consequence of being wrong.

Status legend: **DECIDED** · **PROPOSED** (needs author sign-off) · **OPEN** · **SUPERSEDED**

| # | Date | Decision | Status | Rationale / consequence |
|---|---|---|---|---|
| **D-01** | 2026-11-14 | `git init` the repository before any new file is added | **DECIDED — done** | Resolved 2026-11-14. `git init`, branch renamed `master`→`main`, baseline commit `chore: initialise repository at baseline (pre-Command-Layer)` on 507 files, work continues on branch `command-layer`. `.git` is 251 MB (graphs + models); acceptable for a local-only repo. Node 25.9 / npm 11.13 / pnpm are installed, which unblocks D-02(b). |
| **D-02** | 2026-11-14 | Frontend stack: (a) deck.gl UMD + vanilla ES modules, no build step; (b) deck.gl + React + TS via Vite; (c) stay on Leaflet | **SUPERSEDED by D-17** | Original recommendation was (a) on the assumption that no Node toolchain existed. That assumption was wrong — see D-17. |
| **D-03** | 2026-11-14 | Decision layer runs as a **separate Starlette service on :8000**, not as new Flask blueprints in `app.py` | **PROPOSED** | Protects the 1,500-line inference file from a hot-editing failure, and isolates routing hangs from the model. Cost: second process + CORS, mitigated by `dev.sh` and a one-line Flask proxy. `fastapi` is **not installed**; Starlette 1.4 + uvicorn already are, so no new dependency. |
| **D-04** | 2026-11-14 | POIs come from OSM Overpass **with a mandatory name-table fallback** derived from `JUNCTION_NAMES` | **DECIDED** | Overpass is unreliable at hackathon venues. `app.py:740` already encodes real POI semantics in English ("Silk Board Underpass Ramp"). The rule is explicit: fewer than 5 Overpass POIs → use the fallback. Never ship an empty POI layer. |
| **D-05** | 2026-11-14 | One threshold ladder lives in `command/config.py`; the three ladders currently in `app.py` (`0.05/0.15/0.30`, `0.05/0.15/0.35`, `>0.08` filter) are **not** modified | **DECIDED** | The research dashboard and the paper depend on existing semantics. The Command Layer maps to its own ladder at the boundary and documents the mapping. |
| **D-06** | 2026-11-14 | Triage reads `nodes[]`, never `risk_nodes[]` | **DECIDED** | `risk_nodes` is truncated to 30 rows (`app.py:1074`); with 400+ nodes above 0.08 m the queue would silently lose alerts. |
| **D-07** | 2026-11-14 | Routing speed penalty is a single physical expression `((d_imp − d)/(d_imp − 0.05))^1.5`, **not** a hand-tuned congestion constant | **DECIDED** | Reproduces the brief's requested curve (normal → steep → impassable) from one monotone formula, with no magic number to defend. At `d_imp=0.25`: 15 cm → 3.1× slower, 20 cm → 8.7×, ≥25 cm → impassable. |
| **D-08** | 2026-11-14 | Consequence score weights `0.45 S + 0.30 A + 0.15 V + 0.10 N` | **DECIDED** | Depth dominates but cannot override asset criticality — this is what produces the hospital-beats-deep-lane ranking inversion that the demo turns on. Weights are config, asserted to sum to 1.0. |
| **D-09** | 2026-11-14 | Red-Alert mode moves the **barrier** trigger most (`0.15→0.09`) and the **pump** trigger less (`0.30→0.25`) | **DECIDED** | Compensates the measured 32.2 % critical recall at 100 mm/hr. Barriers are cheap and reversible; pumps are scarce. Aggression belongs on the reversible action. |
| **D-10** | 2026-11-14 | Assignment is **greedy nearest-feasible**, explicitly not a VRP/MILP optimiser | **DECIDED** | Explainable in one sentence on stage, deterministic, <1 ms. A solver would be defensible engineering but indefensible demo pacing and impossible to debug live. |
| **D-11** | 2026-11-14 | All actuation is **simulated** and labelled as such in the UI and audit log | **DECIDED** | There is no actuator integration and no authority to close a real gate. A persistent `SIMULATION` badge and `actor: system(simulated)` in the log prevent an overclaim that would be a genuine safety and ethics problem. |
| **D-12** | 2026-11-14 | Simulation clock with `POST /fleet/tick` and a "1 min = 1 s" toggle, rather than wall-clock ETAs | **DECIDED** | A 11-minute ETA cannot be demonstrated in a 4-minute pitch. Every audit timestamp uses `sim_now`, with `wall_ts` retained. |
| **D-13** | 2026-11-14 | Slider ranges: align the UI to the model's existing clamps (rain 20–300, duration 15–120) rather than relaxing `app.py` | **OPEN** | The brief asks for 10–120 mm/hr and 15–180 min. Relaxing the clamp changes what the surrogate is being asked to predict, in a region where it is already known to under-predict. **Recommendation: ship 20–120 mm/hr and 15–120 min, which covers every scenario in the demo script.** |
| **D-14** | 2026-11-14 | Demo catchment scope: one Bengaluru catchment vs all five (12,436 nodes) vs all sixteen (76,316) | **DECIDED — all five** | Author's call. Five catchments = 12,436 nodes / 29,717 edges, which is deck.gl-trivial and keeps the "city" feel. Consequences: (1) triage and routing must run per-catchment and be merged into one queue, because the five graphs are **disconnected** — a pump in HSR cannot drive to Whitefield through a graph that has no edges between them; (2) depots and fleet must therefore be modelled **city-wide with a manual inter-catchment travel stub** (great-circle distance ÷ 12 m/s, flagged `inter_catchment: true` in the audit log); (3) the KPI "blocked road km" becomes a sum across five graphs; (4) never quote 76,316 as the live scene. |
| **D-15** | 2026-11-14 | Fleet shared city-wide across catchments | **OPEN** | Author asked for an explanation (see below). Shared pool creates the scarcity that makes the product a *decision*; per-catchment pools are simpler but delete the central tension. **Recommendation: shared city-wide**, 12 pumps / 8 barriers / 6 warden squads across the five catchments. |
| **D-16** | 2026-11-14 | Audit trail as append-only JSONL on disk, fsynced per event | **DECIDED** | Queryability is not needed in V1; durability and "it is a file I can `tail -f` on stage" are. SQLite is the V2 path if the operator model grows. |
| **D-17** | 2026-11-14 | Frontend = **React 19 + TypeScript + Vite + deck.gl + Tailwind**, one app in `web/`, build output committed to `static/command/` and served by Flask | **DECIDED — scaffolded & verified** | Supersedes D-02. Node 25.9 / npm 11.13 / pnpm are installed (verified), so the "no build step" objection to React is void. **The build step is at build time, not demo time** — `npm run build` emits hashed static assets, so `python app.py` remains a single command and the demo has no Node dependency. Chosen because the brief asks for the best possible output, and React/TS is what makes a screen with 6 queue cards, a fleet strip, an inspector, and a live log maintainable rather than 2,500 lines of imperative DOM. Tailwind + a small token layer replaces the 1,539-line hand-written stylesheet. **Outcome:** the four-zone shell builds in 1.9 s (1.04 MB / 300 kB gzip), renders with zero console errors and zero page scroll at 1920×1080 and 1366×768, and the rainfall slider + Red-Alert toggle drive a live, deduplicated 6-alert queue. Basemap is **MapLibre + OSM raster, not Mapbox** — Mapbox GL JS needs a paid access token, which would be a demo-day outage waiting to happen. |

---

## D-15 explained — what these "pumps" actually are

The brief says "12 mobile dewatering pumps" without saying what that means operationally. In an
Indian municipal flood response this is a **trailer-mounted diesel pump set** — typically
1,000–3,000 L/min, towed to a flooding underpass or junction by a truck, hoses dropped into the
standing water and run out to the nearest storm drain, canal, or lake outfall. Bengaluru's BBMP and
the fire service both run these. They are the primary physical remedy for a flooded underpass,
because the water will not drain on its own when the outfall is already surcharged.

So "a pump" in this product is a **unit with a location, a state, and a clock**:

| Property | Value in our model |
|---|---|
| Where it starts | one of 6 depots |
| Status | `IDLE` / `EN_ROUTE` / `ON_SITE` / `DEWATERING` / `RETURNING` |
| How fast it moves | 0.8 × road speed, and it cannot enter water ≥ 0.25 m |
| How long it works | ~45–90 simulated minutes to clear a 0.30 m node |
| How many exist | **12, and that is the whole point** |

### The resource problem, in one paragraph

At 95 mm/hr across the five Bengaluru catchments, the triage layer will flag far more than twelve
P1/P2 nodes. Twelve pumps cannot cover them. The operator must therefore **choose**, and the product
exists to make that choice defensible: which node gets the first pump is a consequence score, not a
gut feeling. When the twelfth pump leaves, the thirteenth alert must visibly say *"no unit
available — nearest free pump is 38 minutes away, peak is in 22"* rather than silently recommend
something impossible.

### The two options, concretely

**Option A — shared city-wide pool (recommended).** One pool of 12 pumps, 8 barriers, 6 warden
squads covering HSR + Bellandur + Whitefield + E-City + Koramangala. A pump based in HSR can be sent
to Whitefield. This is realistic (a city does move units between wards) and it produces the scarcity
that makes the dashboard a decision tool: the KPI reads `6 / 12`, and one catchment under a cloudburst
can starve another.

**Option B — per-catchment pools.** Each catchment gets its own small pool (e.g. 3 pumps each). Every
local crisis can be solved locally, so the queue never runs out, so the operator never has to
choose, so the product has no tension and the "Available Pumps" KPI never moves in an interesting
way. It is easier to build (no inter-catchment travel logic at all) and it is a weaker demo.

**Why A is recommended despite being harder:** Option B removes the only mechanism that distinguishes
this from a map with coloured lines. The whole claim — *"we tell you what to do first"* — is only
testable when you cannot do everything.

### The one technical cost of A

The five catchment graphs are **disconnected** (separate `.graphml` files, no shared nodes). A pump
therefore cannot be routed from HSR to Whitefield through the graph. The fix is a stub route:
great-circle distance between the two catchment centroids ÷ 12 m/s, added as a fixed leg with
`inter_catchment: true` in the audit log. That is ~15 lines of code and it is honest — we are
modelling the highway leg that our street graph does not cover.
