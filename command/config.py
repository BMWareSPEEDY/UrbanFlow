"""Single source of truth for UrbanFLOW Command & Dispatch constants.

Every threshold, consequence weight, asset criticality weight, vehicle profile,
routing penalty, and fleet bound lives here. Frontend mirrors these via
`/api/v1/bootstrap` (and `web/src/lib/scoring.ts`).
"""
from __future__ import annotations

import os
from typing import Dict, Tuple

VERSION = "1.0.0"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHS_DIR = os.path.join(BASE_DIR, "graphs")
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
COMMAND_DATA_DIR = os.path.join(DATA_DIR, "command")
LOGS_DIR = os.path.join(COMMAND_DATA_DIR, "logs")
EVAL_DIR = os.path.join(BASE_DIR, "scratch", "evaluation")
STATIC_COMMAND_DIR = os.path.join(BASE_DIR, "static", "command")

# Five Bengaluru catchments (D-14). Graphs are disconnected; fleet is city-wide (D-15).
CATCHMENTS: Dict[str, dict] = {
    "hsr": {
        "key": "hsr",
        "short": "HSR",
        "name": "HSR Layout (Residential Hub)",
        "file": "bengaluru_complete_graph.graphml",
        "lat": 12.9116,
        "lng": 77.6389,
        "expected_nodes": 1379,
        "expected_edges": 3733,
    },
    "bellandur": {
        "key": "bellandur",
        "short": "BLR",
        "name": "Bellandur & ORR (Lake Basin)",
        "file": "bengaluru_bellandur_graph.graphml",
        "lat": 12.9340,
        "lng": 77.6880,
        "expected_nodes": 1507,
        "expected_edges": 3197,
    },
    "whitefield": {
        "key": "whitefield",
        "short": "WFD",
        "name": "Whitefield (ITPB Corridor)",
        "file": "bengaluru_whitefield_graph.graphml",
        "lat": 12.9698,
        "lng": 77.7500,
        "expected_nodes": 1797,
        "expected_edges": 3994,
    },
    "ecity": {
        "key": "ecity",
        "short": "ECT",
        "name": "Electronic City (Tech Corridor)",
        "file": "bengaluru_ecity_graph.graphml",
        "lat": 12.8451,
        "lng": 77.6602,
        "expected_nodes": 3337,
        "expected_edges": 7610,
    },
    "koramangala": {
        "key": "koramangala",
        "short": "KRM",
        "name": "Koramangala & Indiranagar",
        "file": "bengaluru_koramangala_graph.graphml",
        "lat": 12.9352,
        "lng": 77.6245,
        "expected_nodes": 4416,
        "expected_edges": 11183,
    },
}

EXPECTED_TOTAL_NODES = sum(c["expected_nodes"] for c in CATCHMENTS.values())  # 12,436
EXPECTED_TOTAL_EDGES = sum(c["expected_edges"] for c in CATCHMENTS.values())  # 29,717

# One threshold ladder (D-05, D-09). Red-Alert lowers action triggers to compensate
# for 32.2 % critical recall at 100 mm/hr while keeping alert_floor at 0.08 m.
THRESHOLDS: Dict[str, Dict[str, float]] = {
    "normal": {"alert_floor": 0.08, "barrier": 0.15, "pump": 0.30},
    "red_alert": {"alert_floor": 0.08, "barrier": 0.09, "pump": 0.25},
}

# Consequence score weights (D-08) — MUST sum to 1.0.
TRIAGE_WEIGHTS: Dict[str, float] = {
    "severity": 0.45,
    "asset": 0.30,
    "vulnerability": 0.15,
    "network": 0.10,
}
assert abs(sum(TRIAGE_WEIGHTS.values()) - 1.0) < 1e-9, "TRIAGE_WEIGHTS must sum to 1.0"

SEVERITY_MIN_M = 0.05
SEVERITY_MAX_M = 0.40

# Asset criticality weights — mirrored identically in web/src/lib/scoring.ts.
ASSET_WEIGHT: Dict[str, float] = {
    "underpass": 1.00,
    "transit_hub": 0.95,
    "hospital": 0.95,
    "fire_station": 0.90,
    "power_substation": 0.85,
    "school": 0.70,
    "arterial": 0.60,
    "watercourse": 0.55,
    "street": 0.25,
}

# Critical asset threshold for evaluation (IMPLEMENTATION_PLAN §11.3).
CRITICAL_ASSET_WEIGHT_MIN = 0.85

# Priority tiers on 0..100 Consequence Score.
PRIORITY_THRESHOLDS: Tuple[Tuple[str, float], ...] = (
    ("P1", 70.0),
    ("P2", 50.0),
    ("P3", 30.0),
)

# Spatial deduplication radius (metres) in EPSG:32643 UTM space.
CLUSTER_RADIUS_M = 200.0

# Free-flow speeds (m/s) when OSM maxspeed tag is missing/unparseable.
HIGHWAY_SPEED_MPS: Dict[str, float] = {
    "motorway": 22.0,
    "motorway_link": 16.0,
    "trunk": 18.0,
    "trunk_link": 14.0,
    "primary": 14.0,
    "primary_link": 11.0,
    "secondary": 12.0,
    "secondary_link": 10.0,
    "tertiary": 10.0,
    "tertiary_link": 8.5,
    "unclassified": 9.0,
    "residential": 8.0,
    "living_street": 6.0,
    "service": 6.0,
    "busway": 12.0,
    "default": 9.0,
}

