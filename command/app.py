"""Standalone Flask API server for UrbanFLOW Municipal Flood Command & Dispatch.

Run directly from repository root:
  python -m command.app

Never imports or modifies frozen `app.py`, `core/`, `docs/`, or `paper/`.
"""
from __future__ import annotations

import gzip
import json as _json
import math
import os
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from command.audit import AuditLogger
from command.config import (
    ASSET_WEIGHT,
    CATCHMENTS,
    DEFAULT_FLEET,
    DURATION_CLAMP,
    FLEET_LIMITS,
    RAINFALL_CLAMP,
    EVAL_DIR,
    STATIC_COMMAND_DIR,
    THRESHOLDS,
    TRIAGE_WEIGHTS,
    UI_DURATION_RANGE,
    UI_RAINFALL_RANGE,
    VEHICLE_PROFILES,
    VERSION,
)
from command.fleet import (
    advance_fleet_clock,
    closed_barrier_nodes,
    dispatch_alert,
    enrich_alerts_with_fleet,
    fleet_summary,
    reopen_barrier,
    veto_barrier,
)
from command.loader import CommandRegistry, get_registry
from command.routing import resolve_endpoint, route_nodes
from command.scenarios import SCENARIO_PRESETS
from command.schemas import (
    ValidationError,
    validate_dismiss_reason,
    validate_float,
    validate_mode,
    validate_region,
    validate_session_payload,
    validate_vehicle,
)
from command.state import CommandSession, SessionStore, get_session_store
from command.transit import evaluate_transit_corridors
from command.triage import infer_catchment, inspect_single_node, triage_scenario


def _build_bootstrap_roads(reg: CommandRegistry) -> list[dict]:
    roads: list[dict] = []
    for r_key, c in reg.catchments.items():
        for e in c.edges:
            roads.append(
                {
                    "id": e.eid,
                    "path": e.coords,
                    "highway": e.highway,
                    "catchment": r_key,
                    "length_m": e.length_m,
                }
            )
    return roads


