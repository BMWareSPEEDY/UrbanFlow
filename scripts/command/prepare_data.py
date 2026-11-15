"""Prepare static Command & Dispatch assets under data/command/.

Generates:
1. data/command/pois.json         — OSM road-name + Nominatim incident + municipal POIs snapped via STRtree
2. data/command/depots.json       — 6 high-elevation, non-basement, SCC-connected depots
3. data/command/betweenness.json  — deterministic percentile-ranked betweenness centrality N in [0, 1]
4. data/command/fleet.json        — default municipal inventory seed (12 pumps, 8 barriers, 6 wardens)
5. data/command/pyg_bengaluru_50.pt — compact 5-catchment PyG Data cache (with elev_range)
6. data/command/eval_swmm_truth.json — genuine EPA SWMM 5.2 node depths for 20/50/80/100/120 mm/hr

Run from repo root:
  .venv/bin/python scripts/command/prepare_data.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Tuple

import networkx as nx
import numpy as np
import osmnx as ox
import torch
from pyproj import Transformer
from shapely.geometry import Point
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from command.config import (
    ASSET_WEIGHT,
    CATCHMENTS,
    COMMAND_DATA_DIR,
    DATA_DIR,
    DATASETS_DIR,
    DEFAULT_FLEET,
    GRAPHS_DIR,
)

TRANSFORMER = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

# Curated municipal POIs inside the five Bengaluru catchment bounding boxes
# (combined with deduplicated OSM graph road-name POIs, major intersections,
# BBMP lakes/rain gauges, and Nominatim-geocoded Oct 2024 flood blackspots).
CURATED_POIS: Dict[str, List[Dict[str, Any]]] = {
    "hsr": [
        {"name": "Agara Junction Underpass", "category": "underpass", "lat": 12.9234, "lng": 77.6388},
        {"name": "Silk Board East Ramp", "category": "underpass", "lat": 12.9173, "lng": 77.6248},
        {"name": "Iblur West Service Underpass", "category": "underpass", "lat": 12.9212, "lng": 77.6520},
        {"name": "Roopena Agrahara Hosur Rd Ramp", "category": "underpass", "lat": 12.9120, "lng": 77.6260},
        {"name": "Greenview Medical Centre HSR", "category": "hospital", "lat": 12.9146, "lng": 77.6378},
        {"name": "Narayana Multispeciality HSR", "category": "hospital", "lat": 12.9102, "lng": 77.6442},
        {"name": "Lotus Multi-Speciality Hospital HSR", "category": "hospital", "lat": 12.9154, "lng": 77.6476},
        {"name": "Phoenix Hospital 27th Main HSR", "category": "hospital", "lat": 12.9078, "lng": 77.6512},
        {"name": "HSR Fire & Emergency Station", "category": "fire_station", "lat": 12.9122, "lng": 77.6395},
        {"name": "BESCOM 66/11kV HSR Substation", "category": "power_substation", "lat": 12.9085, "lng": 77.6495},
        {"name": "HSR BMTC Transit Depot (Sector 1)", "category": "transit_hub", "lat": 12.9130, "lng": 77.6510},
        {"name": "HSR BDA Complex Bus Hub", "category": "transit_hub", "lat": 12.9142, "lng": 77.6372},
        {"name": "Agara BMTC Flyover Stop", "category": "transit_hub", "lat": 12.9231, "lng": 77.6442},
        {"name": "Bommanahalli Silk Rd Bus Hub", "category": "transit_hub", "lat": 12.9089, "lng": 77.6272},
        {"name": "Agara Lake Spillway", "category": "watercourse", "lat": 12.9225, "lng": 77.6410},
        {"name": "NIFT Bengaluru HSR Campus", "category": "school", "lat": 12.9128, "lng": 77.6488},
    ],
    "bellandur": [
        {"name": "Iblur ORR Underpass", "category": "underpass", "lat": 12.92066, "lng": 77.66520},
        {"name": "Ecospace ORR Underpass", "category": "underpass", "lat": 12.92834, "lng": 77.68116},
        {"name": "Devarabeesanahalli Flyover Sump", "category": "underpass", "lat": 12.93015, "lng": 77.68532},
        {"name": "Bellandur Gate ORR Underpass", "category": "underpass", "lat": 12.9268, "lng": 77.6742},
        {"name": "Sakra World Hospital", "category": "hospital", "lat": 12.9288, "lng": 77.6845},
        {"name": "Manipal Hospital Bellandur", "category": "hospital", "lat": 12.9242, "lng": 77.6745},
        {"name": "Cloudnine Hospital Bellandur ORR", "category": "hospital", "lat": 12.9218, "lng": 77.6675},
        {"name": "Doctor Levine Memorial Hospital", "category": "hospital", "lat": 12.9125, "lng": 77.6758},
        {"name": "Bellandur Fire Response Post", "category": "fire_station", "lat": 12.9165, "lng": 77.6780},
        {"name": "BESCOM Bellandur Grid Substation", "category": "power_substation", "lat": 12.9255, "lng": 77.6720},
        {"name": "Bellandur Gate BMTC Transit Hub", "category": "transit_hub", "lat": 12.92783, "lng": 77.67653},
        {"name": "RMZ Ecospace BMTC Hub", "category": "transit_hub", "lat": 12.9268, "lng": 77.6815},
        {"name": "Kasavanahalli Cross Bus Hub", "category": "transit_hub", "lat": 12.9078, "lng": 77.6762},
        {"name": "Haralur Cross BMTC Stop", "category": "transit_hub", "lat": 12.9112, "lng": 77.6635},
        {"name": "Bellandur Lake Rajakaluve Weir", "category": "watercourse", "lat": 12.9338, "lng": 77.6710},
        {"name": "Kaikondrahalli Lake Bund", "category": "watercourse", "lat": 12.9128, "lng": 77.6730},
        {"name": "New Horizon / Bellandur Campus", "category": "school", "lat": 12.9338, "lng": 77.6908},
    ],
    "whitefield": [
        {"name": "Kundalahalli Gate Underpass", "category": "underpass", "lat": 12.9612, "lng": 77.7295},
        {"name": "Hope Farm Junction Underpass", "category": "underpass", "lat": 12.9873, "lng": 77.7538},
        {"name": "Graphite India Signal Sump", "category": "underpass", "lat": 12.9765, "lng": 77.7318},
        {"name": "Varthur Kodi Junction Sump", "category": "underpass", "lat": 12.9570, "lng": 77.7455},
        {"name": "Manipal Hospital Whitefield", "category": "hospital", "lat": 12.9825, "lng": 77.7298},
        {"name": "Vydehi Institute Hospital", "category": "hospital", "lat": 12.9768, "lng": 77.7342},
        {"name": "Sri Sathya Sai Super Speciality Hospital", "category": "hospital", "lat": 12.9788, "lng": 77.7422},
        {"name": "Cloudnine Hospital Whitefield", "category": "hospital", "lat": 12.9685, "lng": 77.7485},
        {"name": "Whitefield Fire Station", "category": "fire_station", "lat": 12.9718, "lng": 77.7505},
        {"name": "BESCOM EPIP 66/11kV Substation", "category": "power_substation", "lat": 12.9760, "lng": 77.7350},
        {"name": "ITPL Pattandur Agrahara Metro Hub", "category": "transit_hub", "lat": 12.98772, "lng": 77.73692},
        {"name": "Hope Farm Channasandra Metro Hub", "category": "transit_hub", "lat": 12.9866, "lng": 77.7548},
        {"name": "Kadugodi / Whitefield BMTC Hub", "category": "transit_hub", "lat": 12.9872, "lng": 77.7598},
        {"name": "Kundalahalli Gate BMTC Stand", "category": "transit_hub", "lat": 12.9598, "lng": 77.7312},
        {"name": "Varthur Kodi Bus Terminus", "category": "transit_hub", "lat": 12.9548, "lng": 77.7458},
        {"name": "Varthur Lake Spillway", "category": "watercourse", "lat": 12.9518, "lng": 77.7418},
        {"name": "Nallurahalli Lake Canal", "category": "watercourse", "lat": 12.9728, "lng": 77.7392},
    ],
    "ecity": [
        {"name": "Hosur Road E-City Underpass", "category": "underpass", "lat": 12.8445, "lng": 77.6605},
        {"name": "Konappana Agrahara Underpass", "category": "underpass", "lat": 12.8585, "lng": 77.6580},
        {"name": "Veerasandra BETL Underpass", "category": "underpass", "lat": 12.8342, "lng": 77.6745},
        {"name": "Hosa Road Junction Sump", "category": "underpass", "lat": 12.8655, "lng": 77.6525},
        {"name": "Kauvery Hospital Electronic City", "category": "hospital", "lat": 12.8415, "lng": 77.6635},
        {"name": "Springleaf Hospital E-City Phase 1", "category": "hospital", "lat": 12.8448, "lng": 77.6538},
        {"name": "Vimalalaya Hospital Kammasandra", "category": "hospital", "lat": 12.8332, "lng": 77.6805},
        {"name": "Ramakrishna Healthcare Neeladri", "category": "hospital", "lat": 12.8432, "lng": 77.6448},
        {"name": "Electronic City Fire Station", "category": "fire_station", "lat": 12.8465, "lng": 77.6710},
        {"name": "BESCOM 220kV E-City Substation", "category": "power_substation", "lat": 12.8380, "lng": 77.6680},
        {"name": "BESCOM Infosys Phase 2 Grid Sub", "category": "power_substation", "lat": 12.8452, "lng": 77.6665},
        {"name": "Electronic City Phase 1 Metro/BMTC Hub", "category": "transit_hub", "lat": 12.84968, "lng": 77.66497},
        {"name": "Konappana Agrahara Metro Station", "category": "transit_hub", "lat": 12.8582, "lng": 77.6592},
        {"name": "Infosys Gate BMTC Hub", "category": "transit_hub", "lat": 12.8498, "lng": 77.6625},
        {"name": "Wipro Gate / Doddathoguru Stand", "category": "transit_hub", "lat": 12.8385, "lng": 77.6588},
        {"name": "Neeladri Nagar Transit Terminus", "category": "transit_hub", "lat": 12.8418, "lng": 77.6440},
        {"name": "Doddathoguru Lake Bund", "category": "watercourse", "lat": 12.8555, "lng": 77.6540},
    ],
    "koramangala": [
        {"name": "Silk Board Junction Underpass", "category": "underpass", "lat": 12.9172, "lng": 77.6228},
        {"name": "Ejipura Inner Ring Underpass", "category": "underpass", "lat": 12.9428, "lng": 77.6265},
        {"name": "Madiwala Underpass (Hosur Rd)", "category": "underpass", "lat": 12.9219, "lng": 77.6177},
        {"name": "Dairy Circle / Adugodi Sump", "category": "underpass", "lat": 12.9362, "lng": 77.6068},
        {"name": "St. John's Medical College Hospital", "category": "hospital", "lat": 12.9295, "lng": 77.6205},
        {"name": "Marvel Hospital Koramangala", "category": "hospital", "lat": 12.9345, "lng": 77.6305},
        {"name": "Apollo Spectra Hospital 5th Block", "category": "hospital", "lat": 12.9342, "lng": 77.6202},
        {"name": "Acura Specialty Hospital 8th Block", "category": "hospital", "lat": 12.9395, "lng": 77.6225},
        {"name": "Koramangala Fire Station", "category": "fire_station", "lat": 12.9390, "lng": 77.6110},
        {"name": "BESCOM 66/11kV Koramangala Sub", "category": "power_substation", "lat": 12.9310, "lng": 77.6285},
        {"name": "Koramangala TTMC / Water Tank Hub", "category": "transit_hub", "lat": 12.9332, "lng": 77.6238},
        {"name": "Sony World Junction BMTC Hub", "category": "transit_hub", "lat": 12.9365, "lng": 77.6275},
        {"name": "Madiwala BMTC Bus Terminus", "category": "transit_hub", "lat": 12.9222, "lng": 77.6195},
        {"name": "Domlur / Inner Ring BMTC Hub", "category": "transit_hub", "lat": 12.9502, "lng": 77.6382},
        {"name": "ST Bed Koramangala Rajakaluve", "category": "watercourse", "lat": 12.9368, "lng": 77.6335},
        {"name": "Madiwala Lake Outlet Channel", "category": "watercourse", "lat": 12.9175, "lng": 77.6125},
    ],
}

# Six depot anchor targets across the 5 catchments (1-2 per catchment; D-15, §2.2).
DEPOT_SEEDS: List[Dict[str, Any]] = [
    {"id": "DEP-HSR-01", "name": "HSR Sector 2 Yard", "region": "hsr", "lat": 12.9125, "lng": 77.6440, "classes": ["pump", "warden"]},
    {"id": "DEP-BLR-01", "name": "Bellandur Lake Yard", "region": "bellandur", "lat": 12.9195, "lng": 77.6790, "classes": ["pump", "warden"]},
    {"id": "DEP-WFD-01", "name": "Whitefield EPIP Yard", "region": "whitefield", "lat": 12.9735, "lng": 77.7450, "classes": ["pump", "warden"]},
    {"id": "DEP-ECT-01", "name": "Electronic City Hub Yard", "region": "ecity", "lat": 12.8470, "lng": 77.6690, "classes": ["pump", "warden"]},
    {"id": "DEP-KRM-01", "name": "Koramangala 4th Block Yard", "region": "koramangala", "lat": 12.9340, "lng": 77.6290, "classes": ["pump", "warden"]},
    {"id": "DEP-KRM-02", "name": "Indiranagar / Domlur Yard", "region": "koramangala", "lat": 12.9485, "lng": 77.6360, "classes": ["pump", "warden"]},
]


def _classify_edge_name(name: str) -> str | None:
    low = name.lower()
    if any(w in low for w in ("underpass", "subway")):
        return "underpass"
    if any(w in low for w in ("hospital", "clinic")):
        return "hospital"
    if "fire" in low:
        return "fire_station"
    if any(w in low for w in ("substation", "bescom")):
        return "power_substation"
    if any(w in low for w in ("metro", "transit", "tech park", "business park")):
        return "transit_hub"
    if any(w in low for w in ("school", "college", "polytechnic")):
        return "school"
    if any(w in low for w in ("lake", "canal")):
        return "watercourse"
    return None


def _snap_point(
    lng: float,
    lat: float,
    tree: STRtree,
    pts: List[Point],
    node_ids: List[str],
    max_dist_m: float,
    allowed_set: set[str] | None = None,
) -> Tuple[str | None, float]:
    ux, uy = TO_UTM.transform(lng, lat)
    q = Point(ux, uy)
    idx = int(tree.nearest(q))
    dist = float(pts[idx].distance(q))
    if dist > max_dist_m:
        return None, dist
    cand = node_ids[idx]
    if allowed_set is not None and cand not in allowed_set:
        # Check nearby nodes within max_dist_m
        idxs = tree.query(q.buffer(max_dist_m))
        best = None
        best_d = float("inf")
        for i in idxs:
            nid = node_ids[int(i)]
            if nid in allowed_set:
                d = float(pts[int(i)].distance(q))
                if d < best_d:
                    best_d = d
                    best = nid
        if best is not None:
            return best, best_d
    return cand, dist


def _extract_intersection_pois(
    G: nx.MultiDiGraph,
    r_key: str,
    seen_node_cat: set,
    existing_utm: List[Tuple[float, float]],
    limit: int = 16,
) -> List[Dict[str, Any]]:
    """Extract clean named major road intersections (`Street A × Street B`) spaced >= 300 m."""
    major_hw = {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
    }
    node_streets: Dict[Any, List[str]] = {}
    node_has_major: Dict[Any, bool] = {}
    for u, v, _, ed in G.edges(keys=True, data=True):
        hw = ed.get("highway", "")
        if isinstance(hw, list):
            hw = hw[0]
        nm = ed.get("name")
        if isinstance(nm, list):
            nm = nm[0]
        nm_str = str(nm).strip() if nm else ""
        if not nm_str:
            continue
        for node in (u, v):
            st_list = node_streets.setdefault(node, [])
            if nm_str not in st_list:
                st_list.append(nm_str)
            if hw in major_hw:
                node_has_major[node] = True

    candidates = []
    for n, streets in node_streets.items():
        if not node_has_major.get(n) or len(streets) < 2:
            continue
        deg = int(G.degree(n))
        ux, uy = float(G.nodes[n]["x"]), float(G.nodes[n]["y"])
        # Pick top 2 distinct road names deterministically
        clean_names = sorted(streets, key=lambda s: (len(s), s))[:2]
        label = f"{clean_names[0]} × {clean_names[1]}"
        candidates.append((deg, str(n), ux, uy, label))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    added: List[Dict[str, Any]] = []
    kept_pts = list(existing_utm)
    for _, nid, ux, uy, label in candidates:
        if len(added) >= limit:
            break
        if (nid, "arterial") in seen_node_cat:
            continue
        if any(math.hypot(ux - px, uy - py) < 300.0 for px, py in kept_pts):
            continue
        seen_node_cat.add((nid, "arterial"))
        kept_pts.append((ux, uy))
        lon, lat = TRANSFORMER.transform(ux, uy)
        added.append(
            {
                "id": "",
                "name": label,
                "category": "arterial",
                "catchment": r_key,
                "node_id": nid,
                "lat": round(lat, 6),
                "lng": round(lon, 6),
                "snap_m": 0.0,
                "source": "osm_graph_intersection",
            }
        )
    return added


def main() -> None:
    pois_only = "--pois-only" in sys.argv
    os.makedirs(COMMAND_DATA_DIR, exist_ok=True)
    t_start = time.time()

    # Load Oct-2024 incidents if present
    incidents_path = os.path.join(DATA_DIR, "real_bengaluru_oct2024_incidents.json")
    incidents: List[dict] = []
    if os.path.exists(incidents_path):
        with open(incidents_path, "r") as f:
            incidents = json.load(f).get("incidents", [])

    pyg_50: Dict[str, Any] = {}
    eval_swmm: Dict[str, Dict[str, List[float]]] = {}
    r100_lookup: Dict[str, Dict[str, float]] = {}

    if not pois_only:
        expanded_path = os.path.join(DATASETS_DIR, "expanded_master_physics_dataset.pt")
        if os.path.exists(expanded_path):
            print("Loading expanded_master_physics_dataset.pt for compact extraction...")
            dl = torch.load(expanded_path, weights_only=False)
            for g in dl:
                r = getattr(g, "region", "") or getattr(g, "city", "")
                if r not in CATCHMENTS:
                    continue
                rain = float(g.rain_intensity)
                if abs(rain - 50.0) < 1.0 and r not in pyg_50:
                    pyg_50[r] = g.clone()
                if int(round(rain)) in (20, 50, 80, 120):
                    eval_swmm.setdefault(str(int(round(rain))), {})[r] = [
                        round(float(v), 5) for v in g.y.view(-1).tolist()
                    ]

        r100_path = os.path.join(DATA_DIR, "regime100_literal_swmm_rows_all.json")
        if os.path.exists(r100_path):
            with open(r100_path, "r") as f:
                raw100 = json.load(f)
            for r_key, rows in raw100.items():
                m = {}
                for row in rows:
                    sid = str(row["swmm_node_id"])
                    nid = sid[2:] if sid.startswith("J_") else sid
                    m[nid] = float(row["max_water_depth_m"])
                r100_lookup[r_key] = m

    pois_out: Dict[str, Any] = {"catchments": {}, "summary": {}}
    depots_out: List[Dict[str, Any]] = []
    betweenness_out: Dict[str, Dict[str, float]] = {}

    for r_key, meta in CATCHMENTS.items():
        gpath = os.path.join(GRAPHS_DIR, meta["file"])
        G = ox.load_graphml(gpath)
        node_ids = [str(n) for n in G.nodes()]
        raw_nodes = list(G.nodes())
        assert len(node_ids) == meta["expected_nodes"], f"{r_key} nodes mismatch"
        assert G.number_of_edges() == meta["expected_edges"], f"{r_key} edges mismatch"

        elevs = [float(G.nodes[n].get("elevation", 880.0)) for n in raw_nodes]
        elev_range = max(elevs) - min(elevs)
        if r_key in pyg_50:
            pyg_50[r_key].elev_range = float(elev_range)

        # Build UTM Point STRtree
        pts = [Point(float(G.nodes[n]["x"]), float(G.nodes[n]["y"])) for n in raw_nodes]
        tree = STRtree(pts)

        if not pois_only:
            if r_key in r100_lookup:
                eval_swmm.setdefault("100", {})[r_key] = [
                    round(r100_lookup[r_key].get(nid, 0.0), 5) for nid in node_ids
                ]

            print(f"Computing betweenness for {r_key} ({len(node_ids)} nodes)...")
            k_sample = None if len(node_ids) < 2000 else 400
            bc = nx.betweenness_centrality(G, k=k_sample, weight="length", seed=7)
            vals = np.array([float(bc[n]) for n in raw_nodes], dtype=np.float64)
            order = np.argsort(vals, kind="mergesort")
            ranks = np.empty_like(vals)
            ranks[order] = np.linspace(0.0, 1.0, len(vals)) if len(vals) > 1 else np.array([0.0])
            ranks[vals == 0.0] = 0.0
            betweenness_out[r_key] = {
                nid: round(float(ranks[i]), 4) for i, nid in enumerate(node_ids)
            }

        # Largest strongly connected component for depot safety
        sccs = sorted(nx.strongly_connected_components(G), key=len, reverse=True)
        scc_set = {str(n) for n in sccs[0]}
        elev_p60 = float(np.percentile(elevs, 60))

        # 3. POIs: curated municipal POIs > Oct-2024 incidents > deduplicated OSM edge POIs > arterial intersections
        poi_list: List[Dict[str, Any]] = []
        seen_node_cat = set()
        seen_utm: List[Tuple[float, float]] = []

        # 3c. Curated municipal POIs (highest reliability)
        for item in CURATED_POIS.get(r_key, []):
            nid, dist = _snap_point(
                item["lng"], item["lat"], tree, pts, node_ids, 450.0, scc_set
            )
            if nid is None:
                continue
            cat = item["category"]
            if (nid, cat) in seen_node_cat:
                continue
            seen_node_cat.add((nid, cat))
            raw_n = int(nid) if nid.isdigit() and int(nid) in G else nid
            n_obj = G.nodes[raw_n]
            ux, uy = float(n_obj["x"]), float(n_obj["y"])
            seen_utm.append((ux, uy))
            lon, lat = TRANSFORMER.transform(ux, uy)
            poi_list.append({
                "id": "",
                "name": item["name"],
                "category": cat,
                "catchment": r_key,
                "node_id": nid,
                "lat": round(lat, 6),
                "lng": round(lon, 6),
                "snap_m": round(dist, 1),
                "source": "curated_municipal",
            })

        # 3b. Nominatim Oct-2024 incidents (verified flood blackspots)
        for inc in incidents:
            if inc.get("region") != r_key:
                continue
            nid, dist = _snap_point(
                float(inc["lon"]), float(inc["lat"]), tree, pts, node_ids, 250.0, scc_set
            )
            if nid is None:
                continue
            loc = inc["location"]
            cat = _classify_edge_name(loc) or "arterial"
            if (nid, cat) in seen_node_cat:
                continue
            seen_node_cat.add((nid, cat))
            raw_n = int(nid) if nid.isdigit() and int(nid) in G else nid
            n_obj = G.nodes[raw_n]
            ux, uy = float(n_obj["x"]), float(n_obj["y"])
            seen_utm.append((ux, uy))
            lon, lat = TRANSFORMER.transform(ux, uy)
            poi_list.append({
                "id": "",
                "name": loc,
                "category": cat,
                "catchment": r_key,
                "node_id": nid,
                "lat": round(lat, 6),
                "lng": round(lon, 6),
                "snap_m": round(dist, 1),
                "source": "nominatim_incident",
            })

        # 3a. Deduplicated OSM graph edge names (1 highest-degree node per (cat, normalized_name) per 450m)
        edge_name_cands: Dict[Tuple[str, str], List[Tuple[int, Any]]] = {}
        for u, v, _, ed in G.edges(keys=True, data=True):
            nm = ed.get("name")
            if not nm:
                continue
            if isinstance(nm, list):
                nm = nm[0]
            nm_str = str(nm).strip()
            cat = _classify_edge_name(nm_str)
            if cat is None:
                continue
            edge_name_cands.setdefault((cat, nm_str.lower()), []).append(
                (int(G.degree(u)), u, nm_str)
            )
        for (cat, _), cands in sorted(edge_name_cands.items()):
            cands.sort(key=lambda item: (-item[0], str(item[1])))
            kept_for_name: List[Tuple[float, float]] = []
            for _, u, nm_str in cands:
                target_nid = str(u)
                ux, uy = float(G.nodes[u]["x"]), float(G.nodes[u]["y"])
                if any(math.hypot(ux - px, uy - py) < 500.0 for px, py in kept_for_name):
                    continue
                if (target_nid, cat) in seen_node_cat:
                    continue
                seen_node_cat.add((target_nid, cat))
                kept_for_name.append((ux, uy))
                seen_utm.append((ux, uy))
                lon, lat = TRANSFORMER.transform(ux, uy)
                poi_list.append({
                    "id": "",
                    "name": nm_str,
                    "category": cat,
                    "catchment": r_key,
                    "node_id": target_nid,
                    "lat": round(lat, 6),
                    "lng": round(lon, 6),
                    "snap_m": 0.0,
                    "source": "osm_graph_edge",
                })
                if len(kept_for_name) >= 2:
                    break

        # 3e. Major named arterial intersections (`Road A × Road B`)
        poi_list.extend(
            _extract_intersection_pois(G, r_key, seen_node_cat, seen_utm, limit=60)
        )

        # Assign sequential POI IDs deterministically
        for idx, p in enumerate(poi_list, 1):
            p["id"] = f"POI-{r_key.upper()}-{idx:03d}"

        # 3d. Arterial nodes (edges with highway in motorway/trunk/primary/secondary)
        arterial_nodes = set()
        for u, v, _, ed in G.edges(keys=True, data=True):
            hw = ed.get("highway", "")
            if isinstance(hw, list):
                hw = hw[0]
            if hw in (
                "motorway",
                "motorway_link",
                "trunk",
                "trunk_link",
                "primary",
                "primary_link",
                "secondary",
                "secondary_link",
            ):
                arterial_nodes.add(str(u))
                arterial_nodes.add(str(v))

        pois_out["catchments"][r_key] = {
            "pois": poi_list,
            "arterial_nodes": sorted(arterial_nodes),
        }
        pois_out["summary"][r_key] = {
            "poi_count": len(poi_list),
            "arterial_nodes": len(arterial_nodes),
            "underpasses": sum(1 for p in poi_list if p["category"] == "underpass"),
            "hospitals": sum(1 for p in poi_list if p["category"] == "hospital"),
            "transit_hubs": sum(1 for p in poi_list if p["category"] == "transit_hub"),
        }

        # 4. Depots in this catchment (non-basement, top 40% elev, in largest SCC)
        eligible_depots = set()
        for n in raw_nodes:
            nid = str(n)
            elev = float(G.nodes[n].get("elevation", 880.0))
            imp = float(G.nodes[n].get("impervious_ratio", 0.2))
            is_basement = imp > 0.4 and elev < 882.0
            if nid in scc_set and (not is_basement) and elev >= elev_p60:
                eligible_depots.add(nid)

        for d_seed in DEPOT_SEEDS:
            if d_seed["region"] != r_key:
                continue
            nid, dist = _snap_point(
                d_seed["lng"], d_seed["lat"], tree, pts, node_ids, 1500.0, eligible_depots
            )
            if nid is None:
                # Fallback to highest elevation node in SCC
                nid = max(scc_set, key=lambda s: float(G.nodes[int(s) if s.isdigit() and int(s) in G else s].get("elevation", 880.0)))
                dist = 0.0
            raw_n = int(nid) if nid.isdigit() and int(nid) in G else nid
            n_obj = G.nodes[raw_n]
            lon, lat = TRANSFORMER.transform(float(n_obj["x"]), float(n_obj["y"]))
            depots_out.append({
                "id": d_seed["id"],
                "name": d_seed["name"],
                "region": r_key,
                "node_id": nid,
                "lat": round(lat, 6),
                "lng": round(lon, 6),
                "elevation": round(float(n_obj.get("elevation", 880.0)), 2),
                "asset_classes": d_seed["classes"],
            })

    # Write outputs
    with open(os.path.join(COMMAND_DATA_DIR, "pois.json"), "w") as f:
        json.dump(pois_out, f, indent=2)
    with open(os.path.join(COMMAND_DATA_DIR, "depots.json"), "w") as f:
        json.dump({"depots": depots_out}, f, indent=2)
    if not pois_only and betweenness_out:
        with open(os.path.join(COMMAND_DATA_DIR, "betweenness.json"), "w") as f:
            json.dump(betweenness_out, f)

    # Default fleet.json: balanced underpass bindings across all 5 catchments
    all_underpasses = [
        p
        for r_key in CATCHMENTS
        for p in pois_out["catchments"][r_key]["pois"]
        if p["category"] == "underpass"
    ]
    fleet_seed = {
        "defaults": DEFAULT_FLEET,
        "depots": depots_out,
        "underpass_bindings": all_underpasses[:16],
        "specs": {
            "pump": {"capacity_lpm": 1500, "vehicle_profile": "pump_truck"},
            "barrier": {"veto_window_sec": 60, "bound_to": "underpass"},
            "warden": {"personnel": 2, "vehicle_profile": "warden"},
        },
    }
    with open(os.path.join(COMMAND_DATA_DIR, "fleet.json"), "w") as f:
        json.dump(fleet_seed, f, indent=2)

    if pyg_50:
        pyg_path = os.path.join(COMMAND_DATA_DIR, "pyg_bengaluru_50.pt")
        torch.save(pyg_50, pyg_path)
        print(f"Saved compact PyG cache: {pyg_path} ({os.path.getsize(pyg_path) / 1e6:.2f} MB)")

    if eval_swmm:
        eval_path = os.path.join(COMMAND_DATA_DIR, "eval_swmm_truth.json")
        with open(eval_path, "w") as f:
            json.dump(eval_swmm, f)
        print(f"Saved compact SWMM truth: {eval_path} ({os.path.getsize(eval_path) / 1e6:.2f} MB)")

    print("POI summary:", json.dumps(pois_out["summary"], indent=2))
    print(f"Prepared all command data in {time.time() - t_start:.2f} s")


if __name__ == "__main__":
    main()
