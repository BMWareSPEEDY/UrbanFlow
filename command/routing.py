"""Dynamic flood-aware emergency vehicle routing & corridor comparison engine.

Builds cached flood-weighted directed road graphs per `(catchment, scenario,
vehicle, closed_barriers)` and computes both the Flood-Naive GPS path (red) and
the HydroGINE Flood-Safe detour (green), including explicit 20-minute
inter-catchment transfer penalties when catchments are disconnected.
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np

from command.config import (
    INTER_CATCHMENT_PENALTY_MIN,
    INTER_CATCHMENT_SPEED_MPS,
    VEHICLE_PROFILES,
)
from command.loader import CatchmentData, CommandRegistry, EdgeRecord

_GRAPH_LOCK = threading.Lock()
_GRAPH_CACHE: "OrderedDict[Tuple[Any, ...], nx.DiGraph]" = OrderedDict()
_STD_PATH_CACHE: "OrderedDict[Tuple[str, str, str, str], Optional[Tuple[str, ...]]]" = OrderedDict()
_OSRM_CACHE: "OrderedDict[Tuple[float, float, float, float], Tuple[List[List[float]], float, Optional[float]]]" = OrderedDict()
_MAX_GRAPH_CACHE = 48
_MAX_STD_PATH_CACHE = 512
_MAX_OSRM_CACHE = 256
_OSRM_NEGATIVE_TTL_S = 120.0


def _osrm_road_route(
    o_lng: float, o_lat: float, d_lng: float, d_lat: float
) -> Tuple[List[List[float]], float]:
    """Fetch real Bengaluru street geometry & road distance (m) via OSRM, cached."""
    key = (round(o_lng, 4), round(o_lat, 4), round(d_lng, 4), round(d_lat, 4))
    now = time.monotonic()
    with _GRAPH_LOCK:
        hit = _OSRM_CACHE.get(key)
        if hit is not None:
            coords_cached, dist_cached, expires_at = hit
            if expires_at is None or now < expires_at:
                _OSRM_CACHE.move_to_end(key)
                return [list(pt) for pt in coords_cached], float(dist_cached)
            _OSRM_CACHE.pop(key, None)
    fallback_coords = [[round(o_lng, 6), round(o_lat, 6)], [round(d_lng, 6), round(d_lat, 6)]]
    fallback_m = haversine_m(o_lat, o_lng, d_lat, d_lng)
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{o_lng:.6f},{o_lat:.6f};{d_lng:.6f},{d_lat:.6f}"
        f"?overview=full&geometries=geojson"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UrbanFLOW/1.0"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        routes = payload.get("routes") or []
        coords = routes[0]["geometry"]["coordinates"] if routes else None
        dist_m = float(routes[0].get("distance") or fallback_m) if routes else fallback_m
        if isinstance(coords, list) and len(coords) >= 2:
            cleaned = [[round(float(c[0]), 6), round(float(c[1]), 6)] for c in coords]
            with _GRAPH_LOCK:
                _OSRM_CACHE[key] = (cleaned, dist_m, None)
                _OSRM_CACHE.move_to_end(key)
                while len(_OSRM_CACHE) > _MAX_OSRM_CACHE:
                    _OSRM_CACHE.popitem(last=False)
            return [list(pt) for pt in cleaned], dist_m
    except Exception:
        pass
    with _GRAPH_LOCK:
        _OSRM_CACHE[key] = (fallback_coords, fallback_m, time.monotonic() + _OSRM_NEGATIVE_TTL_S)
        _OSRM_CACHE.move_to_end(key)
        while len(_OSRM_CACHE) > _MAX_OSRM_CACHE:
            _OSRM_CACHE.popitem(last=False)
    return fallback_coords, fallback_m


def _osrm_road_geometry(
    o_lng: float, o_lat: float, d_lng: float, d_lat: float
) -> List[List[float]]:
    coords, _ = _osrm_road_route(o_lng, o_lat, d_lng, d_lat)
    return coords

_EARTH_R_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two WGS84 coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi * 0.5) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb * 0.5) ** 2
    )
    return 2.0 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def passability_factor(
    depth_m: float, vehicle: str = "pump_truck", safety_margin_m: float = 0.0
) -> float:
    """Return travel-time multiplier for water depth, or `inf` if impassable."""
    prof = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["pump_truck"])
    d_safe = max(0.02, prof["d_safe"] - safety_margin_m)
    d_impass = max(d_safe + 0.05, prof["d_impass"] - safety_margin_m)
    if depth_m >= d_impass:
        return math.inf
    if depth_m <= d_safe:
        return 1.0
    ratio = (depth_m - d_safe) / max(1e-6, d_impass - d_safe)
    return 1.0 + 18.0 * (ratio * ratio)


def build_weighted_digraph(
    c: CatchmentData,
    depths: Optional[np.ndarray],
    vehicle: str = "pump_truck",
    flood_aware: bool = True,
    closed_barriers: FrozenSet[str] = frozenset(),
    scenario_key: str = "static",
    safety_margin_m: float = 0.0,
) -> nx.DiGraph:
    """Build or fetch cached simplified DiGraph with minimum parallel edge weights."""
    prof = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["pump_truck"])
    speed_mult = prof["speed_mult"]
    bar_key = tuple(sorted(closed_barriers)) if (flood_aware and closed_barriers) else ()
    margin_key = round(safety_margin_m, 3) if flood_aware else 0.0
    cache_key = (c.key, vehicle, flood_aware, scenario_key if flood_aware else "std", bar_key, margin_key)

    with _GRAPH_LOCK:
        hit = _GRAPH_CACHE.get(cache_key)
        if hit is not None:
            _GRAPH_CACHE.move_to_end(cache_key)
            return hit

    dg = nx.DiGraph()
    dg.add_nodes_from(c.node_ids)

    for e in c.edges:
        ed = float(max(depths[e.u_idx], depths[e.v_idx])) if depths is not None else 0.0
        base_sec = e.t0_sec / speed_mult
        if flood_aware:
            if e.u in closed_barriers or e.v in closed_barriers:
                continue
            mult = passability_factor(ed, vehicle, safety_margin_m=safety_margin_m)
            if not math.isfinite(mult):
                continue
            w = base_sec * mult
        else:
            w = base_sec

        existing = dg.get_edge_data(e.u, e.v)
        if existing is None or w < existing["weight"]:
            dg.add_edge(
                e.u,
                e.v,
                weight=w,
                base_sec=base_sec,
                length_m=e.length_m,
                depth_m=round(ed, 3),
                edge_rec=e,
            )

    with _GRAPH_LOCK:
        _GRAPH_CACHE[cache_key] = dg
        _GRAPH_CACHE.move_to_end(cache_key)
        while len(_GRAPH_CACHE) > _MAX_GRAPH_CACHE:
            _GRAPH_CACHE.popitem(last=False)
    return dg


def _extract_path_geometry(
    dg: nx.DiGraph,
    path_nodes: Sequence[str],
    depths: Optional[np.ndarray],
    c: CatchmentData,
    vehicle: str,
) -> dict:
    """Assemble GeoJSON coords, ETA, distance, and flooded segment highlights along path."""
    prof = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["pump_truck"])
    d_impass = prof["d_impass"]
    coords: List[List[float]] = []
    flooded_segments: List[List[List[float]]] = []
    total_sec = 0.0
    total_m = 0.0
    max_depth = 0.0
    flooded_crossings = 0

    for u, v in zip(path_nodes, path_nodes[1:]):
        data = dg.get_edge_data(u, v)
        if data is None:
            continue
        rec: EdgeRecord = data["edge_rec"]
        total_sec += float(data["weight"])
        total_m += float(rec.length_m)
        ed = (
            float(max(depths[rec.u_idx], depths[rec.v_idx]))
            if depths is not None
            else float(data.get("depth_m", 0.0))
        )
        max_depth = max(max_depth, ed)
        if ed >= d_impass:
            flooded_crossings += 1
            flooded_segments.append(rec.coords)
        if not coords:
            coords.extend(rec.coords)
        else:
            coords.extend(rec.coords[1:])

    if not coords and path_nodes:
        i0 = c.node_idx[path_nodes[0]]
        pt = [round(float(c.lng[i0]), 6), round(float(c.lat[i0]), 6)]
        coords = [pt, pt]

    return {
        "reachable": True,
        "path_nodes": list(path_nodes),
        "coords": coords,
        "flooded_segments": flooded_segments,
        "eta_min": round(total_sec / 60.0, 2),
        "distance_m": round(total_m, 1),
        "flooded_crossings": flooded_crossings,
        "max_depth_m": round(max_depth, 3),
    }


def _dijkstra_path(dg: nx.DiGraph, origin: str, dest: str) -> Optional[List[str]]:
    if origin not in dg or dest not in dg:
        return None
    if origin == dest:
        return [origin]
    try:
        _, path = nx.bidirectional_dijkstra(dg, origin, dest, weight="weight")
        return path
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def _unreachable_leg() -> dict:
    return {
        "reachable": False,
        "path_nodes": [],
        "coords": [],
        "flooded_segments": [],
        "eta_min": None,
        "distance_m": None,
        "flooded_crossings": 0,
        "max_depth_m": 0.0,
    }


def _nearest_reachable_ingress(
    dg: nx.DiGraph,
    c_dest: CatchmentData,
    dest_node: str,
    from_lat: float,
    from_lng: float,
) -> Optional[Tuple[str, List[str]]]:
    """Find reachable node in `c_dest` closest to `from_(lat,lng)` that reaches `dest_node`."""
    try:
        rev = dg.reverse(copy=False)
        dists, paths = nx.single_source_dijkstra(rev, dest_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    best_nid = None
    best_sec = float("inf")
    # Minimize total door-to-door time (external bridge + local path to dest_node)
    for nid, local_sec in dists.items():
        if nid == dest_node:
            continue
        idx = c_dest.node_idx[nid]
        d_m = haversine_m(from_lat, from_lng, float(c_dest.lat[idx]), float(c_dest.lng[idx]))
        total_sec = (d_m / INTER_CATCHMENT_SPEED_MPS) + float(local_sec)
        if total_sec < best_sec:
            best_sec = total_sec
            best_nid = nid

    if best_nid is None:
        return None
    forward_nodes = list(reversed(paths[best_nid]))
    return best_nid, forward_nodes


def _perimeter_candidates(
    c_dest: CatchmentData,
    di: int,
    depths: Optional[np.ndarray],
    d_impass: float,
    radius_m: float = 250.0,
) -> List[Tuple[float, str]]:
    """Return non-flooded junction IDs within `radius_m` of `dest_node`, sorted nearest-first."""
    dest_pt = c_dest.utm_points[di]
    near_idxs = c_dest.strtree.query(dest_pt.buffer(radius_m))
    cands: List[Tuple[float, str]] = []
    for idx in near_idxs:
        i = int(idx)
        if i == di:
            continue
        if depths is not None and float(depths[i]) >= d_impass:
            continue
        cands.append((float(c_dest.utm_points[i].distance(dest_pt)), c_dest.node_ids[i]))
    cands.sort(key=lambda t: t[0])
    return cands[:8]


def _append_staging_hop(leg: dict, c_dest: CatchmentData, di: int, snap_m: float) -> None:
    """Append final perimeter staging hop to flooded target junction (+1.0 min hose lay)."""
    dest_ll = [round(float(c_dest.lng[di]), 6), round(float(c_dest.lat[di]), 6)]
    if leg["coords"]:
        leg["coords"].append(dest_ll)
    leg["eta_min"] = round(float(leg["eta_min"] or 0.0) + 1.0, 2)
    leg["distance_m"] = round(float(leg["distance_m"] or 0.0) + snap_m, 1)


def route_nodes(
    reg: CommandRegistry,
    origin_node: str,
    dest_node: str,
    depths_by_catchment: Dict[str, np.ndarray],
    vehicle: str = "pump_truck",
    closed_barriers: FrozenSet[str] = frozenset(),
    scenario_key: str = "default",
    allow_terminal_staging: bool = False,
    safety_margin_m: float = 0.0,
    use_osrm: bool = False,
) -> dict:
    """Compute Flood-Naive vs Flood-Safe routes between two graph nodes."""
    if vehicle not in VEHICLE_PROFILES:
        vehicle = "pump_truck"

    o_found = reg.find_node(origin_node)
    d_found = reg.find_node(dest_node)
    if o_found is None or d_found is None:
        return {
            "reachable": False,
            "reason": "unknown_node",
            "vehicle": vehicle,
            "origin_node": origin_node,
            "dest_node": dest_node,
            "inter_catchment": False,
            "penalty_min": 0.0,
            "stub_coords": None,
            "standard": _unreachable_leg(),
            "safe": _unreachable_leg(),
            "added_vs_standard_min": None,
        }

    c_orig, oi = o_found
    c_dest, di = d_found

    if c_orig.key == c_dest.key:
        depths = depths_by_catchment.get(c_dest.key)
        dg_std = build_weighted_digraph(
            c_dest, depths, vehicle=vehicle, flood_aware=False, scenario_key="std"
        )
        std_key = (c_dest.key, vehicle, origin_node, dest_node)
        with _GRAPH_LOCK:
            in_std = std_key in _STD_PATH_CACHE
            std_hit = _STD_PATH_CACHE.get(std_key)
        if in_std:
            std_nodes = list(std_hit) if std_hit is not None else None
        else:
            std_nodes = _dijkstra_path(dg_std, origin_node, dest_node)
            with _GRAPH_LOCK:
                _STD_PATH_CACHE[std_key] = tuple(std_nodes) if std_nodes is not None else None
                while len(_STD_PATH_CACHE) > _MAX_STD_PATH_CACHE:
                    _STD_PATH_CACHE.popitem(last=False)

        prof = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["pump_truck"])
        if not closed_barriers and (depths is None or float(depths.max()) <= max(0.02, prof["d_safe"] - safety_margin_m)):
            safe_nodes = std_nodes
            dg_safe = dg_std
        else:
            dg_safe = build_weighted_digraph(
                c_dest,
                depths,
                vehicle=vehicle,
                flood_aware=True,
                closed_barriers=closed_barriers,
                scenario_key=scenario_key,
                safety_margin_m=safety_margin_m,
            )
            safe_nodes = _dijkstra_path(dg_safe, origin_node, dest_node)

        staged_dist_m = 0.0
        if safe_nodes is None and allow_terminal_staging:
            for dist_m, stage_nid in _perimeter_candidates(c_dest, di, depths, prof["d_impass"]):
                cand_path = _dijkstra_path(dg_safe, origin_node, stage_nid)
                if cand_path is not None:
                    safe_nodes = cand_path
                    staged_dist_m = dist_m
                    break

        std_leg = (
            _extract_path_geometry(dg_std, std_nodes, depths, c_dest, vehicle)
            if std_nodes
            else _unreachable_leg()
        )
        safe_leg = (
            _extract_path_geometry(dg_safe, safe_nodes, depths, c_dest, vehicle)
            if safe_nodes
            else _unreachable_leg()
        )
        if safe_leg["reachable"] and staged_dist_m > 0.0:
            _append_staging_hop(safe_leg, c_dest, di, staged_dist_m)
        reachable = bool(safe_leg["reachable"])
        added = (
            round(safe_leg["eta_min"] - std_leg["eta_min"], 2)
            if reachable and std_leg["reachable"]
            else None
        )
        return {
            "reachable": reachable,
            "reason": None if reachable else "flood_blocked",
            "vehicle": vehicle,
            "origin_node": origin_node,
            "dest_node": dest_node,
            "origin_catchment": c_orig.key,
            "dest_catchment": c_dest.key,
            "inter_catchment": False,
            "penalty_min": 0.0,
            "stub_coords": None,
            "standard": std_leg,
            "safe": safe_leg,
            "added_vs_standard_min": added,
        }

    # Cross-catchment dispatch: explicit arterial highway stub + penalty + local safe leg
    depths_d = depths_by_catchment.get(c_dest.key)
    dg_std_d = build_weighted_digraph(
        c_dest, depths_d, vehicle=vehicle, flood_aware=False, scenario_key="std"
    )
    dg_safe_d = build_weighted_digraph(
        c_dest,
        depths_d,
        vehicle=vehicle,
        flood_aware=True,
        closed_barriers=closed_barriers,
        scenario_key=scenario_key,
    )

    o_lat, o_lng = float(c_orig.lat[oi]), float(c_orig.lng[oi])

    safe_ing = _nearest_reachable_ingress(dg_safe_d, c_dest, dest_node, o_lat, o_lng)
    staged_x_m = 0.0
    if safe_ing is None and allow_terminal_staging:
        prof_d = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["pump_truck"])
        for dist_m, stage_nid in _perimeter_candidates(c_dest, di, depths_d, prof_d["d_impass"]):
            cand = _nearest_reachable_ingress(dg_safe_d, c_dest, stage_nid, o_lat, o_lng)
            if cand is not None:
                safe_ing = cand
                staged_x_m = dist_m
                break
    std_ing = _nearest_reachable_ingress(dg_std_d, c_dest, dest_node, o_lat, o_lng)

    if std_ing:
        std_ing_id, std_path = std_ing
        std_ing_idx = c_dest.node_idx[std_ing_id]
        std_ing_lat, std_ing_lng = float(c_dest.lat[std_ing_idx]), float(c_dest.lng[std_ing_idx])
        std_leg = _extract_path_geometry(dg_std_d, std_path, depths_d, c_dest, vehicle)
        if use_osrm:
            std_road, std_bridge_m = _osrm_road_route(o_lng, o_lat, std_ing_lng, std_ing_lat)
            std_leg["coords"] = std_road + std_leg["coords"][1:] if std_leg["coords"] else std_road
        else:
            std_bridge_m = haversine_m(o_lat, o_lng, std_ing_lat, std_ing_lng)
            o_pt = [round(o_lng, 6), round(o_lat, 6)]
            if not std_leg["coords"]:
                std_leg["coords"] = [o_pt, [round(std_ing_lng, 6), round(std_ing_lat, 6)]]
            elif std_leg["coords"][0] != o_pt:
                std_leg["coords"] = [o_pt] + std_leg["coords"]
        std_transfer_min = (std_bridge_m / INTER_CATCHMENT_SPEED_MPS) / 60.0 + INTER_CATCHMENT_PENALTY_MIN
        std_leg["eta_min"] = round(std_leg["eta_min"] + std_transfer_min, 2)
        std_leg["distance_m"] = round(std_leg["distance_m"] + std_bridge_m, 1)
    else:
        std_leg = _unreachable_leg()

    if safe_ing:
        ing_id, safe_path = safe_ing
        ing_idx = c_dest.node_idx[ing_id]
        ing_lat, ing_lng = float(c_dest.lat[ing_idx]), float(c_dest.lng[ing_idx])
        if use_osrm:
            stub, safe_bridge_m = _osrm_road_route(o_lng, o_lat, ing_lng, ing_lat)
        else:
            safe_bridge_m = haversine_m(o_lat, o_lng, ing_lat, ing_lng)
            stub = [
                [round(o_lng, 6), round(o_lat, 6)],
                [round(ing_lng, 6), round(ing_lat, 6)],
            ]
        safe_leg = _extract_path_geometry(dg_safe_d, safe_path, depths_d, c_dest, vehicle)
        if staged_x_m > 0.0:
            _append_staging_hop(safe_leg, c_dest, di, staged_x_m)
        if use_osrm:
            safe_leg["coords"] = stub + safe_leg["coords"][1:] if safe_leg["coords"] else stub
        safe_transfer_min = (safe_bridge_m / INTER_CATCHMENT_SPEED_MPS) / 60.0 + INTER_CATCHMENT_PENALTY_MIN
        safe_leg["eta_min"] = round(safe_leg["eta_min"] + safe_transfer_min, 2)
        safe_leg["distance_m"] = round(safe_leg["distance_m"] + safe_bridge_m, 1)
        reachable = True
        reason = None
    else:
        if use_osrm:
            stub = _osrm_road_geometry(
                o_lng, o_lat, float(c_dest.lng[di]), float(c_dest.lat[di])
            )
        else:
            stub = [
                [round(o_lng, 6), round(o_lat, 6)],
                [round(float(c_dest.lng[di]), 6), round(float(c_dest.lat[di]), 6)],
            ]
        safe_leg = _unreachable_leg()
        reachable = False
        reason = "flood_blocked"

    added = (
        round(safe_leg["eta_min"] - std_leg["eta_min"], 2)
        if reachable and std_leg["reachable"]
        else None
    )
    return {
        "reachable": reachable,
        "reason": reason,
        "vehicle": vehicle,
        "origin_node": origin_node,
        "dest_node": dest_node,
        "origin_catchment": c_orig.key,
        "dest_catchment": c_dest.key,
        "inter_catchment": True,
        "penalty_min": INTER_CATCHMENT_PENALTY_MIN,
        "stub_coords": stub,
        "standard": std_leg,
        "safe": safe_leg,
        "added_vs_standard_min": added,
    }


def resolve_endpoint(
    reg: CommandRegistry,
    spec: Any,
    region_hint: Optional[str] = None,
) -> Optional[Tuple[str, float]]:
    """Resolve `node_id` string or `{lat, lng}` coord object to `(node_id, snap_m)`."""
    if isinstance(spec, str):
        return (spec, 0.0) if reg.find_node(spec) is not None else None
    if isinstance(spec, dict):
        if "node_id" in spec and spec["node_id"]:
            nid = str(spec["node_id"])
            return (nid, 0.0) if reg.find_node(nid) is not None else None
        if "lat" in spec and "lng" in spec:
            snapped = reg.snap_coord(
                float(spec["lng"]), float(spec["lat"]), region_hint=region_hint
            )
            if snapped is not None:
                return snapped[1], snapped[2]
    return None
