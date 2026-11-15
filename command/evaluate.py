"""Offline benchmark & baseline comparison against genuine EPA SWMM 5.2 ground truth.

Run from repository root:
  .venv/bin/python -m command.evaluate

Produces:
  - scratch/evaluation/baseline-comparison.md
  - scratch/evaluation/baseline-comparison.json
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Set, Tuple

import numpy as np

from command.config import (
    ASSET_WEIGHT,
    CRITICAL_ASSET_WEIGHT_MIN,
    EVAL_DIR,
)
from command.loader import CatchmentData, CommandRegistry, get_registry
from command.routing import route_nodes
from command.transit import evaluate_transit_corridors
from command.triage import triage_catchment, triage_scenario

DEV_CATCHMENTS = ["hsr", "bellandur"]
HELD_OUT_CATCHMENTS = ["whitefield", "ecity", "koramangala"]
EVAL_INTENSITIES = [20, 80, 100, 120]
BUDGET_N = 12


def _true_critical_nodes(c: CatchmentData, swmm_depths: np.ndarray) -> Set[str]:
    out: Set[str] = set()
    for i, nid in enumerate(c.node_ids):
        if float(swmm_depths[i]) >= 0.30 and ASSET_WEIGHT.get(c.primary_asset[i], 0.25) >= CRITICAL_ASSET_WEIGHT_MIN:
            out.add(nid)
    return out


def _score_selected_nodes(
    selected_sets: List[Set[str]],
    true_critical: Set[str],
    budget: int = BUDGET_N,
) -> dict:
    picked = selected_sets[:budget]
    hits = sum(1 for s in picked if bool(s & true_critical))
    covered = set().union(*[s & true_critical for s in picked]) if picked else set()
    n_true = len(true_critical)
    prec = round(hits / float(budget), 4) if budget > 0 else 0.0
    rec = round(len(covered) / float(n_true), 4) if n_true > 0 else 0.0
    return {
        "hits_at_n": hits,
        "covered_true_critical": len(covered),
        "total_true_critical": n_true,
        "precision_at_n": prec,
        "recall_at_n": rec,
    }


def _evaluate_split(
    reg: CommandRegistry,
    catchment_keys: List[str],
    rain: int,
    mode: str = "normal",
) -> dict:
    true_crit: Set[str] = set()
    ours_alerts: List[dict] = []
    b0_alerts: List[dict] = []
    b1_candidates: List[Tuple[float, str]] = []
    wet_nodes: List[str] = []

    for ck in catchment_keys:
        c = reg.catchments[ck]
        swmm_d = c.swmm_truth.get(rain)
        if swmm_d is None:
            continue
        true_crit.update(_true_critical_nodes(c, swmm_d))

        tri = triage_catchment(reg, c, rain_mmhr=float(rain), duration_min=60.0, mode=mode)
        ours_alerts.extend(tri["alerts"])

        tri_50 = triage_catchment(reg, c, rain_mmhr=50.0, duration_min=60.0, mode=mode)
        b0_alerts.extend(tri_50["alerts"])

        depths = tri["depths"]
        for i, nid in enumerate(c.node_ids):
            d = float(depths[i])
            b1_candidates.append((d, nid))
            if d >= 0.08:
                wet_nodes.append(nid)

    ours_alerts.sort(key=lambda a: (-a["score"], -a["depth_m"], a["id"]))
    b0_alerts.sort(key=lambda a: (-a["score"], -a["depth_m"], a["id"]))
    b1_candidates.sort(key=lambda t: (-t[0], t[1]))

    ours_sets = [set(a["cluster_node_ids"]) for a in ours_alerts]
    b0_sets = [set(a["cluster_node_ids"]) for a in b0_alerts]
    b1_sets = [{nid} for _, nid in b1_candidates]

    # B2 random over 50 seeds from wet nodes
    rng = np.random.default_rng(42)
    b2_hits: List[float] = []
    b2_precs: List[float] = []
    b2_recs: List[float] = []
    n_true = len(true_crit)
    if len(wet_nodes) > 0:
        for _ in range(50):
            k = min(BUDGET_N, len(wet_nodes))
            draw = rng.choice(wet_nodes, size=k, replace=False)
            h = sum(1 for nid in draw if nid in true_crit)
            b2_hits.append(float(h))
            b2_precs.append(h / float(BUDGET_N))
            b2_recs.append(h / float(n_true) if n_true > 0 else 0.0)
    else:
        b2_hits, b2_precs, b2_recs = [0.0], [0.0], [0.0]

    return {
        "rain_mmhr": rain,
        "true_critical_count": n_true,
        "ours": _score_selected_nodes(ours_sets, true_crit),
        "b0_persistence_50": _score_selected_nodes(b0_sets, true_crit),
        "b1_depth_only": _score_selected_nodes(b1_sets, true_crit),
        "b2_random": {
            "hits_at_n": round(float(np.mean(b2_hits)), 2),
            "precision_at_n": round(float(np.mean(b2_precs)), 4),
            "recall_at_n": round(float(np.mean(b2_recs)), 4),
        },
        "wet_node_count": len(wet_nodes),
        "dedup_alert_count": len(ours_alerts),
    }


def main() -> None:
    os.makedirs(EVAL_DIR, exist_ok=True)
    reg = get_registry(load_model=True)

    held_out = [_evaluate_split(reg, HELD_OUT_CATCHMENTS, r, "normal") for r in EVAL_INTENSITIES]
    dev_res = [_evaluate_split(reg, DEV_CATCHMENTS, r, "normal") for r in EVAL_INTENSITIES]

    # Dedup & Red-Alert check on severe 95 mm/hr across all 5 catchments
    tri_95_norm = triage_scenario(reg, "all", 95.0, 60.0, "normal")
    tri_95_red = triage_scenario(reg, "all", 95.0, 60.0, "red_alert")

    # Transit stress across regimes
    transit_summary = {}
    for r in (50.0, 95.0, 120.0):
        tri = triage_scenario(reg, "all", r, 60.0, "red_alert" if r >= 95.0 else "normal")
        tr = evaluate_transit_corridors(
            reg, tri["depths_by_catchment"], frozenset(), scenario_key=f"eval_{r}", region="all"
        )
        transit_summary[str(int(r))] = tr["summary"]

    # Routing speed sample (20 intra-catchment routes on flooded koramangala)
    krm = reg.catchments["koramangala"]
    scc = [n for n in krm.node_ids if n in krm.scc_nodes]
    t0 = time.perf_counter()
    for idx in range(20):
        route_nodes(
            reg,
            scc[idx * 5],
            scc[(idx * 5 + 150) % len(scc)],
            tri_95_norm["depths_by_catchment"],
            vehicle="pump_truck",
            scenario_key="eval_95",
        )
    route_20_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    report = {
        "dev_catchments": DEV_CATCHMENTS,
        "held_out_catchments": HELD_OUT_CATCHMENTS,
        "budget_n": BUDGET_N,
        "critical_definition": "swmm_depth_m >= 0.30 and asset_weight >= 0.85",
        "held_out": held_out,
        "dev": dev_res,
        "dedup_95_normal": tri_95_norm["stats"],
        "dedup_95_red_alert": tri_95_red["stats"],
        "transit_summary": transit_summary,
        "routing_20_krm_ms": route_20_ms,
    }

    json_path = os.path.join(EVAL_DIR, "baseline-comparison.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    lines = [
        "# UrbanFLOW Decision Layer — Held-Out Baseline Evaluation",
        "",
        "Measured offline against genuine EPA SWMM 5.2 node depths (`data/command/eval_swmm_truth.json`).",
        "",
        f"- **Dev split:** {', '.join(DEV_CATCHMENTS)}",
        f"- **Held-out split:** {', '.join(HELD_OUT_CATCHMENTS)}",
        f"- **True Critical Target:** `swmm_depth_m >= 0.30` at high-criticality municipal assets (`ASSET_WEIGHT >= {CRITICAL_ASSET_WEIGHT_MIN}`, i.e. underpasses, hospitals, transit hubs, fire stations, substations).",
        f"- **Dispatch Budget:** `N = {BUDGET_N}` top-ranked recommendations across the held-out catchments.",
        "",
        "## Held-Out Triage@12 Comparison",
        "",
        "| Rain (mm/hr) | True Critical | Ours Hits@12 (P@12 / R@12) | B0 Persistence Hits@12 | B1 Depth-Only Hits@12 | B2 Random Hits@12 |",
        "| ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in held_out:
        o = row["ours"]
        b0 = row["b0_persistence_50"]
        b1 = row["b1_depth_only"]
        b2 = row["b2_random"]
        lines.append(
            f"| {row['rain_mmhr']} | {row['true_critical_count']} | "
            f"**{o['hits_at_n']}** ({o['precision_at_n']:.3f} / {o['recall_at_n']:.3f}) | "
            f"{b0['hits_at_n']} ({b0['precision_at_n']:.3f} / {b0['recall_at_n']:.3f}) | "
            f"{b1['hits_at_n']} ({b1['precision_at_n']:.3f} / {b1['recall_at_n']:.3f}) | "
            f"{b2['hits_at_n']:.2f} ({b2['precision_at_n']:.3f} / {b2['recall_at_n']:.3f}) |"
        )

    lines.extend(
        [
            "",
            "## Spatial Deduplication & System Speed (5 Catchments, 12,436 Nodes)",
            "",
            f"- **95 mm/hr Normal mode:** {tri_95_norm['stats']['raw_above_floor']} raw nodes >= 0.08m -> "
            f"{tri_95_norm['stats']['raw_eligible']} eligible -> **{tri_95_norm['stats']['dedup_alerts']} deduplicated clusters** "
            f"({tri_95_norm['stats']['suppressed']} low-consequence watch nodes suppressed, "
            f"blocked roads `{tri_95_norm['stats']['blocked_km']} km`, "
            f"wall time `{tri_95_norm['stats']['triage_wall_ms']} ms`).",
            f"- **95 mm/hr Red-Alert mode:** {tri_95_red['stats']['dedup_alerts']} clusters, "
            f"{tri_95_red['stats']['critical_nodes']} critical nodes flagged (`triage_wall_ms={tri_95_red['stats']['triage_wall_ms']} ms`).",
            f"- **20 Flooded Koramangala Routes (4,416 nodes / 11,183 edges):** `{route_20_ms} ms` total (`{route_20_ms / 20.0:.2f} ms/route`).",
            "",
            "## BMTC Bus Corridor Flood Status (Held + Dev Combined)",
            "",
            "| Intensity | Normal | Diverted (Safe Detour) | Suspended |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for k, sm in transit_summary.items():
        lines.append(f"| {k} mm/hr | {sm['normal']} | {sm['diverted']} | {sm['suspended']} |")

    lines.extend(
        [
            "",
            "## Failure Cases & Limitations",
            "",
            "- **Low-rainfall floor (20 mm/hr):** Minimal surface ponding produces very few true SWMM critical nodes above `0.30 m`, making consequence ranking and baselines nearly tied or zero-signal on held-out catchments.",
            "- **Extreme cloudburst (>80 mm/hr):** Raw HydroGINE-v5 exhibits low-bias conservative recall at 100 mm/hr (documented 32.2% critical recall); Red-Alert lowers Barrier/Pump action triggers (`0.09 m` / `0.25 m`) to widen operational safety margins while preserving node-ranking order.",
            "- **Disconnected catchment graphs:** Inter-catchment pump dispatches incur an explicit `20.0 min` transfer penalty across an off-graph arterial stub.",
        ]
    )

    md_path = os.path.join(EVAL_DIR, "baseline-comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
