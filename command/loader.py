"""Read-only asset loader & spatial registry for UrbanFLOW Command & Dispatch.

Loads the five Bengaluru GraphML road networks directly via NetworkX (avoiding
osmnx's ~10 s import overhead), aligns compact PyG graphs and genuine EPA SWMM
reference depths, attaches snapped municipal POIs / depots / betweenness, and
initializes the frozen EnsembleFloodPredictorV4 inference engine.
"""
from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np
import torch
from pyproj import Transformer
from shapely import wkt as shapely_wkt
from shapely.geometry import Point
from shapely.strtree import STRtree

from command.config import (
    ASSET_WEIGHT,
    CATCHMENTS,
    COMMAND_DATA_DIR,
    DATASETS_DIR,
    EXPECTED_TOTAL_EDGES,
    EXPECTED_TOTAL_NODES,
    GRAPHS_DIR,
    HIGHWAY_SPEED_MPS,
    JUNCTION_NAMES,
)
from core.production_v4 import EnsembleFloodPredictorV4

UTM_TO_WGS84 = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
WGS84_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

_SOURCE_PRIORITY = {
    "curated_municipal": 4,
    "nominatim_incident": 3,
    "osm_graph_intersection": 2,
    "osm_graph_edge": 1,
}

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _parse_first_str(val: Any, default: str = "") -> str:
    """Extract first scalar string from raw GraphML scalar or stringified list."""
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else default
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)) and parsed:
                return str(parsed[0]).strip()
        except (ValueError, SyntaxError):
            pass
    return s or default


def _parse_speed_mps(raw_maxspeed: Any, highway: str) -> float:
    """Convert OSM maxspeed tag to m/s with highway-class fallback."""
    hw = highway.lower().strip()
    fallback = HIGHWAY_SPEED_MPS.get(hw, HIGHWAY_SPEED_MPS["default"])
    s = _parse_first_str(raw_maxspeed)
    if not s:
        return fallback
    m = _NUM_RE.search(s)
    if not m:
        return fallback
    val = float(m.group(1))
    mps = val * 0.44704 if "mph" in s.lower() else val / 3.6
    return float(max(2.0, min(30.0, mps)))


def _parse_edge_coords(
    raw_geom: Any,
    u_lonlat: List[float],
    v_lonlat: List[float],
) -> List[List[float]]:
    """Transform optional WKT LINESTRING from EPSG:32643 to rounded WGS84 coords."""
    if isinstance(raw_geom, str) and "LINESTRING" in raw_geom:
        try:
            geom = shapely_wkt.loads(raw_geom)
            coords = []
            for x, y in geom.coords:
                lon, lat = UTM_TO_WGS84.transform(float(x), float(y))
                coords.append([round(lon, 6), round(lat, 6)])
            if len(coords) >= 2:
                return coords
        except Exception:
            pass
    return [u_lonlat, v_lonlat]


@dataclass(frozen=True)
class EdgeRecord:
    """Pre-parsed directed road edge ready for routing and Deck.gl rendering."""

    eid: str
    u: str
    v: str
    key: str
    u_idx: int
    v_idx: int
    length_m: float
    t0_sec: float
    highway: str
    name: str
    coords: List[List[float]]


