"""Consequence-based flood triage, threshold classification, and 200 m clustering.

Implements IMPLEMENTATION_PLAN §5.3–§5.5 deterministically on top of raw
EnsembleFloodPredictorV4 predictions, keeping inference cached and stateless so
fleet/routing can layer live unit feasibility cleanly on top.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.strtree import STRtree

from command.config import (
    ASSET_WEIGHT,
    CLUSTER_RADIUS_M,
    DURATION_CLAMP,
    PRIORITY_THRESHOLDS,
    RAINFALL_CLAMP,
    SEVERITY_MAX_M,
    SEVERITY_MIN_M,
    THRESHOLDS,
    TRIAGE_WEIGHTS,
)
from command.loader import CatchmentData, CommandRegistry

_CACHE_LOCK = threading.Lock()
_INFER_CACHE: "OrderedDict[Tuple[str, float, float], Dict[str, Any]]" = OrderedDict()
_MAX_CACHE_ENTRIES = 512
_EDGE_ARRAYS: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[str, ...]]] = {}
_PRECOMPUTED_GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "command" / "precompute_grid.npz"
_PRECOMPUTED_GRID: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
_PRECOMPUTED_LOADED = False


def _ensure_precomputed_grid(reg: CommandRegistry) -> None:
    global _PRECOMPUTED_LOADED
    if _PRECOMPUTED_LOADED:
        return
    with _CACHE_LOCK:
        if _PRECOMPUTED_LOADED:
            return
        _PRECOMPUTED_LOADED = True
        if not _PRECOMPUTED_GRID_PATH.exists():
            return
        try:
            with np.load(_PRECOMPUTED_GRID_PATH, allow_pickle=False) as z:
                rains = z["rains"]
                durs = z["durs"]
                for ck, c in reg.catchments.items():
                    dk = f"depths_{ck}"
                    rek = f"r_early_{ck}"
                    rmk = f"r_mid_{ck}"
                    if dk not in z or rek not in z or rmk not in z:
                        continue
                    d_arr = z[dk]
                    re_arr = z[rek]
                    rm_arr = z[rmk]
                    expected = (len(rains), len(durs), len(c.node_ids))
                    if d_arr.shape != expected:
                        continue
                    for ri, rv in enumerate(rains):
                        for di, dv in enumerate(durs):
                            r_f = round(float(rv), 1)
                            d_f = round(float(dv), 1)
                            _PRECOMPUTED_GRID[(ck, r_f, d_f)] = {
                                "depths": np.ascontiguousarray(d_arr[ri, di], dtype=np.float32),
                                "r_early": np.ascontiguousarray(re_arr[ri, di], dtype=np.float32),
                                "r_mid": np.ascontiguousarray(rm_arr[ri, di], dtype=np.float32),
                                "dur": float(dv),
                                "rain": float(rv),
                                "latency_ms": 0.05,
                            }
        except Exception:
            _PRECOMPUTED_GRID.clear()


def _get_edge_arrays(c: CatchmentData) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[str, ...]]:
    cached = _EDGE_ARRAYS.get(c.key)
    if cached is not None:
        return cached
    u_idx = np.fromiter((e.u_idx for e in c.edges), dtype=np.int32, count=len(c.edges))
    v_idx = np.fromiter((e.v_idx for e in c.edges), dtype=np.int32, count=len(c.edges))
    lengths = np.fromiter((e.length_m for e in c.edges), dtype=np.float64, count=len(c.edges))
    eids = tuple(e.eid for e in c.edges)
    res = (u_idx, v_idx, lengths, eids)
    _EDGE_ARRAYS[c.key] = res
    return res


def clamp01(val: float) -> float:
    """Clamp scalar value to [0.0, 1.0]."""
    return max(0.0, min(1.0, float(val)))


def compute_node_score(
    depth_m: float,
    primary_asset: str,
    sink_ratio: float,
    betweenness: float,
) -> float:
    """Exact §5.3 scalar Consequence Score CS in [0.0, 100.0] rounded to 0.1."""
    s = clamp01((depth_m - SEVERITY_MIN_M) / (SEVERITY_MAX_M - SEVERITY_MIN_M))
    a = ASSET_WEIGHT.get(primary_asset, ASSET_WEIGHT["street"])
    v = clamp01(
        0.45 * float(depth_m > 0.18)
        + 0.35 * min(1.0, max(0.0, depth_m) / 0.30)
        + 0.20 * clamp01(sink_ratio)
    )
    n = clamp01(betweenness)
    raw = 100.0 * (
        TRIAGE_WEIGHTS["severity"] * s
        + TRIAGE_WEIGHTS["asset"] * a
        + TRIAGE_WEIGHTS["vulnerability"] * v
        + TRIAGE_WEIGHTS["network"] * n
    )
    return round(raw, 1)


def compute_scores_vectorized(
    depths_m: np.ndarray,
    asset_weights: np.ndarray,
    sink_ratio: np.ndarray,
    betweenness: np.ndarray,
) -> np.ndarray:
    """Vectorized NumPy implementation matching `compute_node_score` identically."""
    d = depths_m.astype(np.float64, copy=False)
    s = np.clip((d - SEVERITY_MIN_M) / (SEVERITY_MAX_M - SEVERITY_MIN_M), 0.0, 1.0)
    v = np.clip(
        0.45 * (d > 0.18).astype(np.float64)
        + 0.35 * np.minimum(1.0, np.maximum(0.0, d) / 0.30)
        + 0.20 * np.clip(sink_ratio, 0.0, 1.0),
        0.0,
        1.0,
    )
    raw = 100.0 * (
        TRIAGE_WEIGHTS["severity"] * s
        + TRIAGE_WEIGHTS["asset"] * asset_weights
        + TRIAGE_WEIGHTS["vulnerability"] * v
        + TRIAGE_WEIGHTS["network"] * np.clip(betweenness, 0.0, 1.0)
    )
    return np.round(raw, 1)


def classify_band(depth_m: float, mode: str) -> str:
    """Map predicted water depth (m) and operator mode into severity band."""
    th = THRESHOLDS.get(mode, THRESHOLDS["normal"])
    if depth_m >= th["pump"]:
        return "pump"
    if depth_m >= th["barrier"]:
        return "barrier"
    if depth_m >= th["alert_floor"]:
        return "watch"
    return "dry"


def classify_priority(score: float, band: str) -> str:
    """Map Consequence Score + band into P1/P2/P3/suppressed."""
    if band == "dry":
        return "suppressed"
    for label, floor in PRIORITY_THRESHOLDS:
        if score >= floor:
            return label
    return "suppressed"


def classify_action(
    band: str,
    primary_asset: str,
    assets: Sequence[str],
) -> Tuple[str, str, str]:
    """Return `(action_code, action_label, unit_class)` for a triaged cluster."""
    # Safety first: an inundated underpass is closed to traffic before anyone
    # pumps it. Without this, an underpass that floods past the pump threshold
    # (0.59-0.76 m at 95 mm/hr) is classified as pump_dispatch, which leaves the
    # entire barrier fleet idle and the 60 s veto path unreachable.
    if "underpass" in assets and band in ("barrier", "pump"):
        return "barrier_closure", "Barrier Close", "barrier"
    if band == "pump":
        return "pump_dispatch", "Pump Dispatch", "pump"
    if band == "barrier":
        if "underpass" in assets:
            return "barrier_closure", "Barrier Close", "barrier"
        if primary_asset in {"hospital", "transit_hub", "power_substation", "fire_station"}:
            return "pump_dispatch", "Pump Dispatch", "pump"
        return "warden_diversion", "Warden Diversion", "warden"
    if band == "watch":
        return "warden_diversion", "Warden Pre-Position", "warden"
    return "monitor", "Monitor", "none"


def infer_catchment(
    reg: CommandRegistry,
    c: CatchmentData,
    rain_mmhr: float,
    duration_min: float,
) -> Dict[str, Any]:
    """Run (and cache) EnsembleFloodPredictorV4 + 3-keyframe 12-step TTP profile."""
    rain = float(max(RAINFALL_CLAMP[0], min(RAINFALL_CLAMP[1], rain_mmhr)))
    dur = float(max(DURATION_CLAMP[0], min(DURATION_CLAMP[1], duration_min)))
    cache_key = (c.key, round(rain, 1), round(dur, 1))

    with _CACHE_LOCK:
        hit = _INFER_CACHE.get(cache_key)
        if hit is not None:
            _INFER_CACHE.move_to_end(cache_key)
            return hit

    _ensure_precomputed_grid(reg)
    pre = _PRECOMPUTED_GRID.get(cache_key)
    if pre is not None:
        with _CACHE_LOCK:
            _INFER_CACHE[cache_key] = pre
            _INFER_CACHE.move_to_end(cache_key)
            while len(_INFER_CACHE) > _MAX_CACHE_ENTRIES:
                _INFER_CACHE.popitem(last=False)
        return pre

    if reg.predictor is None:
        raise RuntimeError("GNN predictor not loaded in CommandRegistry")

    t0 = time.perf_counter()
    depths, _, _ = reg.predictor.predict(c.pyg_graph, rain, dur)
    depths = np.asarray(depths, dtype=np.float32)

    # Fast 12-frame SCS hyetograph envelope using primary ensemble member
    # Keyframes at normalized storm progress t_norm = 2/11 (ramp) & 5/11 (peak onset)
    if reg.predictor.members:
        m0 = reg.predictor.members[0]
        early_rain = max(RAINFALL_CLAMP[0], rain * (0.2 + 0.8 * ((2.0 / 11.0) / 0.3)))
        early_dur = max(DURATION_CLAMP[0], dur * 0.25)
        mid_dur = max(DURATION_CLAMP[0], dur * 0.50)
        d_early = np.asarray(m0.predict(c.pyg_graph, early_rain, early_dur)[0], dtype=np.float32)
        d_mid = np.asarray(m0.predict(c.pyg_graph, rain, mid_dur)[0], dtype=np.float32)
        d_end = np.asarray(m0.predict(c.pyg_graph, rain, dur)[0], dtype=np.float32)
        denom = np.maximum(d_end, 1e-4)
        r_early = np.clip(d_early / denom, 0.05, 1.0)
        r_mid = np.clip(np.maximum(d_mid / denom, r_early), 0.15, 1.0)
    else:
        r_early = np.full(len(depths), 0.45, dtype=np.float32)
        r_mid = np.full(len(depths), 0.85, dtype=np.float32)

    dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    payload = {
        "depths": depths,
        "r_early": r_early,
        "r_mid": r_mid,
        "dur": dur,
        "rain": rain,
        "latency_ms": dt_ms,
    }
    with _CACHE_LOCK:
        _INFER_CACHE[cache_key] = payload
        _INFER_CACHE.move_to_end(cache_key)
        while len(_INFER_CACHE) > _MAX_CACHE_ENTRIES:
            _INFER_CACHE.popitem(last=False)
    return payload


def _estimate_ttp_min(
    depth_peak: float,
    threshold_m: float,
    r_early: float,
    r_mid: float,
    duration_min: float,
) -> float:
    """Interpolate 12-frame storm buildup curve to estimate minutes to critical depth."""
    if depth_peak <= 1e-4:
        return round(duration_min, 1)
    target_ratio = min(0.90, max(0.35, threshold_m / depth_peak))
    t_early = max(5.0, duration_min * 0.25)
    t_mid = max(t_early + 2.0, duration_min * 0.50)

    if r_early >= target_ratio:
        frac = target_ratio / max(r_early, 1e-4)
        ttp = max(4.0, t_early * frac)
    elif r_mid >= target_ratio:
        frac = (target_ratio - r_early) / max(r_mid - r_early, 1e-4)
        ttp = t_early + frac * (t_mid - t_early)
    else:
        frac = (target_ratio - r_mid) / max(1.0 - r_mid, 1e-4)
        ttp = t_mid + frac * max(1.0, duration_min - t_mid)
    return round(float(max(4.0, min(duration_min, ttp))), 1)


def _node_record(
    c: CatchmentData,
    i: int,
    depth_m: float,
    score: float,
    band: str,
    priority: str,
    rain_mmhr: float,
    ttp_min: float,
) -> dict:
    swmm_d = c.interpolate_swmm(i, rain_mmhr)
    delta_cm = round((depth_m - swmm_d) * 100.0, 1)
    if abs(depth_m - swmm_d) < 0.15:
        status = "MATCH"
    elif depth_m > swmm_d:
        status = "OVER"
    else:
        status = "UNDER"
    return {
        "id": c.node_ids[i],
        "catchment": c.key,
        "position": [round(float(c.lng[i]), 6), round(float(c.lat[i]), 6)],
        "depth_m": round(depth_m, 4),
        "depth": round(depth_m, 4),
        "band": band,
        "priority": priority,
        "score": float(score),
        "name": c.junction_names[i],
        "assets": list(c.node_assets[i]),
        "primary_asset": c.primary_asset[i],
        "elevation": round(float(c.elevation[i]), 2),
        "sink": round(float(c.dep_depth[i]), 3),
        "sink_ratio": round(float(c.sink_ratio[i]), 3),
        "network": round(float(c.betweenness[i]), 4),
        "is_basement": bool(c.is_basement[i]),
        "swmm_depth_m": round(swmm_d, 4),
        "swmmDeltaCm": delta_cm,
        "status": status,
        "ttp_min": ttp_min,
    }


def _dedup_clusters(
    c: CatchmentData,
    eligible_idx: List[int],
    scores: np.ndarray,
    depths: np.ndarray,
    radius_m: float = CLUSTER_RADIUS_M,
) -> List[List[int]]:
    """Peak-first bounded-radius NMS clustering within `radius_m` in UTM (no transitive chaining)."""
    m = len(eligible_idx)
    if m == 0:
        return []
    if m == 1:
        return [list(eligible_idx)]

    ordered = sorted(
        eligible_idx,
        key=lambda idx: (-float(scores[idx]), -float(depths[idx]), c.node_ids[idx]),
    )
    pts = [c.utm_points[i] for i in ordered]
    tree = STRtree(pts)
    pairs_a, pairs_b = tree.query(pts, predicate="dwithin", distance=radius_m)

    nbrs: List[List[int]] = [[] for _ in range(m)]
    for a, b in zip(pairs_a.tolist(), pairs_b.tolist()):
        nbrs[a].append(b)

    claimed = np.zeros(m, dtype=bool)
    clusters: List[List[int]] = []
    for local_i in range(m):
        if claimed[local_i]:
            continue
        grp: List[int] = []
        for local_j in nbrs[local_i]:
            if not claimed[local_j]:
                claimed[local_j] = True
                grp.append(ordered[local_j])
        if not grp:
            claimed[local_i] = True
            grp = [ordered[local_i]]
        else:
            grp.sort(
                key=lambda idx: (-float(scores[idx]), -float(depths[idx]), c.node_ids[idx])
            )
        clusters.append(grp)

    return clusters


def triage_catchment(
    reg: CommandRegistry,
    c: CatchmentData,
    rain_mmhr: float,
    duration_min: float,
    mode: str = "normal",
    depths_override: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Compute Consequence Scores, dedup alerts, sparse nodes, and blocked road metrics."""
    if mode not in THRESHOLDS:
        mode = "normal"
    th = THRESHOLDS[mode]

    if depths_override is None:
        inf = infer_catchment(reg, c, rain_mmhr, duration_min)
        depths = inf["depths"]
        r_early = inf["r_early"]
        r_mid = inf["r_mid"]
        dur = inf["dur"]
        rain = inf["rain"]
        latency_ms = inf["latency_ms"]
    else:
        depths = np.asarray(depths_override, dtype=np.float32)
        r_early = np.full(len(depths), 0.45, dtype=np.float32)
        r_mid = np.full(len(depths), 0.85, dtype=np.float32)
        dur = float(duration_min)
        rain = float(rain_mmhr)
        latency_ms = 0.0

    asset_w = np.array(
        [ASSET_WEIGHT.get(a, ASSET_WEIGHT["street"]) for a in c.primary_asset],
        dtype=np.float64,
    )
    scores = compute_scores_vectorized(depths, asset_w, c.sink_ratio, c.betweenness)

    above_floor = depths >= th["alert_floor"]
    raw_above_floor = int(np.sum(above_floor))

    eligible_idx: List[int] = []
    node_bands: Dict[int, str] = {}
    node_priorities: Dict[int, str] = {}
    sparse_nodes: List[dict] = []

    for i in np.flatnonzero(depths >= 0.02).tolist():
        d_i = float(depths[i])
        sc_i = float(scores[i])
        band_i = classify_band(d_i, mode)
        prio_i = classify_priority(sc_i, band_i)
        node_bands[i] = band_i
        node_priorities[i] = prio_i
        ttp_i = _estimate_ttp_min(d_i, th["barrier"], float(r_early[i]), float(r_mid[i]), dur)
        sparse_nodes.append(_node_record(c, i, d_i, sc_i, band_i, prio_i, rain, ttp_i))
        if d_i >= th["alert_floor"] and prio_i != "suppressed":
            eligible_idx.append(i)

    clusters = _dedup_clusters(c, eligible_idx, scores, depths, CLUSTER_RADIUS_M)
    alerts: List[dict] = []
    for grp in clusters:
        rep = grp[0]
        d_rep = float(depths[rep])
        sc_rep = float(scores[rep])
        band_rep = node_bands[rep]
        prio_rep = node_priorities[rep]

        # Merge asset tags and identify underpass POI & landmark name if cluster overlaps one
        merged_assets_set = set()
        underpass_poi_id = None
        best_poi_name = None
        best_poi_weight = -1.0
        for idx in grp:
            merged_assets_set.update(c.node_assets[idx])
            nid_here = c.node_ids[idx]
            if underpass_poi_id is None and nid_here in c.underpass_poi_by_node:
                underpass_poi_id = c.underpass_poi_by_node[nid_here]
            if nid_here in c.poi_names_by_node:
                pw = ASSET_WEIGHT.get(c.primary_asset[idx], 0.25)
                if pw > best_poi_weight:
                    best_poi_weight = pw
                    best_poi_name = c.poi_names_by_node[nid_here]
        merged_assets = sorted(
            merged_assets_set, key=lambda a: (-ASSET_WEIGHT.get(a, 0.25), a)
        )
        primary_rep = c.primary_asset[rep]
        if primary_rep == "street" and merged_assets:
            primary_rep = merged_assets[0]
        if len(grp) > 1:
            dx = c.x_utm[grp] - c.x_utm[rep]
            dy = c.y_utm[grp] - c.y_utm[rep]
            extent_m = round(float(np.max(np.hypot(dx, dy))) * 2.0, 1)
        else:
            extent_m = 0.0

        action_code, action_label, unit_class = classify_action(
            band_rep, primary_rep, merged_assets
        )
        ttp_thresh = th["pump"] if band_rep == "pump" else th["barrier"]
        ttp_rep = _estimate_ttp_min(
            d_rep, ttp_thresh, float(r_early[rep]), float(r_mid[rep]), dur
        )
        rec = _node_record(c, rep, d_rep, sc_rep, band_rep, prio_rep, rain, ttp_rep)
        if best_poi_name and c.node_ids[rep] not in c.poi_names_by_node:
            rec["name"] = best_poi_name
        rec["primary_asset"] = primary_rep
        rec.update(
            {
                "alert_id": f"ALT-{c.key.upper()}-{c.node_ids[rep]}",
                "assets": merged_assets,
                "affected_nodes": len(grp),
                "cluster_node_ids": [c.node_ids[j] for j in grp],
                "extent_m": extent_m,
                "action": action_code,
                "action_label": action_label,
                "unit_class": unit_class,
                "underpass_poi_id": underpass_poi_id,
                "ttp_source": "playback",
                "mode": mode,
            }
        )
        alerts.append(rec)

    alerts.sort(key=lambda a: (-a["score"], -a["depth_m"], a["id"]))

    # Edge flood depths & blocked road km
    u_idx, v_idx, lengths, eids = _get_edge_arrays(c)
    ed_arr = np.maximum(depths[u_idx], depths[v_idx])
    wet_indices = np.flatnonzero(ed_arr >= 0.02)
    wet_vals = np.round(ed_arr[wet_indices].astype(np.float64), 3)
    edge_depths = {eids[int(i)]: float(v) for i, v in zip(wet_indices, wet_vals)}
    blocked_m = float(lengths[ed_arr >= 0.25].sum())

    suppressed = max(0, raw_above_floor - len(eligible_idx))
    critical_nodes = int(np.sum(depths >= th["pump"]))

    return {
        "catchment": c.key,
        "depths": depths,
        "scores": scores,
        "alerts": alerts,
        "nodes": sparse_nodes,
        "edge_depths": edge_depths,
        "latency_ms": latency_ms,
        "raw_above_floor": raw_above_floor,
        "raw_eligible": len(eligible_idx),
        "dedup_alerts": len(alerts),
        "suppressed": suppressed,
        "critical_nodes": critical_nodes,
        "blocked_km": round(blocked_m / 1000.0, 2),
        "total_edges": len(c.edges),
    }


