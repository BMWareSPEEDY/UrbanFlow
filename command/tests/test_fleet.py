"""Gate C unit tests for fleet inventory, scarcity refusals, barrier veto, clock, and transit."""
from __future__ import annotations

import unittest
import numpy as np

from command.fleet import (
    advance_fleet_clock,
    closed_barrier_nodes,
    dispatch_alert,
    enrich_alerts_with_fleet,
    fleet_summary,
    veto_barrier,
)
from command.loader import get_registry
from command.schemas import ValidationError, validate_session_payload
from command.state import SessionStore
from command.transit import evaluate_transit_corridors
from command.triage import triage_scenario


class TestFleetGateC(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = get_registry(load_model=True)

    def _make_synthetic_pump_alerts(self, count: int) -> list[dict]:
        """Build `count` pump alerts across real catchment SCC nodes."""
        alerts = []
        catch_keys = list(self.reg.catchments.keys())
        for idx in range(count):
            ck = catch_keys[idx % len(catch_keys)]
            c = self.reg.catchments[ck]
            scc = [n for n in c.node_ids if n in c.scc_nodes]
            nid = scc[(idx * 13 + 7) % len(scc)]
            alerts.append(
                {
                    "alert_id": f"ALT-TEST-{idx+1:02d}",
                    "id": nid,
                    "catchment": ck,
                    "name": f"Test Pump Junction {idx+1}",
                    "depth_m": 0.42,
                    "score": round(90.0 - idx, 1),
                    "band": "pump",
                    "priority": "P1",
                    "action": "pump_dispatch",
                    "action_label": "Pump Dispatch",
                    "unit_class": "pump",
                    "underpass_poi_id": None,
                    "ttp_min": 25.0,
                    "assets": ["underpass"],
                }
            )
        return alerts

    def _dry_depths(self) -> dict[str, np.ndarray]:
        return {
            k: np.zeros(len(c.node_ids), dtype=np.float32)
            for k, c in self.reg.catchments.items()
        }

    def test_13_alerts_with_12_pumps_and_no_double_assign(self) -> None:
        store = SessionStore()
        cfg = validate_session_payload({"pumps": 12, "barriers": 8, "wardens": 6})
        sess = store.create(self.reg, cfg)
        alerts = self._make_synthetic_pump_alerts(13)
        depths = self._dry_depths()

        # Preview should mark top 12 feasible and 13th INFEASIBLE (no_unit)
        preview = enrich_alerts_with_fleet(
            self.reg, alerts, sess.units, sess.dismissed, depths, "t13", 0.0
        )
        self.assertEqual(sum(1 for a in preview if a["feasible"]), 12)
        self.assertFalse(preview[12]["feasible"])
        self.assertEqual(preview[12]["infeasible_reason"], "no_unit")
        self.assertIn("deploy_when", preview[0])
        self.assertIn("deploy_where", preview[0])

        assigned_units = set()
        for idx in range(12):
            res = dispatch_alert(
                self.reg, alerts[idx], sess.units, sess.dismissed, depths, "t13", 0.0
            )
            self.assertTrue(res["ok"], f"alert {idx} failed: {res}")
            uid = res["unit"]["unit_id"]
            self.assertNotIn(uid, assigned_units)
            assigned_units.add(uid)

        # Double-assign on alert 0 rejected
        dup = dispatch_alert(
            self.reg, alerts[0], sess.units, sess.dismissed, depths, "t13", 0.0
        )
        self.assertFalse(dup["ok"])
        self.assertEqual(dup["reason"], "already_dispatched")

        # 13th alert returns explicit no_unit with earliest freeing pump
        r13 = dispatch_alert(
            self.reg, alerts[12], sess.units, sess.dismissed, depths, "t13", 0.0
        )
        self.assertFalse(r13["ok"])
        self.assertEqual(r13["reason"], "no_unit")
        self.assertIn("frees in", r13["message"])

    def test_zero_pumps_shortfall_100pct(self) -> None:
        store = SessionStore()
        cfg = validate_session_payload({"pumps": 0, "barriers": 4, "wardens": 4})
        sess = store.create(self.reg, cfg)
        alerts = self._make_synthetic_pump_alerts(3)
        depths = self._dry_depths()
        for a in alerts:
            res = dispatch_alert(
                self.reg, a, sess.units, sess.dismissed, depths, "t0", 0.0
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["reason"], "no_unit")

    def test_validation_and_oversized_flag(self) -> None:
        with self.assertRaises(ValidationError):
            validate_session_payload({"pumps": 31})
        cfg = validate_session_payload({"pumps": 22})
        sess = SessionStore().create(self.reg, cfg)
        summ = fleet_summary(sess.units, 0.0)
        self.assertTrue(summ["fleet_oversized"])
        self.assertEqual(summ["counts"]["pump"]["total"], 22)

    def test_barrier_veto_and_clock_lifecycle(self) -> None:
        store = SessionStore()
        cfg = validate_session_payload({"pumps": 2, "barriers": 4, "wardens": 2})
        sess = store.create(self.reg, cfg)
        depths = self._dry_depths()
        bar_alert = {
            "alert_id": "ALT-BAR-1",
            "id": sess.units[2].home_node_id,  # first barrier node
            "catchment": sess.units[2].home_catchment,
            "name": "Agara Underpass",
            "depth_m": 0.20,
            "score": 68.0,
            "band": "barrier",
            "priority": "P2",
            "action": "barrier_closure",
            "action_label": "Barrier Close",
            "unit_class": "barrier",
            "underpass_poi_id": sess.units[2].underpass_poi_id,
            "ttp_min": 18.0,
            "assets": ["underpass"],
        }
        d1 = dispatch_alert(self.reg, bar_alert, sess.units, sess.dismissed, depths, "b1", 0.0)
        self.assertTrue(d1["ok"])
        self.assertEqual(d1["unit"]["state"], "PENDING_CLOSE")
        bid = d1["unit"]["unit_id"]

        # Veto succeeds at t=0.5 min (< 60s)
        v1 = veto_barrier(sess.units, bid, 0.5)
        self.assertTrue(v1["ok"])
        self.assertEqual(v1["unit"]["state"], "STANDBY")

        # Dispatch second barrier, lock after tick(2.0) -> veto fails
        bar_alert["alert_id"] = "ALT-BAR-2"
        d2 = dispatch_alert(self.reg, bar_alert, sess.units, sess.dismissed, depths, "b2", 1.0)
        self.assertTrue(d2["ok"])
        bid2 = d2["unit"]["unit_id"]
        evs = advance_fleet_clock(sess.units, 1.0, 2.0)
        self.assertTrue(any(e["action"] == "BARRIER_LOCKED" for e in evs))
        self.assertIn(bar_alert["id"], closed_barrier_nodes(sess.units))
        v2 = veto_barrier(sess.units, bid2, 3.0)
        self.assertFalse(v2["ok"])
        self.assertEqual(v2["reason"], "veto_not_pending")

        # Advance pump lifecycle to IDLE
        pump_alert = self._make_synthetic_pump_alerts(1)[0]
        dp = dispatch_alert(self.reg, pump_alert, sess.units, sess.dismissed, depths, "b2", 3.0)
        self.assertTrue(dp["ok"])
        events_cycle = advance_fleet_clock(sess.units, 3.0, 180.0)
        actions = [e["action"] for e in events_cycle]
        self.assertIn("UNIT_ARRIVED", actions)
        self.assertIn("SITE_COMPLETE", actions)
        self.assertIn("UNIT_RETURNED_IDLE", actions)

    def test_transit_corridors_under_severe_rain(self) -> None:
        tri = triage_scenario(self.reg, region="all", rain_mmhr=95.0, duration_min=60.0)
        tr = evaluate_transit_corridors(
            self.reg,
            tri["depths_by_catchment"],
            frozenset(),
            scenario_key="tr95",
            region="all",
        )
        self.assertGreaterEqual(len(tr["corridors"]), 5)
        statuses = {c["status"] for c in tr["corridors"]}
        # At 95 mm/hr some bus corridor must show FLOODED/DIVERTED/SUSPENDED action
        self.assertTrue(bool(statuses & {"DIVERTED", "SUSPENDED"}))


if __name__ == "__main__":
    unittest.main()