@dataclass
class CatchmentData:
    """All static graph, terrain, POI, betweenness, PyG, and SWMM data for one catchment."""

    key: str
    short: str
    name: str
    centroid: Tuple[float, float]  # (lat, lng)
    bounds: List[float]  # [min_lng, min_lat, max_lng, max_lat]
    graph: nx.MultiDiGraph
    node_ids: List[str]
    node_idx: Dict[str, int]
    x_utm: np.ndarray
    y_utm: np.ndarray
    lat: np.ndarray
    lng: np.ndarray
    elevation: np.ndarray
    impervious: np.ndarray
    dep_depth: np.ndarray
    sink_ratio: np.ndarray
    is_basement: np.ndarray
    betweenness: np.ndarray
    node_assets: List[List[str]]
    primary_asset: List[str]
    poi_names_by_node: Dict[str, str]
    underpass_poi_by_node: Dict[str, str]
    junction_names: List[str]
    edges: List[EdgeRecord]
    scc_nodes: Set[str]
    strtree: STRtree
    utm_points: List[Point]
    pyg_graph: Any
    swmm_truth: Dict[int, np.ndarray] = field(default_factory=dict)
    _swmm_keys: List[int] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._swmm_keys = sorted(self.swmm_truth.keys())

    def interpolate_swmm(self, node_i: int, rain_mmhr: float) -> float:
        """Linearly interpolate genuine EPA SWMM depth across calibrated intensities."""
        if not self._swmm_keys:
            return 0.0
        if rain_mmhr <= self._swmm_keys[0]:
            return float(self.swmm_truth[self._swmm_keys[0]][node_i])
        if rain_mmhr >= self._swmm_keys[-1]:
            return float(self.swmm_truth[self._swmm_keys[-1]][node_i])
        for lo, hi in zip(self._swmm_keys, self._swmm_keys[1:]):
            if lo <= rain_mmhr <= hi:
                alpha = (rain_mmhr - lo) / float(hi - lo)
                d_lo = float(self.swmm_truth[lo][node_i])
                d_hi = float(self.swmm_truth[hi][node_i])
                return d_lo + alpha * (d_hi - d_lo)
        return 0.0


@dataclass
class CommandRegistry:
    """Loaded singleton holding all 5 Bengaluru catchments, fleet seeds, and GNN predictor."""

    catchments: Dict[str, CatchmentData]
    pois: Dict[str, List[dict]]
    all_pois: List[dict]
    depots: List[dict]
    fleet_seed: dict
    predictor: Optional[EnsembleFloodPredictorV4]
    device: torch.device
    loaded_at: float
    load_sec: float
    node_to_catchment: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_to_catchment:
            self.node_to_catchment = {
                nid: key
                for key, c in self.catchments.items()
                for nid in c.node_ids
            }

    def total_nodes(self) -> int:
        return sum(len(c.node_ids) for c in self.catchments.values())

    def total_edges(self) -> int:
        return sum(len(c.edges) for c in self.catchments.values())

    def find_node(self, node_id: str) -> Optional[Tuple[CatchmentData, int]]:
        """Look up `(CatchmentData, node_index)` by string node_id."""
        nid = str(node_id)
        r_key = self.node_to_catchment.get(nid)
        if r_key is None:
            return None
        c = self.catchments[r_key]
        return c, c.node_idx[nid]

    def snap_coord(
        self,
        lng: float,
        lat: float,
        region_hint: Optional[str] = None,
        max_dist_m: float = 2500.0,
    ) -> Optional[Tuple[str, str, float]]:
        """Snap WGS84 `(lng, lat)` to nearest street junction in UTM coordinates."""
        ux, uy = WGS84_TO_UTM.transform(float(lng), float(lat))
        q = Point(ux, uy)
        candidates = (
            [self.catchments[region_hint]]
            if region_hint and region_hint in self.catchments
            else list(self.catchments.values())
        )
        best_key = ""
        best_nid = ""
        best_dist = float("inf")
        for c in candidates:
            idx = int(c.strtree.nearest(q))
            dist = float(c.utm_points[idx].distance(q))
            if dist < best_dist:
                best_dist = dist
                best_key = c.key
                best_nid = c.node_ids[idx]
        if best_dist > max_dist_m or not best_nid:
            return None
        return best_key, best_nid, round(best_dist, 2)


def _load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_pyg_cache() -> Dict[str, Any]:
    compact_path = os.path.join(COMMAND_DATA_DIR, "pyg_bengaluru_50.pt")
    if os.path.exists(compact_path):
        return torch.load(compact_path, map_location="cpu", weights_only=False)
    expanded_path = os.path.join(DATASETS_DIR, "expanded_master_physics_dataset.pt")
    if os.path.exists(expanded_path):
        out: Dict[str, Any] = {}
        dl = torch.load(expanded_path, map_location="cpu", weights_only=False)
        for g in dl:
            r = getattr(g, "region", "") or getattr(g, "city", "")
            if r in CATCHMENTS and abs(float(g.rain_intensity) - 50.0) < 1.0 and r not in out:
                out[r] = g
        return out
    raise FileNotFoundError(
        "Missing data/command/pyg_bengaluru_50.pt. Run `python scripts/command/prepare_data.py`."
    )


