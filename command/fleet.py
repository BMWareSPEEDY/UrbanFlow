"""Fleet inventory initialization, nearest-feasible assignment, clock progression, and scarcity handling."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import threading
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import numpy as np

from command.config import (
    BARRIER_VETO_WINDOW_MIN,
    DEWATERING_BASE_MIN,
    DEWATERING_MIN_CLAMP,
    MOBILIZE_MIN,
    SAFETY_MIN,
    VEHICLE_PROFILES,
    WARDEN_ON_SITE_MIN,
)
from command.loader import CommandRegistry
from command.routing import route_nodes

UNIT_SPECS: Dict[str, str] = {
    "pump": "1500 L/min Mobile Pump",
    "barrier": "Automated Underpass Barrier",
    "warden": "2-Officer Diversion Unit",
}

VEHICLE_FOR_CLASS: Dict[str, str] = {
    "pump": "pump_truck",
    "warden": "warden",
}


def format_sim_ts(sim_clock_min: float) -> str:
    """Format simulation clock in explicit T+XXXm simulation notation."""
    total_m = max(0, int(round(sim_clock_min)))
    return f"T+{total_m:03d}m"


def _compute_dewatering_min(depth_m: float) -> float:
    raw = DEWATERING_BASE_MIN * max(0.5, depth_m / 0.30)
    lo, hi = DEWATERING_MIN_CLAMP
    return round(float(max(lo, min(hi, raw))), 1)


def _format_when_directive(
    unit_class: str,
    feasible: bool,
    eta_min: Optional[float],
    ttp_min: float,
    free_in_min: Optional[float] = None,
    total_class_count: int = 0,
) -> str:
    if not feasible:
        if total_class_count == 0:
            return f"UNAVAILABLE · 0 {unit_class}s configured (use Setup or fallback)"
        if free_in_min is not None:
            return f"SHORTAGE · Nearest {unit_class} frees in {free_in_min:.0f}m (peak {ttp_min:.0f}m)"
        return f"BLOCKED · All routes submerged (peak {ttp_min:.0f}m)"

    if unit_class == "barrier":
        return f"Lock NOW · 60s veto window (peak {ttp_min:.0f}m)"

    assert eta_min is not None
    if eta_min > ttp_min:
        return f"LATE · ETA {eta_min:.0f}m arrives after T+{ttp_min:.0f}m peak"
    slack = round(ttp_min - eta_min, 1)
    if slack <= 10.0:
        return f"Deploy NOW · ETA {eta_min:.0f}m vs peak {ttp_min:.0f}m"
    return f"Dispatch by T+{slack:.0f}m · ETA {eta_min:.0f}m before T+{ttp_min:.0f}m peak"


@dataclass
class FleetUnit:
    """Stateful resource unit tracked per command session."""

    unit_id: str
    unit_class: str  # "pump" | "barrier" | "warden"
    depot_id: str
    depot_name: str
    home_node_id: str
    home_catchment: str
    current_node_id: str
    current_catchment: str
    underpass_poi_id: Optional[str] = None
    state: str = "IDLE"  # pump/warden: IDLE|EN_ROUTE|DEWATERING|ON_SITE|RETURNING ; barrier: IDLE|PENDING_CLOSE|CLOSED|STANDBY
    assigned_alert_id: Optional[str] = None
    target_node_id: Optional[str] = None
    target_name: Optional[str] = None
    target_catchment: Optional[str] = None
    eta_min: float = 0.0
    remaining_min: float = 0.0
    site_duration_min: float = 0.0
    return_eta_min: float = 0.0
    veto_deadline_min: float = 0.0
    inter_catchment: bool = False
    active_route: Optional[dict] = field(default=None, repr=False)

    def to_dict(self, sim_clock_min: float) -> dict:
        veto_left_s = (
            max(0.0, (self.veto_deadline_min - sim_clock_min) * 60.0)
            if self.state == "PENDING_CLOSE"
            else 0.0
        )
        return {
            "unit_id": self.unit_id,
            "unit_class": self.unit_class,
            "spec": UNIT_SPECS.get(self.unit_class, self.unit_class),
            "depot_id": self.depot_id,
            "depot_name": self.depot_name,
            "home_node_id": self.home_node_id,
            "home_catchment": self.home_catchment,
            "current_node_id": self.current_node_id,
            "current_catchment": self.current_catchment,
            "underpass_poi_id": self.underpass_poi_id,
            "state": self.state,
            "assigned_alert_id": self.assigned_alert_id,
            "target_node_id": self.target_node_id,
            "target_name": self.target_name,
            "target_catchment": self.target_catchment,
            "eta_min": round(self.eta_min, 1),
            "remaining_min": round(self.remaining_min, 1),
            "veto_remaining_sec": round(veto_left_s, 1),
            "inter_catchment": self.inter_catchment,
        }


def build_initial_fleet(reg: CommandRegistry, fleet_cfg: dict) -> List[FleetUnit]:
    """Instantiate exact session fleet inventory across regional depots & underpasses."""
    units: List[FleetUnit] = []
    depots = reg.depots
    if not depots:
        raise RuntimeError("No depots loaded in CommandRegistry")

    for idx in range(int(fleet_cfg["pumps"])):
        d = depots[idx % len(depots)]
        units.append(
            FleetUnit(
                unit_id=f"PUMP-{idx + 1:02d}",
                unit_class="pump",
                depot_id=d["id"],
                depot_name=d["name"],
                home_node_id=str(d["node_id"]),
                home_catchment=d["region"],
                current_node_id=str(d["node_id"]),
                current_catchment=d["region"],
            )
        )

    underpasses = reg.fleet_seed.get("underpass_bindings") or [
        p for p in reg.all_pois if p.get("category") == "underpass"
    ]
    for idx in range(int(fleet_cfg["barriers"])):
        if underpasses:
            up = underpasses[idx % len(underpasses)]
            node_id = str(up["node_id"])
            catchment = str(up["catchment"])
            up_id = str(up["id"])
            up_name = str(up["name"])
        else:
            d = depots[idx % len(depots)]
            node_id = str(d["node_id"])
            catchment = str(d["region"])
            up_id = None
            up_name = d["name"]
        units.append(
            FleetUnit(
                unit_id=f"BAR-{idx + 1:02d}",
                unit_class="barrier",
                depot_id="FIXED-GATE",
                depot_name=up_name,
                home_node_id=node_id,
                home_catchment=catchment,
                current_node_id=node_id,
                current_catchment=catchment,
                underpass_poi_id=up_id,
            )
        )

    for idx in range(int(fleet_cfg["wardens"])):
        d = depots[idx % len(depots)]
        units.append(
            FleetUnit(
                unit_id=f"WRD-{idx + 1:02d}",
                unit_class="warden",
                depot_id=d["id"],
                depot_name=d["name"],
                home_node_id=str(d["node_id"]),
                home_catchment=d["region"],
                current_node_id=str(d["node_id"]),
                current_catchment=d["region"],
            )
        )

    return units


def closed_barrier_nodes(units: List[FleetUnit]) -> FrozenSet[str]:
    """Return junction node_ids currently physically locked by CLOSED barriers."""
    return frozenset(
        u.target_node_id or u.home_node_id
        for u in units
        if u.unit_class == "barrier" and u.state == "CLOSED"
    )


_ENRICH_LOCK = threading.Lock()
_ENRICH_CACHE: "OrderedDict[Tuple[Any, ...], List[dict]]" = OrderedDict()
_MAX_ENRICH_CACHE = 128


def _node_latlng(reg: CommandRegistry, nid: str) -> Optional[Tuple[float, float]]:
    found = reg.find_node(nid)
    if found is None:
        return None
    c, idx = found
    return float(c.lat[idx]), float(c.lng[idx])


def _best_candidate_for_alert(
    reg: CommandRegistry,
    alert: dict,
    units: List[FleetUnit],
    excluded_unit_ids: set[str],
    depths_by_catchment: Dict[str, np.ndarray],
    closed_barriers: FrozenSet[str],
    scenario_key: str,
) -> dict:
    """Evaluate best available IDLE unit (or explicit refusal diagnostic) for one alert."""
    uclass = alert["unit_class"]
    target_node = str(alert["id"])
    target_catchment = str(alert["catchment"])
    ttp_min = float(alert.get("ttp_min", 45.0))
    class_units = [u for u in units if u.unit_class == uclass]
    idle_units = [
        u for u in class_units if u.state == "IDLE" and u.unit_id not in excluded_unit_ids
    ]

    if uclass == "barrier":
        # Prefer idle barrier bound to the same underpass or catchment
        up_id = alert.get("underpass_poi_id")
        if not idle_units:
            return _no_unit_refusal(uclass, class_units, ttp_min, "No automated barrier available.")
        chosen = next((u for u in idle_units if up_id and u.underpass_poi_id == up_id), None)
        if chosen is None:
            chosen = next(
                (u for u in idle_units if u.home_catchment == target_catchment),
                idle_units[0],
            )
        # Barriers close instantly (ETA 0), but the operator still needs to see the
        # access corridor / gate location on the map before approving. Without a
        # route preview the map has nothing to draw for a pending closure.
        preview = route_nodes(
            reg,
            chosen.current_node_id,
            target_node,
            depths_by_catchment,
            vehicle="pump_truck",
            closed_barriers=closed_barriers,
            scenario_key=scenario_key,
            allow_terminal_staging=True,
        )
        if not preview.get("reachable"):
            std = preview.get("standard") or {}
            if std.get("coords"):
                preview = {**preview, "reachable": True, "safe": preview.get("safe") or std}
            else:
                found = reg.find_node(target_node) or reg.find_node(chosen.current_node_id)
                if found is not None:
                    c, idx = found
                    pt = [float(c.lng[idx]), float(c.lat[idx])]
                else:
                    pt = [77.5946, 12.9716]
                leg = {"coords": [pt, pt], "distance_m": 0.0, "duration_min": 0.0, "node_ids": [target_node]}
                preview = {**preview, "reachable": True, "standard": leg, "safe": leg}
        return {
            "feasible": True,
            "infeasible_reason": None,
            "message": None,
            "unit": chosen,
            "eta_min": 0.0,
            "added_minutes": 0.0,
            "inter_catchment": False,
            "route": preview,
            "when_directive": _format_when_directive("barrier", True, 0.0, ttp_min),
        }

    if not idle_units:
        return _no_unit_refusal(
            uclass,
            class_units,
            ttp_min,
            f"No free {uclass} unit available.",
        )

    vehicle = VEHICLE_FOR_CLASS.get(uclass, "pump_truck")
    # Same-catchment units never incur +20m inter-catchment penalty; check local catchment first!
    tgt_pt = _node_latlng(reg, target_node)

    def _dist_key(u: FleetUnit) -> float:
        if tgt_pt is None:
            return 0.0
        src_pt = _node_latlng(reg, u.current_node_id)
        if src_pt is None:
            return 1e9
        dlat = src_pt[0] - tgt_pt[0]
        dlng = src_pt[1] - tgt_pt[1]
        return dlat * dlat + dlng * dlng

    local_units = sorted((u for u in idle_units if u.current_catchment == target_catchment), key=_dist_key)
    remote_units = sorted((u for u in idle_units if u.current_catchment != target_catchment), key=_dist_key)

    best: Optional[Tuple[Tuple[int, float, str], FleetUnit, dict, float]] = None
    route_by_origin: Dict[str, dict] = {}

    def _eval_pool(pool: List[FleetUnit], max_distinct_origins: int = 3) -> None:
        nonlocal best
        seen_origins: set[str] = set()
        deferred: List[FleetUnit] = []
        for u in pool:
            orig = u.current_node_id
            if orig not in seen_origins and len(seen_origins) >= max_distinct_origins:
                deferred.append(u)
                continue
            seen_origins.add(orig)
            if orig not in route_by_origin:
                route_by_origin[orig] = route_nodes(
                    reg,
                    orig,
                    target_node,
                    depths_by_catchment,
                    vehicle=vehicle,
                    closed_barriers=closed_barriers,
                    scenario_key=scenario_key,
                    allow_terminal_staging=True,
                )
            rt = route_by_origin[orig]
            if not rt["reachable"]:
                continue
            inter = bool(rt["inter_catchment"])
            transit_min = float(rt["safe"]["eta_min"])
            total_eta = round(MOBILIZE_MIN + transit_min + (SAFETY_MIN if inter else 0.0), 1)
            rank_key = (1 if inter else 0, total_eta, u.unit_id)
            if best is None or rank_key < best[0]:
                best = (rank_key, u, rt, total_eta)

        # Fallback: if none of the top-K nearest origins were reachable, check the rest
        if best is None and deferred:
            for u in deferred:
                orig = u.current_node_id
                if orig not in route_by_origin:
                    route_by_origin[orig] = route_nodes(
                        reg,
                        orig,
                        target_node,
                        depths_by_catchment,
                        vehicle=vehicle,
                        closed_barriers=closed_barriers,
                        scenario_key=scenario_key,
                        allow_terminal_staging=True,
                    )
                rt = route_by_origin[orig]
                if not rt["reachable"]:
                    continue
                inter = bool(rt["inter_catchment"])
                transit_min = float(rt["safe"]["eta_min"])
                total_eta = round(MOBILIZE_MIN + transit_min + (SAFETY_MIN if inter else 0.0), 1)
                rank_key = (1 if inter else 0, total_eta, u.unit_id)
                if best is None or rank_key < best[0]:
                    best = (rank_key, u, rt, total_eta)

    _eval_pool(local_units)
    if best is None or best[0][0] == 1:
        _eval_pool(remote_units)

    if best is None:
        return {
            "feasible": False,
            "infeasible_reason": "flood_blocked",
            "message": (
                f"No flood-safe {vehicle} corridor reaches {alert['name']} "
                f"(depth {alert['depth_m']:.2f}m blocks all access)."
            ),
            "unit": None,
            "eta_min": None,
            "added_minutes": None,
            "inter_catchment": False,
            "route": None,
            "when_directive": _format_when_directive(
                uclass, False, None, ttp_min, total_class_count=len(class_units)
            ),
        }

    _, chosen_u, chosen_rt, total_eta = best
    added_vs_std = chosen_rt.get("added_vs_standard_min") or 0.0
    delta = round(float(added_vs_std), 1)
    return {
        "feasible": True,
        "infeasible_reason": None,
        "message": None,
        "unit": chosen_u,
        "eta_min": total_eta,
        # `added_minutes` is the *extra* time attributable to the flood-safe
        # detour. A flood-aware graph can legitimately be faster than the naive
        # one (it avoids a deeper-water edge), which is why the signed value is
        # reported separately as `delta_vs_naive_min` instead of a negative
        # "added" time.
        "added_minutes": round(max(0.0, delta), 1),
        "delta_vs_naive_min": delta,
        "inter_catchment": bool(chosen_rt["inter_catchment"]),
        "route": chosen_rt,
        "when_directive": _format_when_directive(
            uclass, True, total_eta, ttp_min, total_class_count=len(class_units)
        ),
    }


def _no_unit_refusal(
    uclass: str,
    class_units: List[FleetUnit],
    ttp_min: float,
    prefix: str,
) -> dict:
    busy = [u for u in class_units if u.state not in ("IDLE", "STANDBY")]
    if busy:
        earliest = min(busy, key=lambda u: u.remaining_min)
        free_in = round(float(earliest.remaining_min), 1)
        msg = (
            f"{prefix} Nearest busy unit {earliest.unit_id} frees in "
            f"{free_in:.0f}m; peak flood is in {ttp_min:.0f}m."
        )
    elif not class_units:
        free_in = None
        msg = (
            f"0 {uclass}s configured in session fleet (Setup inventory exhausted). "
            f"Peak flood is in {ttp_min:.0f}m."
        )
    else:
        free_in = None
        msg = f"{prefix} Peak flood is in {ttp_min:.0f}m."

    return {
        "feasible": False,
        "infeasible_reason": "no_unit",
        "message": msg,
        "unit": None,
        "eta_min": None,
        "added_minutes": None,
        "inter_catchment": False,
        "route": None,
        "when_directive": _format_when_directive(
            uclass, False, None, ttp_min, free_in_min=free_in, total_class_count=len(class_units)
        ),
    }


def enrich_alerts_with_fleet(
    reg: CommandRegistry,
    alerts: List[dict],
    units: List[FleetUnit],
    dismissed: Dict[str, dict],
    depths_by_catchment: Dict[str, np.ndarray],
    scenario_key: str,
    sim_clock_min: float,
) -> List[dict]:
    """Attach live assignment state OR simulated greedy next-unit preview to each alert."""
    closed_bars = closed_barrier_nodes(units)
    has_pending_close = any(u.state == "PENDING_CLOSE" for u in units)
    cache_key = (
        scenario_key,
        tuple((str(a.get("alert_id")), round(float(a.get("depth_m", 0.0)), 4)) for a in alerts),
        closed_bars,
        tuple(sorted((k, v.get("reason"), v.get("sim_ts")) for k, v in dismissed.items())),
        tuple(
            (u.unit_id, u.state, u.current_node_id, u.assigned_alert_id, round(u.veto_deadline_min, 2))
            for u in units
        ),
        round(sim_clock_min, 2) if has_pending_close else 0.0,
    )
    with _ENRICH_LOCK:
        hit = _ENRICH_CACHE.get(cache_key)
        if hit is not None:
            _ENRICH_CACHE.move_to_end(cache_key)
            return [dict(item) for item in hit]

    active_by_alert: Dict[str, FleetUnit] = {
        u.assigned_alert_id: u
        for u in units
        if u.assigned_alert_id is not None and u.state not in ("IDLE", "STANDBY")
    }
    reserved_ids: set[str] = {u.unit_id for u in active_by_alert.values()}

    enriched: List[dict] = []
    for raw in alerts:
        a = dict(raw)
        aid = a["alert_id"]
        a["deploy_where"] = f"{a['name']} ({a['catchment'].upper()})"
        a["deploy_what"] = f"{a['action_label']} · {UNIT_SPECS.get(a['unit_class'], a['unit_class'])}"

        if aid in dismissed:
            dinfo = dismissed[aid]
            a.update(
                {
                    "dispatch_status": "DISMISSED",
                    "dismiss_reason": dinfo.get("reason"),
                    "unit": None,
                    "depot": None,
                    "eta_min": None,
                    "addedMinutes": 0.0,
                    "delta_vs_naive_min": None,
                    "safe_shorter_than_naive": False,
                    "delta_basis": "n/a",
                    "feasible": False,
                    "infeasible_reason": "dismissed",
                    "infeasible_message": f"Dismissed ({dinfo.get('reason')})",
                    "deploy_when": f"Dismissed at {dinfo.get('sim_ts', 'T+000m')}",
                    "inter_catchment": False,
                    "veto_remaining_sec": 0.0,
                }
            )
            enriched.append(a)
            continue

        assigned = active_by_alert.get(aid)
        if assigned is not None:
            veto_s = (
                max(0.0, (assigned.veto_deadline_min - sim_clock_min) * 60.0)
                if assigned.state == "PENDING_CLOSE"
                else 0.0
            )
            active_delta = (
                (assigned.active_route or {}).get("added_vs_standard_min") or 0.0
            )
            a.update(
                {
                    "dispatch_status": "ASSIGNED",
                    "unit_state": assigned.state,
                    "unit": assigned.unit_id,
                    "depot": assigned.depot_name,
                    "eta_min": round(assigned.eta_min, 1),
                    "remaining_min": round(assigned.remaining_min, 1),
                    "addedMinutes": round(max(0.0, float(active_delta)), 1),
                    "delta_vs_naive_min": round(float(active_delta), 1),
                    "safe_shorter_than_naive": bool(float(active_delta) < 0),
                    "delta_basis": "flood_naive",
                    "feasible": True,
                    "infeasible_reason": None,
                    "infeasible_message": None,
                    "deploy_when": (
                        f"{assigned.state} · {assigned.remaining_min:.0f}m remaining"
                        if assigned.remaining_min > 0
                        else assigned.state
                    ),
                    "beats_peak": bool(assigned.eta_min <= float(a.get("ttp_min", 0.0) or 0.0)),
                    "inter_catchment": assigned.inter_catchment,
                    "veto_remaining_sec": round(veto_s, 1),
                    "route": assigned.active_route,
                }
            )
            enriched.append(a)
            continue

        # Simulated greedy preview so pool limits reflect across top-K directives honestly
        cand = _best_candidate_for_alert(
            reg,
            a,
            units,
            reserved_ids,
            depths_by_catchment,
            closed_bars,
            scenario_key,
        )
        if cand["feasible"] and cand["unit"] is not None:
            u = cand["unit"]
            reserved_ids.add(u.unit_id)
            a.update(
                {
                    "dispatch_status": "PENDING",
                    "unit_state": "RECOMMENDED",
                    "unit": u.unit_id,
                    "depot": u.depot_name,
                    "eta_min": cand["eta_min"],
                    "addedMinutes": cand["added_minutes"],
                    "delta_vs_naive_min": cand.get("delta_vs_naive_min"),
                    "feasible": True,
                    "infeasible_reason": None,
                    "infeasible_message": None,
                    "deploy_when": cand["when_directive"],
                    "beats_peak": bool(
                        cand["eta_min"] is not None
                        and cand["eta_min"] <= float(a.get("ttp_min", 0.0) or 0.0)
                    ),
                    "inter_catchment": cand["inter_catchment"],
                    "veto_remaining_sec": 0.0,
                    "route": cand.get("route"),
                    "delta_basis": "flood_naive",
                    "safe_shorter_than_naive": bool(
                        (cand.get("delta_vs_naive_min") or 0.0) < 0
                    ),
                }
            )
        else:
            a.update(
                {
                    "dispatch_status": "INFEASIBLE",
                    "unit_state": "NONE",
                    "unit": None,
                    "depot": None,
                    "eta_min": None,
                    "addedMinutes": 0.0,
                    "delta_vs_naive_min": None,
                    "safe_shorter_than_naive": False,
                    "delta_basis": "n/a",
                    "feasible": False,
                    "infeasible_reason": cand["infeasible_reason"],
                    "infeasible_message": cand["message"],
                    "deploy_when": cand["when_directive"],
                    "beats_peak": None,
                    "inter_catchment": False,
                    "veto_remaining_sec": 0.0,
                    "route": None,
                }
            )
        enriched.append(a)

    with _ENRICH_LOCK:
        _ENRICH_CACHE[cache_key] = [dict(item) for item in enriched]
        _ENRICH_CACHE.move_to_end(cache_key)
        while len(_ENRICH_CACHE) > _MAX_ENRICH_CACHE:
            _ENRICH_CACHE.popitem(last=False)
    return enriched


def dispatch_alert(
    reg: CommandRegistry,
    alert: dict,
    units: List[FleetUnit],
    dismissed: Dict[str, dict],
    depths_by_catchment: Dict[str, np.ndarray],
    scenario_key: str,
    sim_clock_min: float,
    preferred_unit_id: Optional[str] = None,
) -> dict:
    """Assign an IDLE fleet unit to an alert, locking state cleanly."""
    aid = alert["alert_id"]
    if aid in dismissed:
        return {"ok": False, "status_code": 409, "reason": "already_dismissed", "message": f"Alert {aid} already dismissed."}

    existing = next(
        (u for u in units if u.assigned_alert_id == aid and u.state not in ("IDLE", "STANDBY")),
        None,
    )
    if existing is not None:
        return {
            "ok": False,
            "status_code": 409,
            "reason": "already_dispatched",
            "message": f"Alert {aid} is already covered by {existing.unit_id} ({existing.state}).",
        }

    closed_bars = closed_barrier_nodes(units)
    if preferred_unit_id:
        match = [
            u for u in units
            if u.unit_id == preferred_unit_id and u.state == "IDLE" and u.unit_class == alert["unit_class"]
        ]
        if not match:
            return {
                "ok": False,
                "status_code": 409,
                "reason": "unit_unavailable",
                "message": f"Requested unit {preferred_unit_id} is not IDLE for class {alert['unit_class']}.",
            }
        cand = _best_candidate_for_alert(
            reg, alert, match, set(), depths_by_catchment, closed_bars, scenario_key
        )
    else:
        cand = _best_candidate_for_alert(
            reg, alert, units, set(), depths_by_catchment, closed_bars, scenario_key
        )

    if not cand["feasible"] or cand["unit"] is None:
        return {
            "ok": False,
            "status_code": 200,
            "feasible": False,
            "reason": cand["infeasible_reason"],
            "message": cand["message"],
            "alert_id": aid,
        }

    u: FleetUnit = cand["unit"]
    u.assigned_alert_id = aid
    u.target_node_id = str(alert["id"])
    u.target_name = str(alert["name"])
    u.target_catchment = str(alert["catchment"])
    u.inter_catchment = bool(cand["inter_catchment"])
    u.active_route = cand["route"]

    if u.unit_class == "barrier":
        u.state = "PENDING_CLOSE"
        u.eta_min = 0.0
        u.remaining_min = BARRIER_VETO_WINDOW_MIN
        u.veto_deadline_min = sim_clock_min + BARRIER_VETO_WINDOW_MIN
        u.site_duration_min = 0.0
        action_name = "BARRIER_PENDING_CLOSE"
    else:
        eta = float(cand["eta_min"])
        u.state = "EN_ROUTE"
        u.eta_min = eta
        u.remaining_min = eta
        u.return_eta_min = round(max(5.0, eta * 0.7), 1)
        u.site_duration_min = (
            _compute_dewatering_min(float(alert["depth_m"]))
            if u.unit_class == "pump"
            else WARDEN_ON_SITE_MIN
        )
        action_name = "DISPATCH_APPROVED"

    return {
        "ok": True,
        "feasible": True,
        "action": action_name,
        "alert_id": aid,
        "unit": u.to_dict(sim_clock_min),
        "eta_min": u.eta_min,
        "inter_catchment": u.inter_catchment,
        "route": cand["route"],
    }


def veto_barrier(units: List[FleetUnit], unit_id: str, sim_clock_min: float) -> dict:
    """Cancel a PENDING_CLOSE barrier inside the 60 s operator veto window."""
    u = next((x for x in units if x.unit_id == unit_id and x.unit_class == "barrier"), None)
    if u is None:
        return {"ok": False, "status_code": 404, "reason": "unknown_barrier", "message": f"Barrier {unit_id} not found."}
    if u.state != "PENDING_CLOSE":
        return {
            "ok": False,
            "status_code": 409,
            "reason": "veto_not_pending",
            "message": f"Barrier {unit_id} is in state {u.state}; only PENDING_CLOSE can be vetoed.",
        }
    if sim_clock_min > u.veto_deadline_min + 1e-6:
        return {
            "ok": False,
            "status_code": 409,
            "reason": "veto_window_expired",
            "message": f"60 s veto window expired for {unit_id}.",
        }
    prev_alert = u.assigned_alert_id
    u.state = "STANDBY"
    u.assigned_alert_id = None
    u.target_node_id = None
    u.target_name = None
    u.remaining_min = 0.0
    u.veto_deadline_min = 0.0
    return {
        "ok": True,
        "unit": u.to_dict(sim_clock_min),
        "released_alert_id": prev_alert,
    }


def reopen_barrier(units: List[FleetUnit], unit_id: str, sim_clock_min: float) -> dict:
    """Operator re-opens a CLOSED barrier once the underpass is passable again.

    Without this the barrier state machine is a dead end: a closure locks the
    junction for the rest of the session and no recovery is possible in the UI.
    """
    u = next((x for x in units if x.unit_id == unit_id and x.unit_class == "barrier"), None)
    if u is None:
        return {
            "ok": False,
            "status_code": 404,
            "reason": "unknown_barrier",
            "message": f"Barrier {unit_id} not found.",
        }
    if u.state != "CLOSED":
        return {
            "ok": False,
            "status_code": 409,
            "reason": "not_closed",
            "message": f"Barrier {unit_id} is {u.state}; only CLOSED barriers can be re-opened.",
        }
    prev_alert = u.assigned_alert_id
    prev_target = u.target_node_id or u.home_node_id
    u.state = "STANDBY"
    u.assigned_alert_id = None
    u.target_node_id = None
    u.target_name = None
    u.target_catchment = None
    u.remaining_min = 0.0
    u.veto_deadline_min = 0.0
    u.active_route = None
    return {
        "ok": True,
        "unit": u.to_dict(sim_clock_min),
        "released_alert_id": prev_alert,
        "reopened_node_id": prev_target,
    }


def advance_fleet_clock(
    units: List[FleetUnit],
    old_sim_min: float,
    minutes: float,
) -> List[dict]:
    """Advance simulation clock by `minutes`, returning state-transition event records."""
    new_sim_min = old_sim_min + minutes
    events: List[dict] = []

    for u in units:
        if u.state in ("IDLE", "STANDBY", "CLOSED"):
            continue
        dt_left = float(minutes)
        while dt_left > 1e-6 and u.state not in ("IDLE", "STANDBY", "CLOSED"):
            if dt_left + 1e-6 < u.remaining_min:
                u.remaining_min = round(u.remaining_min - dt_left, 2)
                dt_left = 0.0
                break

            # Complete current phase at phase_end_min
            step_consumed = max(0.0, u.remaining_min)
            dt_left -= step_consumed
            u.remaining_min = 0.0
            prev = u.state

            if prev == "PENDING_CLOSE":
                u.state = "CLOSED"
                events.append(
                    {
                        "unit_id": u.unit_id,
                        "action": "BARRIER_LOCKED",
                        "alert_id": u.assigned_alert_id,
                        "msg": f"{u.unit_id} locked closed at {u.target_name or u.depot_name}",
                    }
                )
            elif prev == "EN_ROUTE":
                u.current_node_id = u.target_node_id or u.current_node_id
                u.current_catchment = u.target_catchment or u.current_catchment
                u.state = "DEWATERING" if u.unit_class == "pump" else "ON_SITE"
                u.remaining_min = u.site_duration_min
                events.append(
                    {
                        "unit_id": u.unit_id,
                        "action": "UNIT_ARRIVED",
                        "alert_id": u.assigned_alert_id,
                        "msg": f"{u.unit_id} arrived on site -> {u.state} ({u.remaining_min:.0f}m)",
                    }
                )
            elif prev in ("DEWATERING", "ON_SITE"):
                u.state = "RETURNING"
                u.remaining_min = u.return_eta_min
                events.append(
                    {
                        "unit_id": u.unit_id,
                        "action": "SITE_COMPLETE",
                        "alert_id": u.assigned_alert_id,
                        "msg": f"{u.unit_id} completed site task -> RETURNING ({u.remaining_min:.0f}m)",
                    }
                )
            elif prev == "RETURNING":
                released_alert = u.assigned_alert_id
                u.state = "IDLE"
                u.current_node_id = u.home_node_id
                u.current_catchment = u.home_catchment
                u.assigned_alert_id = None
                u.target_node_id = None
                u.target_name = None
                u.target_catchment = None
                u.active_route = None
                events.append(
                    {
                        "unit_id": u.unit_id,
                        "action": "UNIT_RETURNED_IDLE",
                        "alert_id": released_alert,
                        "msg": f"{u.unit_id} back at {u.depot_name} -> IDLE",
                    }
                )

    return events


def fleet_summary(units: List[FleetUnit], sim_clock_min: float) -> dict:
    """Compute live KPI inventory counts across pump, barrier, and warden pools."""
    out: Dict[str, dict] = {}
    for cls in ("pump", "barrier", "warden"):
        sub = [u for u in units if u.unit_class == cls]
        out[cls] = {
            "total": len(sub),
            "idle": sum(1 for u in sub if u.state == "IDLE"),
            "active": sum(1 for u in sub if u.state not in ("IDLE", "STANDBY")),
            "standby": sum(1 for u in sub if u.state == "STANDBY"),
        }
    return {
        "counts": out,
        "units": [u.to_dict(sim_clock_min) for u in units],
        "fleet_oversized": out["pump"]["total"] > 18,
    }