def create_app(
    *,
    audit_dir: Optional[str] = None,
    load_model: bool = True,
    session_store: Optional[SessionStore] = None,
) -> Flask:
    """Build and configure the Flask Command & Dispatch WSGI application."""
    app = Flask(
        __name__,
        static_folder=os.path.dirname(STATIC_COMMAND_DIR),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 1 << 20
    reg = get_registry(load_model=load_model)
    app.config["REGISTRY"] = reg
    store = session_store or get_session_store()
    audit = AuditLogger(log_dir=audit_dir) if audit_dir else AuditLogger()
    bootstrap_payload = {
        "simulation": True,
        "version": VERSION,
        "catchments": {
            k: {
                "key": c.key,
                "short": c.short,
                "name": c.name,
                "centroid": list(c.centroid),
                "bounds": c.bounds,
                "nodes": len(c.node_ids),
                "edges": len(c.edges),
            }
            for k, c in reg.catchments.items()
        },
        "roads": _build_bootstrap_roads(reg),
        "pois": reg.all_pois,
        "depots": reg.depots,
        "presets": SCENARIO_PRESETS,
        "config": {
            "thresholds": THRESHOLDS,
            "triage_weights": TRIAGE_WEIGHTS,
            "asset_weights": ASSET_WEIGHT,
            "vehicle_profiles": VEHICLE_PROFILES,
            "fleet_limits": FLEET_LIMITS,
            "default_fleet": DEFAULT_FLEET,
            "ui_rainfall_range": UI_RAINFALL_RANGE,
            "ui_duration_range": UI_DURATION_RANGE,
        },
    }
    bootstrap_json_bytes = _json.dumps(bootstrap_payload, separators=(",", ":")).encode("utf-8")
    bootstrap_gz_bytes = gzip.compress(bootstrap_json_bytes, compresslevel=5)

    @app.after_request
    def _add_cors_and_gzip(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if (
            resp.status_code == 200
            and not resp.direct_passthrough
            and "Content-Encoding" not in resp.headers
            and "gzip" in request.headers.get("Accept-Encoding", "").lower()
            and resp.mimetype in (
                "application/json",
                "text/javascript",
                "application/javascript",
                "text/css",
                "text/html",
            )
        ):
            data = resp.get_data()
            if len(data) >= 1024:
                gz = gzip.compress(data, compresslevel=5)
                resp.set_data(gz)
                resp.headers["Content-Encoding"] = "gzip"
                resp.headers["Content-Length"] = str(len(gz))
                resp.headers["Vary"] = "Accept-Encoding"
        return resp

    @app.errorhandler(ValidationError)
    def _handle_validation(err: ValidationError):
        return jsonify(err.to_dict()), 400

    @app.errorhandler(400)
    def _handle_400(err):
        return jsonify({"error": "bad_request", "message": getattr(err, "description", "Bad request")}), 400

    @app.errorhandler(404)
    def _handle_404(err):
        return jsonify({"error": "not_found", "message": getattr(err, "description", "Not found")}), 404

    @app.errorhandler(405)
    def _handle_405(err):
        return jsonify({"error": "method_not_allowed", "message": "Method not allowed for this endpoint"}), 405

    @app.errorhandler(HTTPException)
    def _handle_http(err: HTTPException):
        code = err.code or 500
        if code >= 500:
            app.logger.exception("http error %s: %s", code, err)
        return jsonify({"error": "http_error", "message": err.description, "status": code}), code

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        # The API must never answer a client with an HTML traceback or internal detail.
        import uuid as _uuid

        cid = _uuid.uuid4().hex[:8]
        app.logger.exception("unhandled API error [%s]: %s", cid, err)
        return (
            jsonify(
                {
                    "error": "internal_error",
                    "message": "Internal server error",
                    "correlation_id": cid,
                }
            ),
            500,
        )

    def _require_session(sid: Optional[str]) -> tuple[Optional[CommandSession], Any]:
        if not sid:
            return None, (jsonify({"error": "missing_session_id", "message": "session_id is required"}), 400)
        sess = store.get(str(sid))
        if sess is None:
            if store.is_evicted(str(sid)):
                return None, (
                    jsonify(
                        {
                            "error": "session_expired",
                            "session_evicted": True,
                            "message": f"Session {sid} expired due to capacity limit",
                        }
                    ),
                    410,
                )
            return None, (jsonify({"error": "session_not_found", "message": f"Unknown session {sid}"}), 404)
        return sess, None

    def _get_json_body() -> dict:
        body = request.get_json(silent=True)
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise ValidationError("body", "JSON body must be an object")
        return body

    @app.route("/", methods=["GET"])
    @app.route("/static/command/", methods=["GET"])
    def serve_command_index():
        index_path = os.path.join(STATIC_COMMAND_DIR, "index.html")
        if os.path.exists(index_path):
            return send_from_directory(STATIC_COMMAND_DIR, "index.html")
        return jsonify(
            {
                "status": "api_only",
                "message": "Frontend not built yet. Run `cd web && npm run build`.",
            }
        )

    @app.route("/static/command/<path:filename>", methods=["GET"])
    def serve_command_asset(filename: str):
        return send_from_directory(STATIC_COMMAND_DIR, filename)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "status": "ok",
                "version": VERSION,
                "simulation": True,
                "total_nodes": reg.total_nodes(),
                "total_edges": reg.total_edges(),
                "catchments": {
                    k: {"nodes": len(c.node_ids), "edges": len(c.edges), "short": c.short}
                    for k, c in reg.catchments.items()
                },
                "predictor_loaded": reg.predictor is not None,
                "load_sec": reg.load_sec,
                "active_sessions": store.count(),
            }
        )

    @app.route("/api/v1/bootstrap", methods=["GET"])
    def bootstrap():
        if "gzip" in request.headers.get("Accept-Encoding", "").lower():
            resp = Response(bootstrap_gz_bytes, status=200, mimetype="application/json")
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Content-Length"] = str(len(bootstrap_gz_bytes))
            resp.headers["Vary"] = "Accept-Encoding"
            return resp
        return Response(bootstrap_json_bytes, status=200, mimetype="application/json")

    @app.route("/api/v1/session", methods=["POST", "GET"])
    def session_endpoint():
        if request.method == "GET":
            sid = request.args.get("session_id")
            sess, err = _require_session(sid)
            if err:
                return err
            assert sess is not None
            with sess.lock:
                return jsonify(
                    {
                        "simulation": True,
                        "session_id": sess.session_id,
                        "operator": sess.operator,
                        "region": sess.region,
                        "rain_mmhr": sess.rain_mmhr,
                        "duration_min": sess.duration_min,
                        "mode": sess.mode,
                        "sim_clock_min": round(sess.sim_clock_min, 2),
                        "sim_ts": sess.sim_ts(),
                        "config_hash": sess.cfg_hash,
                        "fleet_config": sess.fleet_config,
                        "fleet": fleet_summary(sess.units, sess.sim_clock_min),
                    }
                )

        body = _get_json_body()
        validated = validate_session_payload(body)
        sess = store.create(reg, validated)
        f_sum = fleet_summary(sess.units, sess.sim_clock_min)
        entry = audit.append(
            session_id=sess.session_id,
            sim_ts=sess.sim_ts(),
            actor=sess.operator,
            action="SESSION_INIT",
            token="system",
            msg=(
                f"Session initialized: region={sess.region}, rain={sess.rain_mmhr:.0f}mm/hr, "
                f"fleet={sess.fleet_config['pumps']}P/{sess.fleet_config['barriers']}B/{sess.fleet_config['wardens']}W"
            ),
            cfg_hash=sess.cfg_hash,
            details={"fleet": sess.fleet_config, "fleet_oversized": f_sum["fleet_oversized"]},
        )
        return (
            jsonify(
                {
                    "simulation": True,
                    "session_id": sess.session_id,
                    "operator": sess.operator,
                    "region": sess.region,
                    "rain_mmhr": sess.rain_mmhr,
                    "duration_min": sess.duration_min,
                    "mode": sess.mode,
                    "sim_clock_min": sess.sim_clock_min,
                    "sim_ts": sess.sim_ts(),
                    "config_hash": sess.cfg_hash,
                    "fleet_config": sess.fleet_config,
                    "fleet": f_sum,
                    "log_entry": entry,
                }
            ),
            201,
        )

    @app.route("/api/v1/scenario", methods=["GET", "POST"])
    def scenario_endpoint():
        data = _get_json_body() if request.method == "POST" else dict(request.args)
        sid = data.get("session_id")
        sess: Optional[CommandSession] = None
        if sid:
            sess, err = _require_session(sid)
            if err:
                return err

        region = validate_region(data.get("region"), sess.region if sess else "all")
        raw_rain = data.get("rain_mmhr", data.get("rainfall_mmhr", data.get("rain")))
        rain = validate_float(
            raw_rain, "rain_mmhr", RAINFALL_CLAMP[0], RAINFALL_CLAMP[1], sess.rain_mmhr if sess else 45.0
        )
        raw_dur = data.get("duration_min", data.get("duration"))
        dur = validate_float(
            raw_dur, "duration_min", DURATION_CLAMP[0], DURATION_CLAMP[1], sess.duration_min if sess else 60.0
        )
        mode = validate_mode(data.get("mode"), sess.mode if sess else "normal")

        tri = triage_scenario(
            reg, region=region, rain_mmhr=rain, duration_min=dur, mode=mode
        )
        sc_key = f"{region}|{rain:.1f}|{dur:.1f}|{mode}"
        nodes_out = [dict(n) for n in tri["nodes"]]
        edges_out = dict(tri["edge_depths"])
        alerts_out = [dict(a) for a in tri["alerts"]]

        if sess is not None:
            with sess.lock:
                changed = (
                    sess.region != region
                    or abs(sess.rain_mmhr - rain) > 0.05
                    or abs(sess.duration_min - dur) > 0.05
                    or sess.mode != mode
                )
                sess.region = region
                sess.rain_mmhr = round(rain, 1)
                sess.duration_min = round(dur, 1)
                sess.mode = mode
                if sess.cleared_nodes:
                    # Apply operator feedback multipliers to a COPY of cached arrays & edges
                    for ck, c_depths in list(tri["depths_by_catchment"].items()):
                        c_obj = reg.catchments.get(ck)
                        if c_obj is None:
                            continue
                        updated = c_depths.copy() if hasattr(c_depths, "copy") else c_depths
                        touched_indices = set()
                        for nid, mult in sess.cleared_nodes.items():
                            idx = c_obj.node_idx.get(str(nid))
                            if idx is not None:
                                updated[idx] = float(updated[idx]) * mult
                                touched_indices.add(idx)
                        tri["depths_by_catchment"][ck] = updated
                        if touched_indices:
                            for e in c_obj.edges:
                                if e.u_idx in touched_indices or e.v_idx in touched_indices:
                                    ed = float(max(updated[e.u_idx], updated[e.v_idx]))
                                    if ed >= 0.02:
                                        edges_out[e.eid] = round(ed, 3)
                                    else:
                                        edges_out.pop(e.eid, None)
                    for n_item in nodes_out:
                        nid = str(n_item.get("id", ""))
                        if nid in sess.cleared_nodes:
                            n_item["depth_m"] = round(
                                float(n_item["depth_m"]) * sess.cleared_nodes[nid], 4
                            )
                            if n_item["depth_m"] < 0.02:
                                n_item["band"] = "dry"
                    for a_item in alerts_out:
                        nid = str(a_item.get("id", ""))
                        if nid in sess.cleared_nodes:
                            mult = sess.cleared_nodes[nid]
                            new_d = round(float(a_item["depth_m"]) * mult, 4)
                            a_item["depth_m"] = new_d
                            if new_d < 0.08:
                                a_item["band"] = "dry"
                            elif new_d < 0.25:
                                a_item["band"] = "watch"
                enriched = enrich_alerts_with_fleet(
                    reg,
                    alerts_out,
                    sess.units,
                    sess.dismissed,
                    tri["depths_by_catchment"],
                    sc_key,
                    sess.sim_clock_min,
                )
                closed_bars = closed_barrier_nodes(sess.units)
                f_sum = fleet_summary(sess.units, sess.sim_clock_min)
                sim_ts = sess.sim_ts()
                sim_clock = sess.sim_clock_min
                if changed:
                    audit.append(
                        session_id=sess.session_id,
                        sim_ts=sim_ts,
                        actor=sess.operator,
                        action="SCENARIO_UPDATE",
                        token="system",
                        msg=(
                            f"HydroGINE-v5 {region.upper()} {rain:.0f}mm/hr ({dur:.0f}m) [{mode.upper()}]: "
                            f"{len(enriched)} alerts ({tri['stats']['suppressed']} suppressed) in "
                            f"{tri['stats']['inference_latency_ms']:.1f}ms"
                        ),
                        cfg_hash=sess.cfg_hash,
                    )
        else:
            enriched = alerts_out
            closed_bars = frozenset()
            f_sum = None
            sim_ts = "T+000m"
            sim_clock = 0.0

        transit = evaluate_transit_corridors(
            reg,
            tri["depths_by_catchment"],
            closed_bars,
            scenario_key=sc_key,
            region=region,
        )

        # Compute mean ETA across feasible pending/assigned alerts
        etas = [a["eta_min"] for a in enriched if a.get("eta_min") is not None and a.get("feasible")]
        mean_eta = round(sum(etas) / len(etas), 1) if etas else 0.0

        return jsonify(
            {
                "simulation": True,
                "scenario_key": sc_key,
                "region": region,
                "rain_mmhr": round(rain, 1),
                "duration_min": round(dur, 1),
                "mode": mode,
                "sim_clock_min": round(sim_clock, 2),
                "sim_ts": sim_ts,
                "alerts": enriched,
                "nodes": nodes_out,
                "edge_depths": edges_out,
                "stats": {**tri["stats"], "mean_eta_min": mean_eta},
                "fleet": f_sum,
                "transit": transit,
            }
        )

    @app.route("/api/v1/node/<node_id>", methods=["GET"])
    def node_endpoint(node_id: str):
        sid = request.args.get("session_id")
        sess = store.get(sid) if sid else None
        rain = validate_float(
            request.args.get("rain_mmhr"),
            "rain_mmhr",
            RAINFALL_CLAMP[0],
            RAINFALL_CLAMP[1],
            sess.rain_mmhr if sess else 45.0,
        )
        dur = validate_float(
            request.args.get("duration_min"),
            "duration_min",
            DURATION_CLAMP[0],
            DURATION_CLAMP[1],
            sess.duration_min if sess else 60.0,
        )
        mode = validate_mode(request.args.get("mode"), sess.mode if sess else "normal")
        rec = inspect_single_node(reg, node_id, rain_mmhr=rain, duration_min=dur, mode=mode)
        if rec is None:
            return jsonify({"error": "unknown_node", "node_id": node_id}), 404
        barrier_locked = False
        if sess is not None:
            with sess.lock:
                barrier_locked = str(node_id) in closed_barrier_nodes(sess.units)
        rec["barrier_locked"] = barrier_locked
        return jsonify({"simulation": True, "node": rec})

    @app.route("/api/v1/dispatch", methods=["POST"])
    def dispatch_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        alert_id = str(body.get("alert_id") or "").strip()
        if not alert_id:
            raise ValidationError("alert_id", "must not be empty")
        preferred_unit = body.get("unit_id")

        with sess.lock:
            rain = sess.rain_mmhr
            dur = sess.duration_min
            mode = sess.mode
            # Always resolve alert across all catchments if node belongs to another catchment
            tri = triage_scenario(reg, region="all", rain_mmhr=rain, duration_min=dur, mode=mode)
            target_alert = next((a for a in tri["alerts"] if a["alert_id"] == alert_id), None)
            if target_alert is None:
                return jsonify({"error": "unknown_alert", "message": f"Alert {alert_id} not active in current storm"}), 404

            sc_key = f"all|{rain:.1f}|{dur:.1f}|{mode}"
            if not preferred_unit:
                enriched_preview = enrich_alerts_with_fleet(
                    reg,
                    tri["alerts"],
                    sess.units,
                    sess.dismissed,
                    tri["depths_by_catchment"],
                    sc_key,
                    sess.sim_clock_min,
                )
                preview_target = next((a for a in enriched_preview if a["alert_id"] == alert_id), None)
                if (
                    preview_target is not None
                    and preview_target.get("dispatch_status") == "INFEASIBLE"
                    and any(
                        u.unit_class == target_alert["unit_class"] and u.state == "IDLE"
                        for u in sess.units
                    )
                ):
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "reason": "unit_reserved",
                                "message": preview_target.get("infeasible_message")
                                or "All available units are reserved for higher-priority directives.",
                            }
                        ),
                        409,
                    )
            res = dispatch_alert(
                reg,
                target_alert,
                sess.units,
                sess.dismissed,
                tri["depths_by_catchment"],
                sc_key,
                sess.sim_clock_min,
                preferred_unit_id=str(preferred_unit) if preferred_unit else None,
            )

            if not res["ok"] and res.get("status_code", 200) != 200:
                return jsonify(res), res["status_code"]

            if not res["ok"]:
                entry = audit.append(
                    session_id=sess.session_id,
                    sim_ts=sess.sim_ts(),
                    actor=sess.operator,
                    action="DISPATCH_INFEASIBLE",
                    token="warn",
                    msg=f"{alert_id} ({target_alert['name']}): {res['message']}",
                    cfg_hash=sess.cfg_hash,
                    alert_id=alert_id,
                )
            else:
                u = res["unit"]
                msg = (
                    f"{u['unit_id']} dispatched from {u['depot_name']} -> {target_alert['name']} "
                    f"({target_alert['catchment'].upper()}, ETA {res['eta_min']:.1f}m)"
                )
                if res["inter_catchment"]:
                    msg += " [INTER-CATCHMENT +20m]"
                entry = audit.append(
                    session_id=sess.session_id,
                    sim_ts=sess.sim_ts(),
                    actor=sess.operator,
                    action=res["action"],
                    token="operator",
                    msg=msg,
                    cfg_hash=sess.cfg_hash,
                    alert_id=alert_id,
                    unit_id=u["unit_id"],
                    eta_min=res["eta_min"],
                    inter_catchment=res["inter_catchment"],
                )

            transit = evaluate_transit_corridors(
                reg,
                tri["depths_by_catchment"],
                closed_barrier_nodes(sess.units),
                scenario_key=sc_key,
                region=sess.region,
            )
            return jsonify(
                {
                    **res,
                    "fleet": fleet_summary(sess.units, sess.sim_clock_min),
                    "transit": transit,
                    "log_entry": entry,
                }
            )

    @app.route("/api/v1/dismiss", methods=["POST"])
    def dismiss_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        alert_id = str(body.get("alert_id") or "").strip()
        if not alert_id:
            raise ValidationError("alert_id", "must not be empty")
        reason = validate_dismiss_reason(body.get("reason"))

        with sess.lock:
            sess.dismissed[alert_id] = {"reason": reason, "sim_ts": sess.sim_ts()}
            node_id = str(body.get("node_id") or "").strip()
            if not node_id and "-" in alert_id:
                node_id = alert_id.rsplit("-", 1)[-1]
            raw_cluster = body.get("cluster_node_ids")
            cluster_ids = (
                [str(x).strip() for x in raw_cluster if str(x).strip()]
                if isinstance(raw_cluster, list)
                else []
            )
            target_ids = list(dict.fromkeys(([node_id] if node_id else []) + cluster_ids))
            mult = 0.5 if reason == "insufficient_confidence" else 0.0
            for tid in target_ids:
                sess.cleared_nodes[tid] = mult

            if reason == "false_alarm":
                summary = f"False alarm logged · Cleared {max(1, len(target_ids))} cluster junction(s) & re-routed corridors"
            elif reason == "already_handled":
                summary = f"Crew handled · Marked {max(1, len(target_ids))} junction(s) clear on flood & transit layers"
            else:
                summary = f"Confidence adjusted · Halved flood depth (0.5x) across {max(1, len(target_ids))} junction(s) & updated routes"

            entry = audit.append(
                session_id=sess.session_id,
                sim_ts=sess.sim_ts(),
                actor=sess.operator,
                action="ALERT_DISMISSED",
                token="operator",
                msg=f"Alert {alert_id} dismissed ({reason}); operator feedback applied to flood & routing state",
                cfg_hash=sess.cfg_hash,
                alert_id=alert_id,
                details={"reason": reason, "node_id": node_id, "calibrated_nodes": len(target_ids), "mult": mult},
            )
            return jsonify(
                {
                    "ok": True,
                    "alert_id": alert_id,
                    "reason": reason,
                    "node_id": node_id,
                    "calibration": {
                        "reason": reason,
                        "node_count": len(target_ids),
                        "depth_multiplier": mult,
                        "summary": summary,
                    },
                    "log_entry": entry,
                }
            )

    @app.route("/api/v1/veto", methods=["POST"])
    def veto_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        unit_id = str(body.get("unit_id") or body.get("barrier_id") or "").strip()
        if not unit_id:
            raise ValidationError("unit_id", "must not be empty")

        with sess.lock:
            res = veto_barrier(sess.units, unit_id, sess.sim_clock_min)
            if not res["ok"]:
                return jsonify(res), res.get("status_code", 409)
            entry = audit.append(
                session_id=sess.session_id,
                sim_ts=sess.sim_ts(),
                actor=sess.operator,
                action="BARRIER_VETOED",
                token="operator",
                msg=f"Operator vetoed closure of {unit_id} inside 60s window -> STANDBY",
                cfg_hash=sess.cfg_hash,
                alert_id=res.get("released_alert_id"),
                unit_id=unit_id,
            )
            return jsonify(
                {
                    **res,
                    "fleet": fleet_summary(sess.units, sess.sim_clock_min),
                    "log_entry": entry,
                }
            )

    @app.route("/api/v1/reopen", methods=["POST"])
    def reopen_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        unit_id = str(body.get("unit_id") or body.get("barrier_id") or "").strip()
        if not unit_id:
            raise ValidationError("unit_id", "must not be empty")

        with sess.lock:
            res = reopen_barrier(sess.units, unit_id, sess.sim_clock_min)
            if not res["ok"]:
                return jsonify(res), res.get("status_code", 409)
            entry = audit.append(
                session_id=sess.session_id,
                sim_ts=sess.sim_ts(),
                actor=sess.operator,
                action="BARRIER_REOPENED",
                token="operator",
                msg=f"Operator re-opened {unit_id} after water receded -> STANDBY",
                cfg_hash=sess.cfg_hash,
                alert_id=res.get("released_alert_id"),
                unit_id=unit_id,
            )
            return jsonify(
                {
                    **res,
                    "fleet": fleet_summary(sess.units, sess.sim_clock_min),
                    "log_entry": entry,
                }
            )

    @app.route("/api/v1/mode", methods=["POST"])
    def mode_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        new_mode = validate_mode(body.get("mode"))
        with sess.lock:
            prev = sess.mode
            sess.mode = new_mode
            entry = audit.append(
                session_id=sess.session_id,
                sim_ts=sess.sim_ts(),
                actor=sess.operator,
                action="MODE_CHANGED",
                token="system",
                msg=f"Threshold ladder switched {prev.upper()} -> {new_mode.upper()}",
                cfg_hash=sess.cfg_hash,
                details={"prev": prev, "mode": new_mode, "thresholds": THRESHOLDS[new_mode]},
            )
            return jsonify(
                {
                    "ok": True,
                    "mode": new_mode,
                    "thresholds": THRESHOLDS[new_mode],
                    "log_entry": entry,
                }
            )

    @app.route("/api/v1/tick", methods=["POST"])
    def tick_endpoint():
        body = _get_json_body()
        sess, err = _require_session(body.get("session_id"))
        if err:
            return err
        assert sess is not None
        raw_minutes = body.get("minutes", 5.0)
        if isinstance(raw_minutes, bool):
            raise ValidationError("minutes", "must be a number, not bool")
        minutes = validate_float(raw_minutes, "minutes", 0.1, 180.0, 5.0)
        with sess.lock:
            old_clock = sess.sim_clock_min
            events = advance_fleet_clock(sess.units, old_clock, minutes)
            sess.sim_clock_min = round(old_clock + minutes, 2)
            logs = []
            for ev in events:
                logs.append(
                    audit.append(
                        session_id=sess.session_id,
                        sim_ts=sess.sim_ts(),
                        actor="sim-clock",
                        action=ev["action"],
                        token="system",
                        msg=ev["msg"],
                        cfg_hash=sess.cfg_hash,
                        alert_id=ev.get("alert_id"),
                        unit_id=ev.get("unit_id"),
                    )
                )
            tri = triage_scenario(
                reg, region=sess.region, rain_mmhr=sess.rain_mmhr, duration_min=sess.duration_min, mode=sess.mode
            )
            sc_key = f"{sess.region}|{sess.rain_mmhr:.1f}|{sess.duration_min:.1f}|{sess.mode}"
            transit = evaluate_transit_corridors(
                reg,
                tri["depths_by_catchment"],
                closed_barrier_nodes(sess.units),
                scenario_key=sc_key,
                region=sess.region,
            )
            return jsonify(
                {
                    "ok": True,
                    "simulation": True,
                    "sim_clock_min": sess.sim_clock_min,
                    "sim_ts": sess.sim_ts(),
                    "events": events,
                    "log_entries": logs,
                    "fleet": fleet_summary(sess.units, sess.sim_clock_min),
                    "transit": transit,
                }
            )

    @app.route("/api/v1/route", methods=["GET", "POST"])
    def route_endpoint():
        data = _get_json_body() if request.method == "POST" else dict(request.args)
        sid = data.get("session_id")
        sess = store.get(sid) if sid else None

        def _coord(key: str) -> Optional[float]:
            raw = data.get(key)
            if raw is None or str(raw).strip() == "":
                return None
            try:
                val = float(raw)
            except (TypeError, ValueError):
                raise ValidationError(key, "must be a number")
            if not math.isfinite(val):
                raise ValidationError(key, "must be a finite number")
            limit = 90.0 if key.endswith("lat") else 180.0
            if abs(val) > limit:
                raise ValidationError(key, f"must be within +/-{limit:.0f}")
            return val

        orig_spec = data.get("origin") or data.get("origin_node")
        dest_spec = data.get("dest") or data.get("dest_node")
        if orig_spec is None or dest_spec is None:
            # Support flat origin_lat/origin_lng query params too
            if "origin_lat" in data or "origin_lng" in data:
                o_lat, o_lng = _coord("origin_lat"), _coord("origin_lng")
                if o_lat is None or o_lng is None:
                    raise ValidationError("origin_lat/origin_lng", "both coordinates are required")
                orig_spec = {"lat": o_lat, "lng": o_lng}
            if "dest_lat" in data or "dest_lng" in data:
                d_lat, d_lng = _coord("dest_lat"), _coord("dest_lng")
                if d_lat is None or d_lng is None:
                    raise ValidationError("dest_lat/dest_lng", "both coordinates are required")
                dest_spec = {"lat": d_lat, "lng": d_lng}
        if orig_spec is None or dest_spec is None:
            raise ValidationError("origin/dest", "must supply origin and dest node_id or {lat, lng}")

        vehicle = validate_vehicle(data.get("vehicle"), "pump_truck")
        region_hint = data.get("region") if data.get("region") in CATCHMENTS else None

        o_res = resolve_endpoint(reg, orig_spec, region_hint=region_hint)
        d_res = resolve_endpoint(reg, dest_spec, region_hint=region_hint)
        if o_res is None:
            return jsonify({"error": "origin_not_found", "message": "Could not resolve or snap origin"}), 404
        if d_res is None:
            return jsonify({"error": "dest_not_found", "message": "Could not resolve or snap destination"}), 404

        orig_nid, o_snap_m = o_res
        dest_nid, d_snap_m = d_res

        rain = validate_float(
            data.get("rain_mmhr", data.get("rain")),
            "rain_mmhr",
            RAINFALL_CLAMP[0],
            RAINFALL_CLAMP[1],
            sess.rain_mmhr if sess else 45.0,
        )
        dur = validate_float(
            data.get("duration_min", data.get("duration")),
            "duration_min",
            DURATION_CLAMP[0],
            DURATION_CLAMP[1],
            sess.duration_min if sess else 60.0,
        )

        # Infer only relevant catchment(s)
        c_o = reg.find_node(orig_nid)[0].key
        c_d = reg.find_node(dest_nid)[0].key
        depths_map = {}
        for ck in {c_o, c_d}:
            d_arr = infer_catchment(reg, reg.catchments[ck], rain, dur)["depths"].copy()
            if sess is not None and sess.cleared_nodes:
                c_obj = reg.catchments[ck]
                for nid, mult in sess.cleared_nodes.items():
                    idx = c_obj.node_idx.get(nid)
                    if idx is not None:
                        d_arr[idx] = float(d_arr[idx]) * mult
            depths_map[ck] = d_arr

        closed_bars = frozenset()
        mode = validate_mode(data.get("mode"), sess.mode if sess else "normal")
        if sess is not None:
            with sess.lock:
                closed_bars = closed_barrier_nodes(sess.units)

        sc_key = f"route|{rain:.1f}|{dur:.1f}|{mode}"
        rt = route_nodes(
            reg,
            orig_nid,
            dest_nid,
            depths_map,
            vehicle=vehicle,
            closed_barriers=closed_bars,
            scenario_key=sc_key,
            allow_terminal_staging=True,
            safety_margin_m=0.05 if mode == "red_alert" else 0.0,
            use_osrm=True,
        )
        rt["origin_snap_m"] = o_snap_m
        rt["dest_snap_m"] = d_snap_m
        rt["snapped_outside_80m"] = bool(o_snap_m > 80.0 or d_snap_m > 80.0)

        if sess is not None:
            with sess.lock:
                audit.append(
                    session_id=sess.session_id,
                    sim_ts=sess.sim_ts(),
                    actor=sess.operator,
                    action="CORRIDOR_ROUTED",
                    token="system",
                    msg=(
                        f"{vehicle} route {orig_nid[-5:]} -> {dest_nid[-5:]}: "
                        + (
                            f"safe {rt['safe']['eta_min']}m vs naive {rt['standard']['eta_min']}m"
                            if rt["reachable"]
                            else "IMPASSABLE (flood_blocked)"
                        )
                    ),
                    cfg_hash=sess.cfg_hash,
                    inter_catchment=rt["inter_catchment"],
                )

        return jsonify({"simulation": True, **rt})

    @app.route("/api/v1/transit", methods=["GET"])
    def transit_endpoint():
        sid = request.args.get("session_id")
        sess = store.get(sid) if sid else None
        region = validate_region(request.args.get("region"), sess.region if sess else "all")
        rain = validate_float(
            request.args.get("rain_mmhr", request.args.get("rain")),
            "rain_mmhr",
            RAINFALL_CLAMP[0],
            RAINFALL_CLAMP[1],
            sess.rain_mmhr if sess else 45.0,
        )
        dur = validate_float(
            request.args.get("duration_min"),
            "duration_min",
            DURATION_CLAMP[0],
            DURATION_CLAMP[1],
            sess.duration_min if sess else 60.0,
        )
        mode = validate_mode(request.args.get("mode"), sess.mode if sess else "normal")
        tri = triage_scenario(reg, region=region, rain_mmhr=rain, duration_min=dur, mode=mode)
        closed_bars = frozenset()
        if sess is not None:
            with sess.lock:
                closed_bars = closed_barrier_nodes(sess.units)
        sc_key = f"{region}|{rain:.1f}|{dur:.1f}|{mode}"
        tr = evaluate_transit_corridors(
            reg, tri["depths_by_catchment"], closed_bars, sc_key, region=region
        )
        return jsonify({"simulation": True, "region": region, "rain_mmhr": rain, **tr})

    @app.route("/api/v1/fleet", methods=["GET"])
    def fleet_endpoint():
        sess, err = _require_session(request.args.get("session_id"))
        if err:
            return err
        assert sess is not None
        with sess.lock:
            return jsonify(
                {
                    "simulation": True,
                    "session_id": sess.session_id,
                    "sim_clock_min": sess.sim_clock_min,
                    "sim_ts": sess.sim_ts(),
                    **fleet_summary(sess.units, sess.sim_clock_min),
                }
            )

    @app.route("/api/v1/log", methods=["GET"])
    def log_endpoint():
        sid = request.args.get("session_id")
        raw_since = request.args.get("since", "0")
        try:
            since = int(str(raw_since).strip() or "0")
        except (TypeError, ValueError):
            raise ValidationError("since", "must be an integer sequence number")
        if since < 0:
            raise ValidationError("since", "must be >= 0")
        events = audit.since(seq_after=since, session_id=sid)
        return jsonify(
            {"simulation": True, "latest_seq": audit.latest_seq, "events": events}
        )

    @app.route("/api/v1/evaluation", methods=["GET"])
    def evaluation_endpoint():
        json_path = os.path.join(EVAL_DIR, "baseline-comparison.json")
        if not os.path.exists(json_path):
            return jsonify({"ready": False, "message": "Run `python -m command.evaluate` first."})
        import json as _json

        with open(json_path, "r", encoding="utf-8") as f:
            payload = _json.load(f)
        return jsonify({"ready": True, **payload})

    return app


if __name__ == "__main__":
    import threading

    application = create_app()

    def _prewarm_osrm() -> None:
        try:
            reg = application.config.get("REGISTRY") or get_registry()
            for rain_val in (60.0, 85.0, 95.0):
                for mode_name in ("normal", "red_alert"):
                    tri = triage_scenario(
                        reg, region="all", rain_mmhr=rain_val, duration_min=60.0, mode=mode_name
                    )
                    evaluate_transit_corridors(
                        reg,
                        tri["depths_by_catchment"],
                        frozenset(),
                        f"all:{rain_val:.1f}:60.0:{mode_name}",
                        "all",
                    )
        except Exception as exc:
            application.logger.warning("prewarm failed: %s", exc)

    threading.Thread(target=_prewarm_osrm, daemon=True).start()
    application.run(host="0.0.0.0", port=8000, threaded=True, debug=False)