def _compute_depression_depth(G: nx.MultiDiGraph, node_ids: List[str], elev: np.ndarray) -> np.ndarray:
    """Compute local topographic sink depth: max(0, mean_neighbor_elev - node_elev)."""
    idx_map = {nid: i for i, nid in enumerate(node_ids)}
    nbr_sets: List[Set[int]] = [set() for _ in node_ids]
    for u, v in G.edges():
        ui, vi = idx_map.get(str(u)), idx_map.get(str(v))
        if ui is not None and vi is not None and ui != vi:
            nbr_sets[ui].add(vi)
            nbr_sets[vi].add(ui)

    dep = np.zeros(len(node_ids), dtype=np.float32)
    for i, nbrs in enumerate(nbr_sets):
        if nbrs:
            mean_nbr = float(np.mean([elev[j] for j in nbrs]))
            dep[i] = max(0.0, mean_nbr - float(elev[i]))
    return dep


def _build_node_assets(
    node_ids: List[str],
    poi_list: List[dict],
    arterial_set: Set[str],
) -> Tuple[List[List[str]], List[str], Dict[str, str], Dict[str, str]]:
    raw_cats: Dict[str, Set[str]] = {nid: set() for nid in node_ids}
    poi_names: Dict[str, str] = {}
    poi_prio: Dict[str, int] = {}
    underpass_map: Dict[str, str] = {}

    for nid in arterial_set:
        if nid in raw_cats:
            raw_cats[nid].add("arterial")

    for poi in poi_list:
        nid = str(poi["node_id"])
        if nid not in raw_cats:
            continue
        cat = str(poi["category"])
        raw_cats[nid].add(cat)
        if cat == "underpass" and nid not in underpass_map:
            underpass_map[nid] = str(poi["id"])
        prio = _SOURCE_PRIORITY.get(poi.get("source", ""), 0)
        if prio >= poi_prio.get(nid, -1):
            poi_prio[nid] = prio
            poi_names[nid] = str(poi["name"])

    node_assets: List[List[str]] = []
    primary_asset: List[str] = []
    for nid in node_ids:
        cats = raw_cats[nid]
        if not cats:
            node_assets.append(["street"])
            primary_asset.append("street")
        else:
            sorted_cats = sorted(
                cats, key=lambda c: (-ASSET_WEIGHT.get(c, 0.25), c)
            )
            node_assets.append(sorted_cats)
            primary_asset.append(sorted_cats[0])

    return node_assets, primary_asset, poi_names, underpass_map


