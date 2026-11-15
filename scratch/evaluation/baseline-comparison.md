# UrbanFLOW Decision Layer — Held-Out Baseline Evaluation

Measured offline against genuine EPA SWMM 5.2 node depths (`data/command/eval_swmm_truth.json`).

- **Dev split:** hsr, bellandur
- **Held-out split:** whitefield, ecity, koramangala
- **True Critical Target:** `swmm_depth_m >= 0.30` at high-criticality municipal assets (`ASSET_WEIGHT >= 0.85`, i.e. underpasses, hospitals, transit hubs, fire stations, substations).
- **Dispatch Budget:** `N = 12` top-ranked recommendations across the held-out catchments.

## Held-Out Triage@12 Comparison

| Rain (mm/hr) | True Critical | Ours Hits@12 (P@12 / R@12) | B0 Persistence Hits@12 | B1 Depth-Only Hits@12 | B2 Random Hits@12 |
| ---: | ---: | --- | --- | --- | --- |
| 20 | 0 | **0** (0.000 / 0.000) | 0 (0.000 / 0.000) | 0 (0.000 / 0.000) | 0.00 (0.000 / 0.000) |
| 80 | 6 | **5** (0.417 / 0.833) | 5 (0.417 / 0.833) | 1 (0.083 / 0.167) | 0.02 (0.002 / 0.003) |
| 100 | 8 | **5** (0.417 / 0.625) | 5 (0.417 / 0.625) | 0 (0.000 / 0.000) | 0.04 (0.003 / 0.005) |
| 120 | 8 | **5** (0.417 / 0.625) | 5 (0.417 / 0.625) | 0 (0.000 / 0.000) | 0.00 (0.000 / 0.000) |

## Spatial Deduplication & System Speed (5 Catchments, 12,436 Nodes)

- **95 mm/hr Normal mode:** 3714 raw nodes >= 0.08m -> 3468 eligible -> **30 deduplicated clusters** (246 low-consequence watch nodes suppressed, blocked roads `613.06 km`, wall time `361.18 ms`).
- **95 mm/hr Red-Alert mode:** 30 clusters, 2997 critical nodes flagged (`triage_wall_ms=35.21 ms`).
- **20 Flooded Koramangala Routes (4,416 nodes / 11,183 edges):** `33.57 ms` total (`1.68 ms/route`).

## BMTC Bus Corridor Flood Status (Held + Dev Combined)

| Intensity | Normal | Diverted (Safe Detour) | Suspended |
| ---: | ---: | ---: | ---: |
| 50 mm/hr | 1 | 4 | 1 |
| 95 mm/hr | 0 | 2 | 4 |
| 120 mm/hr | 0 | 2 | 4 |

## Failure Cases & Limitations

- **Low-rainfall floor (20 mm/hr):** Minimal surface ponding produces very few true SWMM critical nodes above `0.30 m`, making consequence ranking and baselines nearly tied or zero-signal on held-out catchments.
- **Extreme cloudburst (>80 mm/hr):** Raw HydroGINE-v5 exhibits low-bias conservative recall at 100 mm/hr (documented 32.2% critical recall); Red-Alert lowers Barrier/Pump action triggers (`0.09 m` / `0.25 m`) to widen operational safety margins while preserving node-ranking order.
- **Disconnected catchment graphs:** Inter-catchment pump dispatches incur an explicit `20.0 min` transfer penalty across an off-graph arterial stub.
