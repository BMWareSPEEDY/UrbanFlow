"""Public transit & BMTC bus corridor flood-rerouting evaluator.

Provides the second municipal perspective: tracking key Bengaluru commuter bus
corridors, flagging submerged segments or locked barriers on regular routes,
and computing safe flood-avoiding bus detours using HydroGINE-v5 predictions.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
from typing import Dict, FrozenSet, List, Optional, Tuple

import numpy as np

from command.loader import CommandRegistry
from command.routing import route_nodes

_TRANSIT_LOCK = threading.Lock()
_TRANSIT_CACHE: "OrderedDict[Tuple[object, ...], dict]" = OrderedDict()
_MAX_TRANSIT_CACHE = 128
_CORRIDOR_SNAPS: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

# Representative municipal bus corridors anchored via WGS84 endpoints that snap
# directly to real GraphML junctions / transit POIs inside each catchment.
CORRIDOR_TEMPLATES: List[dict] = [
    {
        "route_id": "BMTC-500D",
        "route_name": "500D · Bellandur ORR Commuter Spine",
        "catchment": "bellandur",
        "origin_label": "Iblur ORR Junction",
        "origin_coord": (12.92066, 77.66520),
        "dest_label": "Devarabeesanahalli Flyover",
        "dest_coord": (12.93015, 77.68532),
    },
    {
        "route_id": "BMTC-500A",
        "route_name": "500A · HSR Agara – Silk Board Shuttle",
        "catchment": "hsr",
        "origin_label": "HSR Transit Hub (Sarjapur Rd)",
        "origin_coord": (12.9130, 77.6510),
        "dest_label": "Silk Board East Approach",
        "dest_coord": (12.9173, 77.6248),
    },
    {
        "route_id": "BMTC-201R",
        "route_name": "201R · Koramangala – Domlur Ring",
        "catchment": "koramangala",
        "origin_label": "Silk Board Junction",
        "origin_coord": (12.9172, 77.6228),
        "dest_label": "Indiranagar / Ejipura Corridor",
        "dest_coord": (12.9460, 77.6400),
    },
    {
        "route_id": "BMTC-335E",
        "route_name": "335E · Whitefield ITPB Express",
        "catchment": "whitefield",
        "origin_label": "Kundalahalli Gate",
        "origin_coord": (12.9612, 77.7295),
        "dest_label": "ITPL Main Gate Hub",
        "dest_coord": (12.98772, 77.73692),
    },
    {
        "route_id": "BMTC-356C",
        "route_name": "356C · Electronic City Hosur Corridor",
        "catchment": "ecity",
        "origin_label": "Konappana Agrahara",
        "origin_coord": (12.8585, 77.6580),
        "dest_label": "Hosur Rd E-City Phase 1",
        "dest_coord": (12.8415, 77.6635),
    },
    {
        "route_id": "BMTC-KIA7A",
        "route_name": "KIA-7A · Koramangala – Bellandur Link",
        "catchment": "all",
        "origin_label": "Koramangala Sony World",
        "origin_coord": (12.9365, 77.6275),
        "dest_label": "Bellandur Gate Hub",
        "dest_coord": (12.92783, 77.67653),
    },
]


def _pick_snap_in_scc(
    reg: CommandRegistry,
    lat: float,
    lng: float,
    hint: Optional[str],
) -> Optional[str]:
    snapped = reg.snap_coord(lng, lat, region_hint=hint, max_dist_m=2000.0)
    if snapped is None:
        return None
    r_key, nid, _ = snapped
    c = reg.catchments[r_key]
    if nid in c.scc_nodes:
        return nid
    # Fall back to closest SCC node in that catchment
    ux, uy = c.x_utm[c.node_idx[nid]], c.y_utm[c.node_idx[nid]]
    best_nid = nid
    best_d2 = float("inf")
    for cand in c.scc_nodes:
        idx = c.node_idx[cand]
        d2 = (float(c.x_utm[idx]) - float(ux)) ** 2 + (float(c.y_utm[idx]) - float(uy)) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_nid = cand
    return best_nid


def evaluate_transit_corridors(
    reg: CommandRegistry,
    depths_by_catchment: Dict[str, np.ndarray],
    closed_barriers: FrozenSet[str],
    scenario_key: str,
    region: str = "all",
) -> dict:
    """Evaluate normal vs Flood-Safe BMTC bus corridors under live storm & barriers."""
    depth_sig = tuple(
        (k, round(float(v.sum()), 3)) for k, v in sorted(depths_by_catchment.items())
    )
    cache_key = (region, scenario_key, closed_barriers, depth_sig)
    with _TRANSIT_LOCK:
        hit = _TRANSIT_CACHE.get(cache_key)
        if hit is not None:
            _TRANSIT_CACHE.move_to_end(cache_key)
            return hit

    corridors_out: List[dict] = []
    counts = {"normal": 0, "diverted": 0, "suspended": 0}

    for tmpl in CORRIDOR_TEMPLATES:
        if region != "all" and tmpl["catchment"] not in (region, "all"):
            continue
        rid = tmpl["route_id"]
        snapped = _CORRIDOR_SNAPS.get(rid)
        if snapped is None:
            o_hint = None if tmpl["catchment"] == "all" else tmpl["catchment"]
            snapped = (
                _pick_snap_in_scc(reg, *tmpl["origin_coord"], hint=o_hint),
                _pick_snap_in_scc(reg, *tmpl["dest_coord"], hint=o_hint),
            )
            _CORRIDOR_SNAPS[rid] = snapped
        orig_node, dest_node = snapped
        if not orig_node or not dest_node or orig_node == dest_node:
            continue

        route = route_nodes(
            reg,
            orig_node,
            dest_node,
            depths_by_catchment,
            vehicle="bus",
            closed_barriers=closed_barriers,
            scenario_key=scenario_key,
            use_osrm=True,
        )
        std = route["standard"]
        safe = route["safe"]
        std_crossings = std.get("flooded_crossings", 0)
        std_nodes = set(std.get("path_nodes") or [])
        barrier_hits = len(std_nodes & closed_barriers)

        # Identify deepest flooded node along naive route to surface bottleneck location
        bottleneck_node = None
        bottleneck_name = None
        bottleneck_depth_m = 0.0
        for nid in std_nodes:
            found_n = reg.find_node(nid)
            if found_n is None:
                continue
            cg_n, idx_n = found_n
            d_arr = depths_by_catchment.get(cg_n.key)
            if d_arr is None:
                continue
            dn = float(d_arr[idx_n])
            if dn > bottleneck_depth_m:
                bottleneck_depth_m = dn
                bottleneck_node = nid
                bottleneck_name = cg_n.junction_names[idx_n]

        if not route["reachable"]:
            status = "SUSPENDED"
            counts["suspended"] += 1
            bn = f" near {bottleneck_name} ({bottleneck_depth_m*100:.0f}cm)" if bottleneck_name else ""
            directive = (
                f"HOLD {tmpl['route_id']} at {tmpl['origin_label']} — "
                f"safe bus detour flood-blocked{bn}; clear corridor or deploy pump"
            )
        elif std_crossings > 0 or barrier_hits > 0:
            status = "DIVERTED"
            counts["diverted"] += 1
            delta = route.get("added_vs_standard_min") or 0.0
            sign = "+" if delta >= 0 else ""
            bn = f" ({bottleneck_name})" if bottleneck_name else ""
            directive = (
                f"DIVERT {tmpl['route_id']} ({sign}{delta:.1f}m) — "
                f"avoids {std_crossings} flooded links{bn}"
                + (f" & {barrier_hits} locked barriers" if barrier_hits else "")
            )
        else:
            status = "NORMAL"
            counts["normal"] += 1
            directive = f"CLEAR {tmpl['route_id']} — standard bus alignment passable ({safe['eta_min']:.1f}m)"

        corridors_out.append(
            {
                "route_id": tmpl["route_id"],
                "route_name": tmpl["route_name"],
                "catchment": tmpl["catchment"],
                "status": status,
                "directive": directive,
                "origin_label": tmpl["origin_label"],
                "dest_label": tmpl["dest_label"],
                "origin_node": orig_node,
                "dest_node": dest_node,
                "bottleneck_node": bottleneck_node,
                "bottleneck_name": bottleneck_name,
                "bottleneck_depth_m": round(bottleneck_depth_m, 3),
                "flooded_crossings": std_crossings,
                "barrier_conflicts": barrier_hits,
                "max_std_depth_m": std.get("max_depth_m", 0.0),
                "standard_eta_min": std.get("eta_min"),
                "safe_eta_min": safe.get("eta_min"),
                "added_vs_standard_min": route.get("added_vs_standard_min"),
                "route": route,
            }
        )

    # Sort suspended & diverted routes to top
    order = {"SUSPENDED": 0, "DIVERTED": 1, "NORMAL": 2}
    corridors_out.sort(key=lambda c: (order[c["status"]], -c["flooded_crossings"], c["route_id"]))

    result = {
        "corridors": corridors_out,
        "summary": counts,
    }
    with _TRANSIT_LOCK:
        _TRANSIT_CACHE[cache_key] = result
        _TRANSIT_CACHE.move_to_end(cache_key)
        while len(_TRANSIT_CACHE) > _MAX_TRANSIT_CACHE:
            _TRANSIT_CACHE.popitem(last=False)
    return result