# Vehicle passability profiles (D-07, spec §6.3).
VEHICLE_PROFILES: Dict[str, Dict[str, float]] = {
    "pump_truck": {"d_safe": 0.05, "d_impass": 0.25, "speed_mult": 0.80},
    "warden": {"d_safe": 0.05, "d_impass": 0.20, "speed_mult": 0.90},
    "bus": {"d_safe": 0.05, "d_impass": 0.25, "speed_mult": 0.75},
    "ambulance": {"d_safe": 0.05, "d_impass": 0.30, "speed_mult": 1.00},
    "fire_engine": {"d_safe": 0.05, "d_impass": 0.30, "speed_mult": 1.00},
    "civilian": {"d_safe": 0.05, "d_impass": 0.20, "speed_mult": 1.00},
}

# Inter-catchment highway stub parameters (D-14, D-15, §6.2).
INTER_CATCHMENT_SPEED_MPS = 12.0
INTER_CATCHMENT_PENALTY_MIN = 20.0

# Fleet & timing constants (§7.1, §7.2, spec §7.2-7.3).
MOBILIZE_MIN = 5.0
SAFETY_MIN = 5.0
DEWATERING_BASE_MIN = 45.0
DEWATERING_MIN_CLAMP = (45.0, 135.0)
WARDEN_ON_SITE_MIN = 30.0
BARRIER_VETO_WINDOW_SEC = 60.0
BARRIER_VETO_WINDOW_MIN = 1.0
DISPATCH_CANCEL_WINDOW_SEC = 30.0

FLEET_LIMITS: Dict[str, Tuple[int, int]] = {
    "pumps": (0, 30),
    "barriers": (0, 24),
    "wardens": (0, 24),
}

DEFAULT_FLEET: Dict[str, int] = {
    "pumps": 12,
    "barriers": 8,
    "wardens": 6,
}

# Model forcing clamps matching app.py:848-849 (D-13).
RAINFALL_CLAMP: Tuple[float, float] = (20.0, 300.0)
DURATION_CLAMP: Tuple[float, float] = (15.0, 120.0)
UI_RAINFALL_RANGE: Tuple[int, int] = (20, 120)
UI_DURATION_RANGE: Tuple[int, int] = (15, 120)

# Deterministic junction fallback names (from app.py:740, read-only mirror).
JUNCTION_NAMES: Dict[str, Tuple[str, ...]] = {
    "hsr": (
        "14th Main & 17th Cross Corridor",
        "27th Main Commercial Belt",
        "Silk Board Underpass Ramp",
        "5th Main Parangi Palya Dip",
        "Sector 6 Low-Lying Sag",
        "Sector 7 Storm Canal Choke",
        "Agara Lake Outfall Channel",
        "19th Main Service Road",
        "Sector 1 Ring Road Ingress",
        "Sector 2 9th Cross Dip",
        "Sector 3 Park Boulevard",
        "HSR Water Tank Junction",
        "22nd Cross Arterial",
        "Sector 4 Low Conduit",
        "14th Main Transit Corridor",
    ),
    "bellandur": (
        "EcoSpace Tech Park Main Gate",
        "Devarabisanahalli Flyover Service Road",
        "Central Mall Bellandur Underpass",
        "Bellandur Lake Inflow Canal",
        "Kadubeesanahalli Low Road",
        "Marathahalli Multiplex Junction",
        "ORR Northbound Surcharge Dip",
        "Kariyammana Agrahara Corridor",
        "Green Glen Layout Inundation Dip",
        "Outer Ring Road Transit Spine",
    ),
    "whitefield": (
        "Hope Farm Junction Corridor",
        "ITPB Main Gate Boulevard",
        "Kundalahalli Gate Underpass",
        "Channasandra Railway Bridge Underpass",
        "Varthur Lake Inflow Channel",
        "ECC Road Commercial Dip",
        "Kadugodi Industrial Outfall",
        "Whitefield Main Road Choke",
        "Brookefield Service Road",
        "ITPB Tech Corridor North",
    ),
    "ecity": (
        "Electronic City Tollgate Ramp",
        "Phase 1 Tech Park Boundary Drain",
        "Velankani Drive Low-Lying Road",
        "Doddathoguru Lake Outfall Canal",
        "Hosur Road Underpass Portal",
        "Neotown Arterial Dip",
        "Phase 2 Transit Hub",
        "Cyber Park Drainage Surcharge",
        "Electronic City Flyover Ingress",
        "Infosys Avenue Crossing",
    ),
    "koramangala": (
        "Sony World Junction Corridor",
        "Koramangala 4th Block 80 Feet Road",
        "Ejipura Canal Outfall Surcharge",
        "ST Bed Layout Ground Floor Sag",
        "Koramangala 1st Block Low Point",
        "National Games Village Ingress",
        "Koramangala Valley Storm Trunk",
        "100 Feet Road Indiranagar Dip",
        "Wipro Park Arterial Junction",
        "Passport Seva Kendra Underpass",
    ),
}
