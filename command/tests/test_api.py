"""Gate D Flask API tests covering parity, zero-pump scarcity, session isolation, transit, and audit."""
from __future__ import annotations

import glob
import json
import tempfile
import unittest

from command.app import create_app
from command.config import EXPECTED_TOTAL_EDGES, EXPECTED_TOTAL_NODES
from command.state import SessionStore


class TestApiGateD(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.app = create_app(
            audit_dir=cls.tmp_dir.name,
            load_model=True,
            session_store=SessionStore(),
        )
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp_dir.cleanup()

    def test_health_and_bootstrap_parity(self) -> None:
        r_h = self.client.get("/health")
        self.assertEqual(r_h.status_code, 200)
        h = r_h.get_json()
        self.assertEqual(h["total_nodes"], EXPECTED_TOTAL_NODES)
        self.assertEqual(h["total_edges"], EXPECTED_TOTAL_EDGES)
        self.assertTrue(h["predictor_loaded"])
        self.assertTrue(h["simulation"])

        r_b = self.client.get("/api/v1/bootstrap")
        self.assertEqual(r_b.status_code, 200)
        b = r_b.get_json()
        self.assertEqual(len(b["roads"]), EXPECTED_TOTAL_EDGES)
        self.assertEqual(len(b["depots"]), 6)
        self.assertGreaterEqual(len(b["pois"]), 100)

    def test_validation_and_zero_pumps_session(self) -> None:
        bad = self.client.post("/api/v1/session", json={"pumps": 31})
        self.assertEqual(bad.status_code, 400)

        r_s = self.client.post(
            "/api/v1/session",
            json={"operator": "zero-test", "region": "all", "rain_mmhr": 95, "mode": "red_alert", "pumps": 0, "barriers": 4, "wardens": 4},
        )
        self.assertEqual(r_s.status_code, 201)
        sid = r_s.get_json()["session_id"]

        sc = self.client.get(f"/api/v1/scenario?session_id={sid}&rain_mmhr=95&mode=red_alert").get_json()
        pump_alerts = [a for a in sc["alerts"] if a["unit_class"] == "pump"]
        self.assertGreater(len(pump_alerts), 0)
        for a in pump_alerts:
            self.assertFalse(a["feasible"])
            self.assertEqual(a["infeasible_reason"], "no_unit")

        disp = self.client.post("/api/v1/dispatch", json={"session_id": sid, "alert_id": pump_alerts[0]["alert_id"]})
        self.assertEqual(disp.status_code, 200)
        dj = disp.get_json()
        self.assertFalse(dj["ok"])
        self.assertEqual(dj["reason"], "no_unit")

    def test_session_isolation_lifecycle_transit_and_audit(self) -> None:
        s1 = self.client.post(
            "/api/v1/session",
            json={"operator": "alice", "region": "all", "rain_mmhr": 95, "mode": "normal", "pumps": 12, "barriers": 8, "wardens": 6},
        ).get_json()["session_id"]
        s2 = self.client.post(
            "/api/v1/session",
            json={"operator": "bob", "region": "all", "rain_mmhr": 95, "mode": "normal", "pumps": 1, "barriers": 2, "wardens": 2},
        ).get_json()["session_id"]

        sc1 = self.client.post("/api/v1/scenario", json={"session_id": s1, "rain_mmhr": 95, "mode": "red_alert"}).get_json()
        alerts1 = sc1["alerts"]
        self.assertGreater(len(alerts1), 5)
        self.assertIn("transit", sc1)
        self.assertGreaterEqual(len(sc1["transit"]["corridors"]), 5)

        pump_a = next(a for a in alerts1 if a["unit_class"] == "pump" and a["feasible"])
        d1 = self.client.post("/api/v1/dispatch", json={"session_id": s1, "alert_id": pump_a["alert_id"]})
        self.assertEqual(d1.status_code, 200)
        self.assertTrue(d1.get_json()["ok"])

        # Session 2 fleet must still be untouched (1/1 idle pump)
        f2 = self.client.get(f"/api/v1/fleet?session_id={s2}").get_json()
        self.assertEqual(f2["counts"]["pump"]["idle"], 1)

        # Invalid dismiss reason -> 400; valid -> 200
        self.assertEqual(
            self.client.post("/api/v1/dismiss", json={"session_id": s1, "alert_id": "X", "reason": "bad"}).status_code,
            400,
        )
        other = alerts1[-1]
        self.assertEqual(
            self.client.post("/api/v1/dismiss", json={"session_id": s1, "alert_id": other["alert_id"], "reason": "false_alarm"}).status_code,
            200,
        )

        # Barrier dispatch + veto
        bar_a = next((a for a in alerts1 if a["unit_class"] == "barrier" and a["feasible"]), None)
        if bar_a:
            db = self.client.post("/api/v1/dispatch", json={"session_id": s1, "alert_id": bar_a["alert_id"]}).get_json()
            self.assertTrue(db["ok"])
            vb = self.client.post("/api/v1/veto", json={"session_id": s1, "unit_id": db["unit"]["unit_id"]}).get_json()
            self.assertTrue(vb["ok"])
            self.assertEqual(vb["unit"]["state"], "STANDBY")

        # Tick clock forward & check transit endpoint
        tk = self.client.post("/api/v1/tick", json={"session_id": s1, "minutes": 10.0}).get_json()
        self.assertEqual(tk["sim_clock_min"], 10.0)
        tr = self.client.get(f"/api/v1/transit?session_id={s1}&rain_mmhr=95").get_json()
        self.assertGreaterEqual(len(tr["corridors"]), 5)

        # Route endpoint check
        cor0 = tr["corridors"][0]
        rt = self.client.post(
            "/api/v1/route",
            json={"session_id": s1, "origin": cor0["origin_node"], "dest": cor0["dest_node"], "vehicle": "bus", "rain_mmhr": 95},
        ).get_json()
        self.assertIn("standard", rt)
        self.assertIn("safe", rt)

        # Node inspect check
        nd = self.client.get(f"/api/v1/node/{cor0['origin_node']}?session_id={s1}&rain_mmhr=95").get_json()
        self.assertEqual(nd["node"]["id"], cor0["origin_node"])

        # Audit log file must exist and contain valid JSONL records for s1
        files = glob.glob(f"{self.tmp_dir.name}/audit-*.jsonl")
        self.assertEqual(len(files), 1)
        with open(files[0], "r") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        s1_actions = {row["action"] for row in lines if row["session_id"] == s1}
        self.assertIn("SESSION_INIT", s1_actions)
        self.assertIn("DISPATCH_APPROVED", s1_actions)
        self.assertIn("ALERT_DISMISSED", s1_actions)
        self.assertIn("CORRIDOR_ROUTED", s1_actions)

    def test_regression_barrier_dismiss_reopen_and_eviction(self) -> None:
        # 1. Barrier closure must be reachable at 95 mm/hr red_alert; addedMinutes >= 0 & beats_peak present
        s = self.client.post(
            "/api/v1/session",
            json={"operator": "reg", "region": "all", "rain_mmhr": 95, "duration_min": 60, "mode": "red_alert", "pumps": 8, "barriers": 4, "wardens": 4},
        ).get_json()["session_id"]
        sc = self.client.post("/api/v1/scenario", json={"session_id": s}).get_json()
        alerts = sc["alerts"]
        bar = next((a for a in alerts if a["action"] == "barrier_closure" and a["feasible"]), None)
        self.assertIsNotNone(bar, "Expected feasible barrier_closure at 95 mm/hr red_alert")
        for a in alerts:
            self.assertGreaterEqual(float(a.get("addedMinutes", 0.0)), 0.0)
            if a["dispatch_status"] == "PENDING" and a.get("eta_min") is not None:
                self.assertIn("beats_peak", a)

        # 2. Barrier lifecycle: PENDING_CLOSE -> CLOSED -> reopen -> STANDBY
        db = self.client.post("/api/v1/dispatch", json={"session_id": s, "alert_id": bar["alert_id"]}).get_json()
        uid = db["unit"]["unit_id"]
        tk = self.client.post("/api/v1/tick", json={"session_id": s, "minutes": 2.0}).get_json()
        u_closed = next(u for u in tk["fleet"]["units"] if u["unit_id"] == uid)
        self.assertEqual(u_closed["state"], "CLOSED")
        re = self.client.post("/api/v1/reopen", json={"session_id": s, "unit_id": uid})
        self.assertEqual(re.status_code, 200)
        self.assertEqual(re.get_json()["unit"]["state"], "STANDBY")

        # 3. Dismiss false_alarm zeros out node depth on subsequent scenario fetch
        target = next(a for a in alerts if a["action"] == "pump_dispatch")
        dm = self.client.post("/api/v1/dismiss", json={"session_id": s, "alert_id": target["alert_id"], "reason": "false_alarm", "node_id": target["id"]})
        self.assertEqual(dm.status_code, 200)
        sc2 = self.client.post("/api/v1/scenario", json={"session_id": s}).get_json()
        n_after = next((n for n in sc2["nodes"] if n["id"] == target["id"]), None)
        if n_after is not None:
            self.assertEqual(n_after["depth_m"], 0.0)

        # 4. Evicted session returns 410 session_expired
        for i in range(65):
            self.client.post("/api/v1/session", json={"operator": f"evict-{i}", "region": "hsr", "rain_mmhr": 45, "duration_min": 60, "mode": "normal", "pumps": 2, "barriers": 2, "wardens": 2})
        ev_resp = self.client.get(f"/api/v1/session?session_id={s}")
        self.assertEqual(ev_resp.status_code, 410)
        self.assertTrue(ev_resp.get_json().get("session_evicted"))


if __name__ == "__main__":
    unittest.main()