def _build_catchment(
    r_key: str,
    meta: dict,
    pois_raw: dict,
    bc_map: Dict[str, float],
    pyg_graph: Any,
    eval_swmm_raw: Dict[str, Dict[str, List[float]]],
) -> CatchmentData:
    gpath = os.path.join(GRAPHS_DIR, meta["file"])
    G = nx.read_graphml(gpath)
    node_ids = [str(n) for n in G.nodes()]
    n_nodes = len(node_ids)
    n_edges = G.number_of_edges()

    if n_nodes != meta["expected_nodes"]:
        raise ValueError(
            f"Catchment {r_key}: expected {meta['expected_nodes']} nodes, got {n_nodes}"
        )
    if n_edges != meta["expected_edges"]:
        raise ValueError(
            f"Catchment {r_key}: expected {meta['expected_edges']} edges, got {n_edges}"
        )

    node_idx = {nid: i for i, nid in enumerate(node_ids)}
    x_utm = np.array([float(G.nodes[nid]["x"]) for nid in node_ids], dtype=np.float64)
    y_utm = np.array([float(G.nodes[nid]["y"]) for nid in node_ids], dtype=np.float64)
    lng_arr, lat_arr = UTM_TO_WGS84.transform(x_utm, y_utm)
    lng = np.asarray(lng_arr, dtype=np.float64)
    lat = np.asarray(lat_arr, dtype=np.float64)

    elevation = np.array(
        [float(G.nodes[nid].get("elevation", 880.0)) for nid in node_ids], dtype=np.float32
    )
    impervious = np.array(
        [float(G.nodes[nid].get("impervious_ratio", 0.2)) for nid in node_ids], dtype=np.float32
    )
    if not hasattr(pyg_graph, "elev_range"):
        pyg_graph.elev_range = float(elevation.max() - elevation.min())

    dep_depth = _compute_depression_depth(G, node_ids, elevation)
    sink_ratio = np.clip(dep_depth / 0.50, 0.0, 1.0).astype(np.float32)
    is_basement = (impervious > 0.4) & (elevation < 882.0)

    bc_region = bc_map.get(r_key, {})
    betweenness = np.array(
        [float(bc_region.get(nid, 0.0)) for nid in node_ids], dtype=np.float32
    )

    c_pois = pois_raw.get("catchments", {}).get(r_key, {})
    poi_list: List[dict] = c_pois.get("pois", [])
    arterial_set: Set[str] = set(str(x) for x in c_pois.get("arterial_nodes", []))
    node_assets, primary_asset, poi_names, underpass_map = _build_node_assets(
        node_ids, poi_list, arterial_set
    )

    edge_names_by_node: Dict[str, List[str]] = {}
    edges: List[EdgeRecord] = []
    for u, v, k, ed in G.edges(keys=True, data=True):
        us, vs, ks = str(u), str(v), str(k)
        ui, vi = node_idx[us], node_idx[vs]
        hw = _parse_first_str(ed.get("highway"), "unclassified").lower()
        road_name = _parse_first_str(ed.get("name"), "")
        if road_name:
            for end_n in (us, vs):
                names_here = edge_names_by_node.setdefault(end_n, [])
                if road_name not in names_here and len(names_here) < 2:
                    names_here.append(road_name)
        length_m = max(1.0, float(ed.get("length", 50.0)))
        speed_mps = _parse_speed_mps(ed.get("maxspeed"), hw)
        t0_sec = length_m / max(speed_mps, 1.0)
        u_ll = [round(float(lng[ui]), 6), round(float(lat[ui]), 6)]
        v_ll = [round(float(lng[vi]), 6), round(float(lat[vi]), 6)]
        coords = _parse_edge_coords(ed.get("geometry"), u_ll, v_ll)
        edges.append(
            EdgeRecord(
                eid=f"{r_key}:{us}->{vs}:{ks}",
                u=us,
                v=vs,
                key=ks,
                u_idx=ui,
                v_idx=vi,
                length_m=round(length_m, 2),
                t0_sec=round(t0_sec, 3),
                highway=hw,
                name=road_name,
                coords=coords,
            )
        )

    fallback_pool = JUNCTION_NAMES.get(r_key, ("Street Junction",))
    junction_names: List[str] = []
    for nid in node_ids:
        if nid in poi_names:
            junction_names.append(poi_names[nid])
        elif nid in edge_names_by_node:
            nms = edge_names_by_node[nid]
            if len(nms) >= 2:
                junction_names.append(f"{nms[0]} × {nms[1]}")
            else:
                junction_names.append(f"{nms[0]} ({nid[-4:]})")
        else:
            idx = sum(ord(ch) for ch in nid) % len(fallback_pool)
            junction_names.append(fallback_pool[idx])

    utm_points = [Point(float(x_utm[i]), float(y_utm[i])) for i in range(n_nodes)]
    strtree = STRtree(utm_points)
    sccs = sorted(nx.strongly_connected_components(G), key=len, reverse=True)
    scc_nodes = {str(n) for n in sccs[0]} if sccs else set()

    swmm_truth: Dict[int, np.ndarray] = {}
    for rain_str, by_region in eval_swmm_raw.items():
        if r_key in by_region:
            arr = np.asarray(by_region[r_key], dtype=np.float32)
            if len(arr) == n_nodes:
                swmm_truth[int(rain_str)] = arr

    return CatchmentData(
        key=r_key,
        short=meta["short"],
        name=meta["name"],
        centroid=(round(float(lat.mean()), 6), round(float(lng.mean()), 6)),
        bounds=[
            round(float(lng.min()), 6),
            round(float(lat.min()), 6),
            round(float(lng.max()), 6),
            round(float(lat.max()), 6),
        ],
        graph=G,
        node_ids=node_ids,
        node_idx=node_idx,
        x_utm=x_utm,
        y_utm=y_utm,
        lat=lat,
        lng=lng,
        elevation=elevation,
        impervious=impervious,
        dep_depth=dep_depth,
        sink_ratio=sink_ratio,
        is_basement=is_basement,
        betweenness=betweenness,
        node_assets=node_assets,
        primary_asset=primary_asset,
        poi_names_by_node=poi_names,
        underpass_poi_by_node=underpass_map,
        junction_names=junction_names,
        edges=edges,
        scc_nodes=scc_nodes,
        strtree=strtree,
        utm_points=utm_points,
        pyg_graph=pyg_graph,
        swmm_truth=swmm_truth,
    )