def triage_scenario(
    reg: CommandRegistry,
    region: str = "all",
    rain_mmhr: float = 45.0,
    duration_min: float = 60.0,
    mode: str = "normal",
) -> Dict[str, Any]:
    """Run triage across one catchment or all 5, merging alerts by `(score, depth)` desc."""
    keys = (
        [region]
        if region != "all" and region in reg.catchments
        else list(reg.catchments.keys())
    )
    t0 = time.perf_counter()

    all_alerts: List[dict] = []
    all_nodes: List[dict] = []
    edge_depths: Dict[str, float] = {}
    depths_by_catchment: Dict[str, np.ndarray] = {}
    total_latency_ms = 0.0
    raw_above_floor = 0
    raw_eligible = 0
    suppressed = 0
    critical_nodes = 0
    blocked_km = 0.0
    total_edges = 0

    for k in keys:
        res = triage_catchment(reg, reg.catchments[k], rain_mmhr, duration_min, mode)
        depths_by_catchment[k] = res["depths"]
        all_alerts.extend(res["alerts"])
        all_nodes.extend(res["nodes"])
        edge_depths.update(res["edge_depths"])
        total_latency_ms += res["latency_ms"]
        raw_above_floor += res["raw_above_floor"]
        raw_eligible += res["raw_eligible"]
        suppressed += res["suppressed"]
        critical_nodes += res["critical_nodes"]
        blocked_km += res["blocked_km"]
        total_edges += res["total_edges"]

    # Focus operator queue on top high-consequence actionable directives (balanced across catchments)
    # instead of flooding the UI with 150+ minor street cards; raw stats remain exact.
    all_alerts.sort(key=lambda a: (-a["score"], -a["depth_m"], a["id"]))
    total_clusters = len(all_alerts)
    max_queue = 30
    if len(all_alerts) > max_queue:
        if len(keys) > 1:
            selected: List[dict] = []
            picked_ids = set()
            # Ensure top critical directives from each flooded catchment appear first
            for k in keys:
                k_top = [a for a in all_alerts if a["catchment"] == k][:4]
                for a in k_top:
                    selected.append(a)
                    picked_ids.add(a["alert_id"])
            for a in all_alerts:
                if len(selected) >= max_queue:
                    break
                if a["alert_id"] not in picked_ids:
                    selected.append(a)
                    picked_ids.add(a["alert_id"])
            selected.sort(key=lambda a: (-a["score"], -a["depth_m"], a["id"]))
            all_alerts = selected
        else:
            all_alerts = all_alerts[:max_queue]

    wall_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return {
        "region": region,
        "catchments": keys,
        "rain_mmhr": round(float(rain_mmhr), 1),
        "duration_min": round(float(duration_min), 1),
        "mode": mode if mode in THRESHOLDS else "normal",
        "alerts": all_alerts,
        "nodes": all_nodes,
        "edge_depths": edge_depths,
        "depths_by_catchment": depths_by_catchment,
        "stats": {
            "inference_latency_ms": round(total_latency_ms, 2),
            "triage_wall_ms": wall_ms,
            "raw_above_floor": raw_above_floor,
            "raw_eligible": raw_eligible,
            "dedup_alerts": len(all_alerts),
            "total_clusters": total_clusters,
            "suppressed": suppressed,
            "critical_nodes": critical_nodes,
            "blocked_km": round(blocked_km, 2),
            "total_edges": total_edges,
        },
    }


def inspect_single_node(
    reg: CommandRegistry,
    node_id: str,
    rain_mmhr: float = 45.0,
    duration_min: float = 60.0,
    mode: str = "normal",
) -> Optional[dict]:
    """Return full inspector details for any node_id, even when dry (< 0.02 m)."""
    found = reg.find_node(node_id)
    if found is None:
        return None
    c, i = found
    inf = infer_catchment(reg, c, rain_mmhr, duration_min)
    d_i = float(inf["depths"][i])
    sc_i = compute_node_score(
        d_i, c.primary_asset[i], float(c.sink_ratio[i]), float(c.betweenness[i])
    )
    band_i = classify_band(d_i, mode)
    prio_i = classify_priority(sc_i, band_i)
    th = THRESHOLDS.get(mode, THRESHOLDS["normal"])
    ttp_i = _estimate_ttp_min(
        d_i, th["barrier"], float(inf["r_early"][i]), float(inf["r_mid"][i]), inf["dur"]
    )
    return _node_record(c, i, d_i, sc_i, band_i, prio_i, inf["rain"], ttp_i)
