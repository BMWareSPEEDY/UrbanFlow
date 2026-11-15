# UrbanFLOW Command & Dispatch

**Track:** AI + Climate  
**Team:** Ayansh Paliwal (`ayanshpaliwal2012@gmail.com`) — The International School Bangalore (TISB)  
**One-Page Write-Up (PDF):** [docs/UrbanFLOW_Veritas_AI_Writeup.pdf](docs/UrbanFLOW_Veritas_AI_Writeup.pdf)

# The problem
During Bengaluru monsoon cloudbursts, municipal flood-control rooms and BMTC transit dispatchers must decide within minutes where to send limited mobile pumps, which underpasses to lock, and how to reroute buses and emergency vehicles. Standard GPS routing ignores street-level water depth, sending vehicles into flooded underpasses while crews lack a real-time, asset-weighted priority queue.

# What we built
**UrbanFLOW** is an end-to-end flood prediction and municipal dispatch command system. Operators input shift fleet counts (`0–30` Mobile Pumps, `0–24` Underpass Barriers, `0–24` Traffic Wardens), target catchment, rainfall intensity (`20–120 mm/hr`), and safety mode (`Normal` vs. `Red-Alert`) to get:
1. A spatially deduplicated **Priority Directives** queue with explicit **WHERE / WHAT / WHEN** deployment orders constrained to actual unit availability.
2. **Flood-safe vs. flood-naive A/B corridor detours** for 6 BMTC bus corridors (`500D`, `500A`, `201R`, `335E`, `356C`, `KIA-7A`) and custom map pins using vehicle-clearance profiles.
3. **Live unit state tracking** (`IDLE -> EN_ROUTE -> DEWATERING -> RETURNING -> IDLE`) with a 60-second barrier closure veto window and an append-only JSONL audit log.

# What we added
**Our own idea:** Rather than stopping at nodal flood-depth prediction, I coupled my custom-trained hydraulic Graph Neural Network (`HydroGINE-v5`) with closed-form consequence scoring (`0.45 * Severity + 0.30 * Asset + 0.15 * Vulnerability + 0.10 * Network`), `200 m` STRtree spatial clustering, vehicle-clearance-aware Dijkstra routing, and fleet scarcity simulation.

# How it works
- **Data:** Five Bengaluru street-network catchments (HSR Layout, Bellandur, Whitefield, Electronic City, Koramangala) totaling **12,436 junctions and 29,717 road edges** extracted from OpenStreetMap, paired with hydrodynamic ground-truth simulations generated in **EPA SWMM 5.2**, elevation/sink features, and snapped municipal POIs (hospitals, underpasses, substations).
- **Model (`HydroGINE-v5`):** Custom-trained 4-member, 6-layer Graph Isomorphism Network with a **Directional Gravity Gate**, **Topological Mixture-of-Experts (MoE)**, 32 scale-invariant node features + 6 edge attributes (zero raw coordinates for zero-shot geographic transferability), and a **Decoupled FiLM Dual-Head** (solving `80.9%` zero-inflation collapse), followed by **2.1 ms Physical Continuity Bounding**. Exact `float32` predictions are cached onto `precompute_grid.npz` for sub-300 ms interactive scenario updates.

# Results

### HydroGINE-v5 vs. EPA SWMM 5.2 Simulation
| Benchmark / Regime | Key Metrics vs. EPA SWMM 5.2 |
| --- | --- |
| **Global (16 Cities · 76,316 Nodes)** | **0.9128 NSE** · **2.44 cm MAE** · **90.8% F1** (88.7% Recall) · **85.5 ms** (~1,310–8,690× faster) |
| **Literal 100 mm/hr Stress Test** | **98.8% Prec** · **76.7% Rec** · **86.4% F1** (>15 cm) · 79.4% within ±15 cm · 17.93 cm MAE |
| **Bengaluru Triage (100 mm/hr, N=12)** | **0.750 Recall@12** vs. 0.500 Persistence (50 mm/hr), 0.000 Raw Depth, 0.010 Random Wet |

### Against Real-World Data (October 2024 Bengaluru Monsoon)
Evaluated against **13 geotagged, news-documented flood locations** (*The Hindu, Times of India, New Indian Express, Moneycontrol*; provenance in `data/real_bengaluru_oct2024_incidents.json`) across three October 2024 rain events (`65 mm` Oct 15; `106–141 mm` Oct 20; `186.2 mm` GKVK cloudburst Oct 22). At `100 mm/hr`, UrbanFLOW captured **5 of 13 locations (38.5%)** within a `50 m` radius of a predicted hazard node (`≥ 0.15 m`): Koramangala and Bellandur locations matched within `10–34 m`, while HSR, Whitefield, and Electronic City lay `83–356 m` away.

### Where It Fails
- **10 m DEM Smoothing:** Sub-10 m micro-topography (curbs, underpass ramps) is smoothed in public DEMs, shifting localized ponding depths.
- **Extreme Tail Cloudbursts (`≥ 100 mm/hr`):** Conservative under-prediction on severe tail events (`32.2%` critical `>30 cm` recall); mitigated by **Red-Alert Mode** lowering barrier/pump triggers (`0.09 m / 0.25 m`).
- **Design-Capacity Assumption:** Assumes unclogged stormwater conduits and pluvial-only forcing without real-time siltation or tidal backwater.

# What we'd do next
1. **Sub-Meter LiDAR & Node Data:** Ingest `0.5–1 m` DEMs, improved OpenStreetMap road/culvert geometry, and municipal drain-invert surveys.
2. **Live Telemetry & Tail Fine-Tuning:** Fuse live IoT rain gauges (KSNDMC), IMD Doppler radar nowcasts, and BMTC GTFS-RT bus feeds, and fine-tune `HydroGINE-v5` on synthetic `100–130 mm/hr` EPA SWMM 5.2 cloudbursts.

# Sources
- **Model:** Custom-trained `HydroGINE-v5` (`EnsembleFloodPredictorV4`) by Ayansh Paliwal.
- **Datasets & Geometry:** [OpenStreetMap](https://www.openstreetmap.org/), [EPA SWMM 5.2](https://www.epa.gov/water-research/storm-water-management-model-swmm), [OSRM](https://project-osrm.org/), and October 2024 Bengaluru news archive (`data/real_bengaluru_oct2024_incidents.json`).
- **Open-Source Stack:** [PyTorch](https://pytorch.org/), [PyTorch Geometric](https://pyg.org/), [Flask](https://flask.palletsprojects.com/), [NetworkX](https://networkx.org/), [Shapely](https://shapely.readthedocs.io/), [React](https://react.dev/), [MapLibre GL](https://maplibre.org/), [Deck.gl](https://deck.gl/), [Tailwind CSS](https://tailwindcss.com/).
- **AI Coding Tool:** Antigravity (Google Deepmind) used to accelerate UI/UX iteration, backend optimization, and testing.

---

## Quickstart & Tests

```bash
# 1. Start the unified Command API & built Deck.gl frontend on :8000
.venv/bin/python -m command.app
# Open http://127.0.0.1:8000/

# 2. Run Gate A–D & Loader Parity unit/API tests (25 tests)
.venv/bin/python -m pytest command/tests -q

# 3. Run held-out EPA SWMM 5.2 baseline evaluation
.venv/bin/python -m command.evaluate
```