def load_registry(load_model: bool = True) -> CommandRegistry:
    """Load all static graphs, POIs, depots, SWMM truth, and GNN ensemble."""
    t0 = time.perf_counter()
    pois_raw = _load_json(os.path.join(COMMAND_DATA_DIR, "pois.json"), {"catchments": {}})
    depots_raw = _load_json(os.path.join(COMMAND_DATA_DIR, "depots.json"), {"depots": []})
    bc_map = _load_json(os.path.join(COMMAND_DATA_DIR, "betweenness.json"), {})
    fleet_seed = _load_json(os.path.join(COMMAND_DATA_DIR, "fleet.json"), {})
    eval_swmm_raw = _load_json(os.path.join(COMMAND_DATA_DIR, "eval_swmm_truth.json"), {})
    pyg_50 = _load_pyg_cache()

    catchments: Dict[str, CatchmentData] = {}
    pois_by_catchment: Dict[str, List[dict]] = {}
    all_pois: List[dict] = []

    for r_key, meta in CATCHMENTS.items():
        if r_key not in pyg_50:
            raise KeyError(f"PyG graph for catchment '{r_key}' missing from cache")
        c = _build_catchment(
            r_key, meta, pois_raw, bc_map, pyg_50[r_key], eval_swmm_raw
        )
        catchments[r_key] = c
        c_pois = pois_raw.get("catchments", {}).get(r_key, {}).get("pois", [])
        pois_by_catchment[r_key] = c_pois
        all_pois.extend(c_pois)

    total_n = sum(len(c.node_ids) for c in catchments.values())
    total_e = sum(len(c.edges) for c in catchments.values())
    if total_n != EXPECTED_TOTAL_NODES or total_e != EXPECTED_TOTAL_EDGES:
        raise ValueError(
            f"Parity error: got {total_n} nodes / {total_e} edges, "
            f"expected {EXPECTED_TOTAL_NODES} / {EXPECTED_TOTAL_EDGES}"
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    predictor = EnsembleFloodPredictorV4(device=device) if load_model else None

    return CommandRegistry(
        catchments=catchments,
        pois=pois_by_catchment,
        all_pois=all_pois,
        depots=depots_raw.get("depots", []),
        fleet_seed=fleet_seed,
        predictor=predictor,
        device=device,
        loaded_at=time.time(),
        load_sec=round(time.perf_counter() - t0, 3),
    )


_REG_LOCK = threading.Lock()
_REG_SINGLETON: Optional[CommandRegistry] = None


def get_registry(load_model: bool = True) -> CommandRegistry:
    """Thread-safe singleton accessor for `CommandRegistry`."""
    global _REG_SINGLETON
    with _REG_LOCK:
        if _REG_SINGLETON is None:
            _REG_SINGLETON = load_registry(load_model=load_model)
        elif load_model and _REG_SINGLETON.predictor is None:
            _REG_SINGLETON.predictor = EnsembleFloodPredictorV4(
                device=_REG_SINGLETON.device
            )
        return _REG_SINGLETON
