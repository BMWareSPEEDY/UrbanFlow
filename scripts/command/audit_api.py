"""Adversarial audit harness for the UrbanFLOW Command API.

Not a unit-test replacement: this drives a *live* server and tries to break it
with malformed input, resource exhaustion, out-of-order calls and concurrency.
Every check prints PASS / FAIL / WARN with the observed value, so the output can
be pasted straight into an audit report.

    python -m scripts.command.audit_api --base http://127.0.0.1:8011
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import requests

RESULTS: list[dict[str, Any]] = []


def check(name: str, fn: Callable[[], tuple[str, str]]) -> None:
    """Run one check. fn returns (status, detail) where status in PASS/FAIL/WARN/SKIP."""
    t0 = time.perf_counter()
    try:
        status, detail = fn()
    except Exception:
        status, detail = "FAIL", "raised: " + traceback.format_exc(limit=2).replace("\n", " | ")
    ms = (time.perf_counter() - t0) * 1000
    RESULTS.append({"name": name, "status": status, "detail": detail, "ms": round(ms, 1)})
    mark = {"PASS": "\033[32mPASS\033[0m", "FAIL": "\033[31mFAIL\033[0m",
            "WARN": "\033[33mWARN\033[0m", "SKIP": "\033[90mSKIP\033[0m"}[status]
    print(f"  {mark}  {name:58} {detail}")


def expect(cond: bool, good: str, bad: str) -> tuple[str, str]:
    return ("PASS", good) if cond else ("FAIL", bad)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.s = requests.Session()

    def get(self, path: str, **kw) -> requests.Response:
        return self.s.get(self.base + path, timeout=120, **kw)

    def post(self, path: str, payload: Any = None, **kw) -> requests.Response:
        if payload is None:
            return self.s.post(self.base + path, timeout=120, **kw)
        return self.s.post(self.base + path, json=payload, timeout=120, **kw)

    def post_raw(self, path: str, body: str, ctype: str = "application/json") -> requests.Response:
        return self.s.post(self.base + path, data=body.encode(), headers={"Content-Type": ctype}, timeout=120)


def new_session(api: Api, **over) -> str:
    payload = {
        "operator": "audit-bot",
        "region": "all",
        "rain_mmhr": 95,
        "duration_min": 60,
        "mode": "red_alert",
        "fleet": {"pumps": 12, "barriers": 8, "wardens": 6},
    }
    payload.update(over)
    r = api.post("/api/v1/session", payload)
    assert r.status_code == 201, f"session create failed {r.status_code}: {r.text[:300]}"
    return r.json()["session_id"]


# --------------------------------------------------------------------------- #
def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def audit(base: str) -> int:
    api = Api(base)
    t_start = time.time()

    # ---------------------------------------------------------------- health
    section("A. Health, bootstrap and data parity")

    def _health():
        r = api.get("/health")
        j = r.json()
        ok = (
            r.status_code == 200
            and j["total_nodes"] == 12436
            and j["total_edges"] == 29717
            and len(j["catchments"]) == 5
            and j["predictor_loaded"] is True
        )
        return expect(ok, f"12,436 nodes / 29,717 edges, predictor loaded, load {j.get('load_sec')}s",
                      f"mismatch: {j}")

    check("health: five catchments, exact node/edge totals", _health)

    def _parity():
        h = api.get("/health").json()["catchments"]
        expect_map = {"hsr": 1379, "bellandur": 1507, "whitefield": 1797, "ecity": 3337, "koramangala": 4416}
        bad = {k: v["nodes"] for k, v in h.items() if v["nodes"] != expect_map[k]}
        return expect(not bad, "per-catchment counts match config", f"drift: {bad}")

    check("health: per-catchment node counts", _parity)

    def _bootstrap():
        r = api.get("/api/v1/bootstrap")
        j = r.json()
        roads = len(j.get("roads", []))
        ok = r.status_code == 200 and roads == 29717 and len(j.get("depots", [])) >= 5 and len(j.get("presets", {})) >= 1
        return expect(ok, f"{roads} road segments, {len(j.get('depots', []))} depots, "
                          f"{len(j.get('presets', {}))} presets", f"bad bootstrap: roads={roads}")

    check("bootstrap: geometry, depots, presets served", _bootstrap)

    def _bootstrap_size():
        r = api.get("/api/v1/bootstrap")
        mb = len(r.content) / 1e6
        return ("PASS" if mb < 40 else "WARN", f"{mb:.1f} MB payload")

    check("bootstrap: payload size sane", _bootstrap_size)

    # --------------------------------------------------------------- session
    section("B. Session creation and input validation")

    check("session: valid payload returns 201 + session_id",
          lambda: expect(api.post("/api/v1/session", {
              "operator": "audit", "region": "all", "rain_mmhr": 95, "duration_min": 60,
              "mode": "red_alert", "fleet": {"pumps": 12, "barriers": 8, "wardens": 6}
          }).status_code == 201, "201", "not 201"))

    def _defaults():
        r = api.post("/api/v1/session", {})
        j = r.json()
        ok = r.status_code == 201 and j["rain_mmhr"] == 45.0 and j["mode"] == "normal" and j["region"] == "all"
        return expect(ok, f"defaults applied: {j['rain_mmhr']} mm/hr, {j['mode']}, {j['region']}", f"{j}")

    check("session: empty body falls back to defaults", _defaults)

    bad_sessions = [
        ("region unknown", {"region": "atlantis"}, 400),
        ("mode unknown", {"mode": "turbo"}, 400),
        ("rain below clamp", {"rain_mmhr": 1}, 400),
        ("rain above clamp", {"rain_mmhr": 9999}, 400),
        ("rain not numeric", {"rain_mmhr": "heavy"}, 400),
        ("duration below clamp", {"duration_min": 1}, 400),
        ("duration above clamp", {"duration_min": 5000}, 400),
        ("pumps negative", {"fleet": {"pumps": -3}}, 400),
        ("pumps over max", {"fleet": {"pumps": 999}}, 400),
        ("pumps fractional", {"fleet": {"pumps": 3.5}}, 400),
        ("pumps as bool", {"fleet": {"pumps": True}}, 400),
        ("barriers over max", {"fleet": {"barriers": 99}}, 400),
    ]

    def make_bad(name: str, payload: dict, want: int):
        def _f():
            r = api.post("/api/v1/session", payload)
            return expect(r.status_code == want, f"{r.status_code} as expected",
                          f"wanted {want}, got {r.status_code}: {r.text[:120]}")
        return _f

    for name, payload, want in bad_sessions:
        check(f"session rejects: {name}", make_bad(name, payload, want))

    def _operator_long():
        r = api.post("/api/v1/session", {"operator": "x" * 5000})
        j = r.json()
        return expect(len(j["operator"]) <= 64, f"operator truncated to {len(j['operator'])} chars",
                      f"not truncated: {len(j['operator'])}")

    check("session: 5,000-char operator is truncated", _operator_long)

    def _operator_blank():
        r = api.post("/api/v1/session", {"operator": "   "})
        j = r.json()
        return expect(j["operator"] == "duty-officer", "blank operator -> default", f"got {j['operator']!r}")

    check("session: whitespace operator falls back", _operator_blank)

    def _bad_json():
        r = api.post_raw("/api/v1/session", "{not json at all")
        return ("PASS" if r.status_code in (200, 201, 400) else "WARN",
                f"{r.status_code} (silently defaulted)" if r.status_code == 201 else f"{r.status_code}")

    check("session: malformed JSON does not 500", _bad_json)

    def _json_array():
        r = api.post_raw("/api/v1/session", "[1,2,3]")
        return ("PASS" if r.status_code < 500 else "FAIL", f"{r.status_code}")

    check("session: JSON array body does not 500", _json_array)

    def _json_string():
        r = api.post_raw("/api/v1/session", '"hello"')
        return ("PASS" if r.status_code < 500 else "FAIL", f"{r.status_code} (500 = unhandled AttributeError)")

    check("session: JSON string body does not 500", _json_string)

    def _fleet_zero():
        r = api.post("/api/v1/session", {"fleet": {"pumps": 0, "barriers": 0, "wardens": 0}})
        j = r.json()
        ok = r.status_code == 201 and j["fleet_config"] == {"pumps": 0, "barriers": 0, "wardens": 0}
        return expect(ok, "zero fleet accepted (valid scenario)", f"{j.get('fleet_config')}")

    check("session: zero fleet is legal", _fleet_zero)

    def _total_units(fleet_payload: dict) -> int:
        return sum(v["total"] for v in fleet_payload["counts"].values())

    def _fleet_max():
        r = api.post("/api/v1/session", {"fleet": {"pumps": 30, "barriers": 24, "wardens": 24}})
        j = r.json()
        total = _total_units(j["fleet"])
        return expect(r.status_code == 201 and total == 78,
                      f"max fleet accepted, {total} units instantiated", f"{r.status_code}, total={total}")

    check("session: max fleet (30/24/24) is legal", _fleet_max)

    def _fleet_missing_subkey():
        r = api.post("/api/v1/session", {"fleet": {"pumps": 3}})
        j = r.json()
        ok = j["fleet_config"]["pumps"] == 3 and j["fleet_config"]["barriers"] == 8
        return expect(ok, "partial fleet fills defaults", f"{j['fleet_config']}")

    check("session: partial fleet object fills defaults", _fleet_missing_subkey)

    def _session_get():
        sid = new_session(api)
        r = api.get(f"/api/v1/session?session_id={sid}")
        j = r.json()
        return expect(r.status_code == 200 and j["session_id"] == sid, "GET returns session", f"{r.status_code}")

    check("session: GET by id", _session_get)

    def _session_missing():
        r = api.get("/api/v1/session?session_id=SES-NOPE")
        return expect(r.status_code == 404, "404 for unknown session", f"{r.status_code}")

    check("session: unknown id -> 404", _session_missing)

    def _session_no_id():
        r = api.get("/api/v1/session")
        return expect(r.status_code == 400, "400 when session_id omitted", f"{r.status_code}")

    check("session: missing id -> 400", _session_no_id)

    # -------------------------------------------------------------- scenario
    section("C. Scenario / triage")

    sid = new_session(api, rain_mmhr=95, mode="red_alert")

    def _scenario():
        r = api.get(f"/api/v1/scenario?session_id={sid}")
        j = r.json()
        ok = r.status_code == 200 and len(j["alerts"]) > 0 and len(j["nodes"]) > 0
        return expect(ok, f"{len(j['alerts'])} alerts, {len(j['nodes'])} nodes, "
                          f"{j['stats']['raw_above_floor']} raw crossings, "
                          f"{j['stats']['dedup_alerts']} after dedup, "
                          f"{j['stats']['inference_latency_ms']}ms", f"empty scene: {list(j)}")

    check("scenario: 95 mm/hr red-alert returns alerts + nodes", _scenario)

    def _dedup():
        j = api.get(f"/api/v1/scenario?session_id={sid}").json()
        st = j["stats"]
        red = st["raw_above_floor"] / max(1, st["dedup_alerts"])
        return expect(st["dedup_alerts"] < st["raw_above_floor"],
                      f"dedup {st['raw_above_floor']} -> {st['dedup_alerts']} ({red:.1f}x reduction)",
                      f"no reduction: {st}")

    check("scenario: spatial dedup actually reduces the queue", _dedup)

    def _unique_ids():
        j = api.get(f"/api/v1/scenario?session_id={sid}").json()
        ids = [a["alert_id"] for a in j["alerts"]]
        return expect(len(ids) == len(set(ids)), f"{len(ids)} unique alert ids", "duplicate alert ids")

    check("scenario: alert ids are unique", _unique_ids)

    def _sorted():
        j = api.get(f"/api/v1/scenario?session_id={sid}").json()
        scores = [a["score"] for a in j["alerts"]]
        return expect(scores == sorted(scores, reverse=True), "queue sorted by score desc", "queue unsorted")

    check("scenario: queue is consequence-ordered", _sorted)

    def _determinism():
        a = api.get(f"/api/v1/scenario?session_id={sid}").json()
        b = api.get(f"/api/v1/scenario?session_id={sid}").json()
        same = [x["alert_id"] for x in a["alerts"]] == [x["alert_id"] for x in b["alerts"]]
        return expect(same, "two calls return identical ordering", "ordering unstable between calls")

    check("scenario: deterministic ordering", _determinism)

    def _heat_curve():
        counts = []
        for mm in (20, 40, 60, 80, 100, 120):
            j = api.get(f"/api/v1/scenario?session_id={sid}&rain_mmhr={mm}").json()
            counts.append((mm, j["stats"]["raw_above_floor"]))
        mono = all(counts[i][1] <= counts[i + 1][1] for i in range(len(counts) - 1))
        return (("PASS" if mono else "WARN"),
                "raw crossings " + " ".join(f"{m}:{c}" for m, c in counts))

    check("scenario: alert count grows monotonically with rain", _heat_curve)

    def _mode_shift():
        n = api.get(f"/api/v1/scenario?session_id={sid}&mode=normal").json()
        r = api.get(f"/api/v1/scenario?session_id={sid}&mode=red_alert").json()
        return expect(len(r["alerts"]) >= len(n["alerts"]),
                      f"red-alert {len(r['alerts'])} >= normal {len(n['alerts'])}",
                      f"red-alert produced fewer alerts: {len(r['alerts'])} < {len(n['alerts'])}")

    check("scenario: Red-Alert escalates the queue", _mode_shift)

    def _region_filter():
        j = api.get(f"/api/v1/scenario?session_id={sid}&region=hsr").json()
        wrong = [a for a in j["alerts"] if a["catchment"] != "hsr"]
        return expect(not wrong and len(j["alerts"]) > 0,
                      f"{len(j['alerts'])} alerts, all in hsr", f"{len(wrong)} foreign-catchment alerts leaked")

    check("scenario: catchment filter leaks nothing", _region_filter)

    bad_scen = [("rain=abc", "&rain_mmhr=abc", 400), ("rain=NaN", "&rain_mmhr=NaN", 400),
                ("rain=Infinity", "&rain_mmhr=Infinity", 400), ("region=null", "&region=zzz", 400),
                ("mode=null", "&mode=zzz", 400), ("duration=abc", "&duration_min=abc", 400)]

    def make_bad_scen(qs: str, want: int):
        def _f():
            r = api.get(f"/api/v1/scenario?session_id={sid}{qs}")
            return expect(r.status_code == want, f"{r.status_code}", f"got {r.status_code}: {r.text[:100]}")
        return _f

    for name, qs, want in bad_scen:
        check(f"scenario rejects: {name}", make_bad_scen(qs, want))

    def _latency():
        t0 = time.perf_counter()
        api.get(f"/api/v1/scenario?session_id={sid}&rain_mmhr=101")
        cold = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        api.get(f"/api/v1/scenario?session_id={sid}&rain_mmhr=101")
        warm = (time.perf_counter() - t0) * 1000
        return expect(cold < 5000 and warm < 2000, f"cold {cold:.0f}ms / warm {warm:.0f}ms",
                      f"slow: cold {cold:.0f}ms warm {warm:.0f}ms")

    check("scenario: end-to-end latency budget", _latency)

    # -------------------------------------------------------------- dispatch
    section("D. Dispatch lifecycle, scarcity and concurrency")

    def _dispatch_one():
        s = new_session(api, fleet={"pumps": 12, "barriers": 8, "wardens": 6})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        pumpable = [a for a in al if a["unit_class"] == "pump" or a["action"] == "pump_dispatch"]
        if not pumpable:
            return ("SKIP", "no pump-class alert at 95 mm/hr")
        a = pumpable[0]
        r = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]})
        j = r.json()
        ok = r.status_code == 200 and j.get("ok") and j.get("unit")
        return expect(ok, f"{j.get('unit', {}).get('unit_id')} -> {a['alert_id'][:28]} "
                          f"ETA {j.get('eta_min')}m", f"{r.status_code}: {j}")

    check("dispatch: assigns a real unit", _dispatch_one)

    def _dispatch_twice():
        s = new_session(api)
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        a = al[0]
        api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]})
        r2 = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]})
        return expect(r2.status_code == 409, f"second dispatch -> {r2.status_code} (idempotent)",
                      f"double dispatch allowed: {r2.status_code}")

    check("dispatch: same alert twice is refused", _dispatch_twice)

    def _exhaust():
        s = new_session(api, fleet={"pumps": 2, "barriers": 1, "wardens": 1})
        al = [a for a in api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
              if a["action"] == "pump_dispatch"]
        ok_ct = 0
        refused = 0
        for a in al[:6]:
            r = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]})
            j = r.json()
            if j.get("ok"):
                ok_ct += 1
            else:
                refused += 1
                if not j.get("message"):
                    return ("FAIL", f"refusal without message: {j}")
        return expect(ok_ct <= 2 and refused >= 1,
                      f"{ok_ct} dispatched (limit 2), {refused} refused with explicit message",
                      f"over-allocation: {ok_ct} dispatched with only 2 pumps")

    check("dispatch: cannot exceed the entered pump count", _exhaust)

    def _zero_fleet():
        s = new_session(api, fleet={"pumps": 0, "barriers": 0, "wardens": 0})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        r = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": al[0]["alert_id"]})
        j = r.json()
        ok = r.status_code == 200 and j.get("ok") is False and j.get("message")
        return expect(ok, f"refused with message: {str(j.get('message'))[:60]}", f"{r.status_code}: {j}")

    check("dispatch: zero fleet refuses in words, not silence", _zero_fleet)

    def _unknown_alert():
        s = new_session(api)
        r = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": "ALT-NOPE-0000"})
        return expect(r.status_code == 404, "404 for unknown alert", f"{r.status_code}")

    check("dispatch: unknown alert -> 404", _unknown_alert)

    def _no_alert_id():
        s = new_session(api)
        r = api.post("/api/v1/dispatch", {"session_id": s})
        return expect(r.status_code == 400, "400 when alert_id missing", f"{r.status_code}")

    check("dispatch: missing alert_id -> 400", _no_alert_id)

    def _no_session():
        r = api.post("/api/v1/dispatch", {"alert_id": "ALT-HSR-1"})
        return expect(r.status_code == 400, "400 when session_id missing", f"{r.status_code}")

    check("dispatch: missing session -> 400", _no_session)

    def _concurrent():
        s = new_session(api)
        aid = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"][0]["alert_id"]

        def fire(_):
            return api.post("/api/v1/dispatch", {"session_id": s, "alert_id": aid}).status_code

        with ThreadPoolExecutor(max_workers=8) as ex:
            codes = list(ex.map(fire, range(8)))
        wins = codes.count(200)
        return expect(wins == 1, f"8 concurrent dispatches -> {wins} accepted, {codes.count(409)} refused",
                      f"race: {wins} accepted (codes={codes})")

    check("dispatch: 8 concurrent requests for one alert", _concurrent)

    # ---------------------------------------------------------------- dismiss
    section("E. Dismiss — operator feedback must reach the flood state")

    def _dismiss():
        s = new_session(api)
        sc = api.get(f"/api/v1/scenario?session_id={s}").json()
        a = sc["alerts"][0]
        before = next((n["depth_m"] for n in sc["nodes"] if n["id"] == a["id"]), None)
        r = api.post("/api/v1/dismiss",
                     {"session_id": s, "alert_id": a["alert_id"], "reason": "false_alarm"})
        j = r.json()
        after_sc = api.get(f"/api/v1/scenario?session_id={s}").json()
        after = next((n["depth_m"] for n in after_sc["nodes"] if n["id"] == a["id"]), None)
        still = next((x for x in after_sc["alerts"] if x["alert_id"] == a["alert_id"]), None)
        ok = r.status_code == 200 and still is not None and still["dispatch_status"] == "DISMISSED"
        return expect(ok, f"alert marked DISMISSED (depth {before} -> {after})",
                      f"{r.status_code}: card={still and still.get('dispatch_status')}, raw={j.get('node_id', j)}")

    check("dismiss: alert moves to DISMISSED state", _dismiss)

    def _dismiss_clears_depth():
        """The API claims 'operator feedback applied to flood & routing state'."""
        s = new_session(api)
        sc = api.get(f"/api/v1/scenario?session_id={s}").json()
        a = sc["alerts"][0]
        before = next((n["depth_m"] for n in sc["nodes"] if n["id"] == a["id"]), None)
        j = api.post("/api/v1/dismiss",
                     {"session_id": s, "alert_id": a["alert_id"],
                      "reason": "false_alarm", "node_id": a["id"]}).json()
        after_sc = api.get(f"/api/v1/scenario?session_id={s}").json()
        after = next((n["depth_m"] for n in after_sc["nodes"] if n["id"] == a["id"]), None)
        ok = before is not None and after is not None and after < before
        return expect(ok, f"node depth {before} -> {after} (feedback applied)",
                      f"depth unchanged {before} -> {after}; node_id echoed as {j.get('node_id')!r}")

    check("dismiss: false_alarm zeroes the node depth", _dismiss_clears_depth)

    def _dismiss_autonode():
        """Without an explicit node_id, the server must derive it from the alert."""
        s = new_session(api)
        sc = api.get(f"/api/v1/scenario?session_id={s}").json()
        a = sc["alerts"][0]
        j = api.post("/api/v1/dismiss",
                     {"session_id": s, "alert_id": a["alert_id"], "reason": "false_alarm"}).json()
        derived = j.get("node_id")
        return expect(derived == a["id"], f"derived node_id={derived!r} (correct={a['id']!r})",
                      f"WRONG node_id derived: {derived!r} != {a['id']!r} — feedback targets a nonexistent node")

    check("dismiss: derives node_id from alert_id correctly", _dismiss_autonode)

    def _dismiss_bad_reason():
        s = new_session(api)
        aid = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"][0]["alert_id"]
        r = api.post("/api/v1/dismiss", {"session_id": s, "alert_id": aid, "reason": "because"})
        return expect(r.status_code == 400, "400 for unknown reason", f"{r.status_code}")

    check("dismiss: rejects unknown reason", _dismiss_bad_reason)

    # ------------------------------------------------------------------- tick
    section("F. Simulated clock and fleet state machine")

    def _tick():
        s = new_session(api)
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        a = next((x for x in al if x.get("action") == "pump_dispatch" and x.get("feasible")), al[0])
        api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]})
        states = []
        for _ in range(12):
            j = api.post("/api/v1/tick", {"session_id": s, "minutes": 10}).json()
            units = j["fleet"].get("units", [])
            u = next((x for x in units if x.get("assigned_alert_id") == a["alert_id"]), None)
            if u:
                states.append(u["state"])
        seen = set(states)
        ok = "EN_ROUTE" in seen or "DEWATERING" in seen or "ON_SITE" in seen
        return expect(ok, f"states over 2h: {' -> '.join(dict.fromkeys(states))}", f"stuck: {seen}")

    check("tick: unit progresses through its lifecycle", _tick)

    def _barrier_reopen_lifecycle():
        s = new_session(api, rain_mmhr=95, mode="red_alert")
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        b = next((x for x in al if x.get("action") == "barrier_closure" and x.get("feasible")), None)
        if not b:
            return WARN, "no feasible barrier_closure alert found"
        d = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": b["alert_id"]}).json()
        uid = d["unit"]["unit_id"]
        tk = api.post("/api/v1/tick", {"session_id": s, "minutes": 2}).json()
        u_closed = next((x for x in tk["fleet"]["units"] if x["unit_id"] == uid), {})
        re = api.post("/api/v1/reopen", {"session_id": s, "unit_id": uid})
        rj = re.json()
        ok = (
            u_closed.get("state") == "CLOSED"
            and re.status_code == 200
            and rj.get("unit", {}).get("state") in ("STANDBY", "IDLE")
        )
        return expect(
            ok,
            f"{uid}: PENDING_CLOSE -> CLOSED -> {rj.get('unit', {}).get('state')}",
            f"closed={u_closed.get('state')} reopen={re.status_code}:{rj}",
        )

    check("barrier: PENDING_CLOSE -> CLOSED -> reopen -> STANDBY", _barrier_reopen_lifecycle)

    def _tick_clock():
        s = new_session(api)
        c0 = api.get(f"/api/v1/session?session_id={s}").json()["sim_clock_min"]
        api.post("/api/v1/tick", {"session_id": s, "minutes": 30})
        c1 = api.get(f"/api/v1/session?session_id={s}").json()["sim_clock_min"]
        return expect(abs((c1 - c0) - 30) < 0.01, f"clock {c0} -> {c1}", f"clock drift {c0} -> {c1}")

    check("tick: advances the simulated clock exactly", _tick_clock)

    def _tick_bad():
        s = new_session(api)
        ok = True
        seen = []
        for v in (-5, 0, 999, "abc"):
            r = api.post("/api/v1/tick", {"session_id": s, "minutes": v})
            seen.append(f"{v}:{r.status_code}")
            if r.status_code not in (400,):
                ok = False
        return expect(ok, "all rejected: " + " ".join(seen), "accepted invalid ticks: " + " ".join(seen))

    check("tick: rejects negative / zero / huge / non-numeric", _tick_bad)

    # ------------------------------------------------------------------ route
    section("G. Corridor routing")

    def _route_same():
        s = new_session(api)
        j = api.get(f"/api/v1/scenario?session_id={s}&region=hsr").json()
        nid = j["nodes"][0]["id"]
        r = api.get(f"/api/v1/route?session_id={s}&origin={nid}&dest={nid}")
        return ("PASS" if r.status_code < 500 else "FAIL", f"{r.status_code}: {r.text[:120]}")

    check("route: origin == destination does not 500", _route_same)

    def _route_cross():
        s = new_session(api)
        a = api.get(f"/api/v1/scenario?session_id={s}&region=hsr").json()["nodes"][0]["id"]
        b = api.get(f"/api/v1/scenario?session_id={s}&region=whitefield").json()["nodes"][0]["id"]
        r = api.get(f"/api/v1/route?session_id={s}&origin={a}&dest={b}")
        j = r.json()
        ok = r.status_code == 200 and j.get("inter_catchment") is True
        return expect(ok, f"inter_catchment={j.get('inter_catchment')}, "
                          f"stub={j.get('stub_coords') is not None}", f"{r.status_code}: {list(j)[:8]}")

    check("route: cross-catchment flagged + stub leg", _route_cross)

    def _route_unknown():
        s = new_session(api)
        r = api.get(f"/api/v1/route?session_id={s}&origin=NOPE-1&dest=NOPE-2")
        return expect(r.status_code == 404, "404 for unresolvable endpoints", f"{r.status_code}")

    check("route: unknown nodes -> 404", _route_unknown)

    def _route_malformed():
        s = new_session(api)
        r = api.get(f"/api/v1/route?session_id={s}&origin_lat=abc&origin_lng=xyz&dest_lat=1&dest_lng=2")
        return ("PASS" if r.status_code < 500 else "FAIL",
                f"{r.status_code} (500 = unguarded float() on query param)")

    check("route: non-numeric coordinates do not 500", _route_malformed)

    def _route_missing():
        s = new_session(api)
        r = api.get(f"/api/v1/route?session_id={s}")
        return expect(r.status_code == 400, "400 when origin/dest absent", f"{r.status_code}")

    check("route: missing origin/dest -> 400", _route_missing)

    def _route_vehicle():
        s = new_session(api)
        n = api.get(f"/api/v1/scenario?session_id={s}&region=hsr").json()["nodes"]
        r = api.get(f"/api/v1/route?session_id={s}&origin={n[0]['id']}&dest={n[1]['id']}&vehicle=hovercraft")
        return expect(r.status_code == 400, "400 for unknown vehicle", f"{r.status_code}")

    check("route: rejects unknown vehicle", _route_vehicle)

    def _route_impassable():
        s = new_session(api, rain_mmhr=120, mode="normal")
        n = api.get(f"/api/v1/scenario?session_id={s}&region=koramangala").json()["nodes"]
        hits = 0
        for i in range(0, min(12, len(n) - 1), 2):
            j = api.get(f"/api/v1/route?session_id={s}&origin={n[i]['id']}&dest={n[i+1]['id']}").json()
            if j.get("reachable") is False:
                hits += 1
        return ("PASS", f"{hits}/6 sampled corridors correctly report impassable") if hits else \
               ("WARN", "no impassable corridor found at 120 mm/hr — depth field may be too shallow")

    check("route: flood-blocked corridors report unreachable", _route_impassable)

    # ------------------------------------------------------------- transit/veto
    section("H. Transit corridors, veto, fleet, log")

    def _transit():
        s = new_session(api)
        r = api.get(f"/api/v1/transit?session_id={s}")
        j = r.json()
        return expect(r.status_code == 200 and isinstance(j.get("corridors"), list),
                      f"{len(j.get('corridors', []))} corridors evaluated", f"{r.status_code}: {list(j)[:6]}")

    check("transit: returns corridor list", _transit)

    def _veto_unknown():
        s = new_session(api)
        r = api.post("/api/v1/veto", {"session_id": s, "unit_id": "PUMP-99"})
        return expect(r.status_code == 404, "404 for unknown unit", f"{r.status_code}")

    check("veto: unknown unit -> 404", _veto_unknown)

    def _veto_not_pending():
        s = new_session(api)
        r = api.post("/api/v1/veto", {"session_id": s, "unit_id": "BAR-01"})
        return expect(r.status_code == 409, "409 for IDLE barrier not pending close", f"{r.status_code}")

    check("veto: IDLE barrier -> 409", _veto_not_pending)

    def _veto_real():
        # Barrier closures only exist in the queue at one storm setting today (see section J),
        # so target that setting explicitly rather than skipping.
        s = new_session(api, rain_mmhr=25, mode="normal",
                        fleet={"pumps": 4, "barriers": 4, "wardens": 4})
        al = [a for a in api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
              if a["action"] == "barrier_closure"]
        if not al:
            return ("FAIL", "no barrier alert reachable at 25 mm/hr — barrier fleet unusable")
        a = al[0]
        d = api.post("/api/v1/dispatch", {"session_id": s, "alert_id": a["alert_id"]}).json()
        uid = (d.get("unit") or {}).get("unit_id")
        if not uid:
            return ("FAIL", f"barrier alert could not be dispatched: {d.get('message')}")
        r = api.post("/api/v1/veto", {"session_id": s, "unit_id": uid})
        return expect(r.status_code == 200, f"veto on {uid} -> {r.status_code}", f"{r.status_code}: {r.text[:120]}")

    check("veto: barrier closure can be vetoed", _veto_real)

    def _fleet():
        s = new_session(api, fleet={"pumps": 5, "barriers": 2, "wardens": 1})
        j = api.get(f"/api/v1/fleet?session_id={s}").json()
        total = _total_units(j)
        return expect(total == 8, f"{total} units built from 5P/2B/1W",
                      f"total={total}, expected 8")

    check("fleet: unit count equals entered inventory", _fleet)

    def _log():
        s = new_session(api)
        j = api.get(f"/api/v1/log?session_id={s}").json()
        return expect(isinstance(j.get("events"), list) and len(j["events"]) >= 1,
                      f"{len(j['events'])} events, latest_seq={j.get('latest_seq')}", f"{list(j)}")

    check("log: returns audit events", _log)

    def _log_since():
        s = new_session(api)
        j1 = api.get(f"/api/v1/log?session_id={s}").json()
        seq = j1["latest_seq"]
        j2 = api.get(f"/api/v1/log?session_id={s}&since={seq}").json()
        return expect(len(j2["events"]) == 0, "since=latest returns empty", f"{len(j2['events'])} leaked")

    check("log: since-token is exclusive", _log_since)

    def _log_malformed():
        r = api.get("/api/v1/log?since=abc")
        return ("PASS" if r.status_code < 500 else "FAIL",
                f"{r.status_code} (500 = unguarded int() on query param)")

    check("log: non-numeric since does not 500", _log_malformed)

    def _node():
        s = new_session(api)
        nid = api.get(f"/api/v1/scenario?session_id={s}&region=hsr").json()["nodes"][0]["id"]
        r = api.get(f"/api/v1/node/{nid}?session_id={s}")
        j = r.json()
        return expect(r.status_code == 200 and "node" in j, f"inspector for {nid}", f"{r.status_code}")

    check("node: inspector returns a record", _node)

    def _node_unknown():
        r = api.get("/api/v1/node/NOPE-999")
        return expect(r.status_code == 404, "404 for unknown node", f"{r.status_code}")

    check("node: unknown node -> 404", _node_unknown)

    def _evaluation():
        r = api.get("/api/v1/evaluation")
        j = r.json()
        return expect(j.get("ready") is True, "baseline evaluation JSON is generated", f"{j.get('message')}")

    check("evaluation: baseline comparison available", _evaluation)

    # ------------------------------------------------------ product integrity
    section("J. Product integrity — does the headline decision layer actually work?")

    def _barrier_reachability():
        hits = []
        for mode in ("normal", "red_alert"):
            for mm in (25, 35, 45, 55, 65, 75, 85, 95):
                s = new_session(api, rain_mmhr=mm, mode=mode,
                                fleet={"pumps": 8, "barriers": 8, "wardens": 8})
                j = api.get(f"/api/v1/scenario?session_id={s}").json()
                n = sum(1 for a in j["alerts"] if a["action"] == "barrier_closure")
                hits.append((mode, mm, n))
        usable = [h for h in hits if h[2] > 0]
        return expect(len(usable) >= 4,
                      f"barrier closures queued in {len(usable)}/16 storm settings",
                      "barrier fleet is unreachable — closures queued in only "
                      f"{len(usable)}/16 settings: {usable}")

    check("product: barrier closure reaches the operator queue", _barrier_reachability)

    def _beats_peak():
        s = new_session(api, rain_mmhr=95, mode="red_alert",
                        fleet={"pumps": 12, "barriers": 8, "wardens": 6})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        late = [a for a in al if a.get("feasible") and a.get("eta_min") and a.get("ttp_min")
                and a["eta_min"] > a["ttp_min"]]
        flagged = [a for a in late if a.get("beats_peak") is False]
        if not late:
            return ("PASS", "no late-but-feasible alerts")
        if len(flagged) == len(late):
            return ("WARN", f"{len(late)} alert(s) arrive after peak but are explicitly flagged")
        return ("FAIL",
                f"{len(late)} alerts claim 'feasible' yet arrive after peak and are not flagged "
                f"(e.g. {late[0]['name']}: ETA {late[0]['eta_min']}m vs peak {late[0]['ttp_min']}m)")

    check("product: 'feasible' respects time-to-peak", _beats_peak)

    def _detour_sign():
        s = new_session(api, rain_mmhr=95, mode="red_alert",
                        fleet={"pumps": 12, "barriers": 8, "wardens": 6})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        neg = [a for a in al if a.get("addedMinutes") is not None and a["addedMinutes"] < 0]
        sample = neg[0]["name"] if neg else ""
        if not neg:
            return ("PASS", "no negative detour deltas")
        return ("FAIL",
                f"{len(neg)} alerts report a negative 'added' time (e.g. {sample}: "
                f"{neg[0]['addedMinutes']}m) — safe route is shorter than the naive baseline, "
                "so the label is wrong, not the route")

    check("product: detour delta is never negative", _detour_sign)

    def _pending_route():
        s = new_session(api, rain_mmhr=95, mode="red_alert",
                        fleet={"pumps": 12, "barriers": 8, "wardens": 6})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        pending = [a for a in al if a["dispatch_status"] == "PENDING"]
        with_route = [a for a in pending if a.get("route")]
        return expect(len(with_route) == len(pending),
                      f"{len(with_route)}/{len(pending)} pending alerts carry a corridor preview",
                      f"only {len(with_route)}/{len(pending)} pending alerts carry a route — the map cannot "
                      "draw the recommended corridor before the operator approves")

    check("product: pending alerts include a corridor preview", _pending_route)

    def _session_growth():
        before = api.get("/health").json()["active_sessions"]
        for _ in range(12):
            new_session(api)
        after = api.get("/health").json()["active_sessions"]
        return expect(after <= 64,
                      f"active_sessions {before} -> {after} (bounded <= 64)",
                      f"exceeded session cap 64: {before} -> {after}")

    check("product: session store behaviour under load", _session_growth)

    def _dispatch_latency():
        s = new_session(api, rain_mmhr=93, mode="normal",
                        fleet={"pumps": 10, "barriers": 6, "wardens": 6})
        al = api.get(f"/api/v1/scenario?session_id={s}").json()["alerts"]
        t0 = time.perf_counter()
        api.post("/api/v1/dispatch", {"session_id": s, "alert_id": al[0]["alert_id"]})
        first = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        api.post("/api/v1/dispatch", {"session_id": s, "alert_id": al[1]["alert_id"]})
        second = (time.perf_counter() - t0) * 1000
        if second < first * 0.6 + 60:
            return ("PASS", f"dispatch latency first {first:.0f}ms, second {second:.0f}ms")
        return ("WARN", f"dispatch repeats full triage: {first:.0f}ms -> {second:.0f}ms (cache key misses)")

    check("product: dispatch reuses the scenario cache", _dispatch_latency)

    # ------------------------------------------------------------------ CORS
    section("I. HTTP hygiene")

    def _cors():
        r = api.get("/health", headers={"Origin": "http://localhost:5173"})
        return expect(r.headers.get("Access-Control-Allow-Origin") == "*", "CORS wildcard present",
                      "no CORS header")

    check("http: CORS header on responses", _cors)

    def _404_json():
        r = api.get("/api/v1/does-not-exist")
        return expect(r.status_code == 404, "404 for unknown route", f"{r.status_code}")

    check("http: unknown route -> 404", _404_json)

    def _500_is_json():
        r = api.get("/api/v1/log?since=abc")
        ctype = r.headers.get("Content-Type", "")
        return ("PASS" if "json" in ctype else "WARN",
                f"{r.status_code} {ctype.split(';')[0]}")

    check("http: error responses are JSON, not HTML traceback", _500_is_json)

    # --------------------------------------------------------------- summary
    dur = time.time() - t_start
    counts = {k: sum(1 for r in RESULTS if r["status"] == k) for k in ("PASS", "FAIL", "WARN", "SKIP")}
    print(f"\n\033[1m{'=' * 78}\033[0m")
    print(f"  {counts['PASS']} passed · {counts['FAIL']} failed · {counts['WARN']} warnings · "
          f"{counts['SKIP']} skipped   in {dur:.1f}s")
    print(f"\033[1m{'=' * 78}\033[0m")
    if counts["FAIL"]:
        print("\nFAILURES:")
        for r in RESULTS:
            if r["status"] == "FAIL":
                print(f"  ✗ {r['name']}\n      {r['detail']}")
    if counts["WARN"]:
        print("\nWARNINGS:")
        for r in RESULTS:
            if r["status"] == "WARN":
                print(f"  ! {r['name']}\n      {r['detail']}")

    with open("scratch/verification/api-audit.json", "w", encoding="utf-8") as f:
        json.dump({"base": base, "duration_s": round(dur, 1), "counts": counts, "results": RESULTS},
                  f, indent=2)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    args = ap.parse_args()
    sys.exit(audit(args.base))
