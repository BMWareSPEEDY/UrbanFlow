"""Gate A unit tests for consequence triage, dedup clustering, and latency."""
from __future__ import annotations

import time
import unittest
import numpy as np

from command.config import ASSET_WEIGHT, TRIAGE_WEIGHTS
from command.loader import get_registry
from command.triage import (
    _INFER_CACHE,
    classify_action,
    classify_band,
    classify_priority,
    compute_node_score,
    compute_scores_vectorized,
    inspect_single_node,
    triage_scenario,
)


class TestTriageGateA(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = get_registry(load_model=True)

    def test_golden_score_exact(self) -> None:
        # depth=0.22 -> S=(0.22-0.05)/0.35 = 0.485714
        # underpass -> A=1.0
        # depth>0.18 -> 0.45 + 0.35*(0.22/0.30) + 0.20*0.50 = 0.45 + 0.256667 + 0.10 = 0.806667
        # N = 0.60
        s = (0.22 - 0.05) / 0.35
        a = ASSET_WEIGHT["underpass"]
        v = 0.45 + 0.35 * (0.22 / 0.30) + 0.20 * 0.50
        n = 0.60
        expected = round(
            100.0
            * (
                TRIAGE_WEIGHTS["severity"] * s
                + TRIAGE_WEIGHTS["asset"] * a
                + TRIAGE_WEIGHTS["vulnerability"] * v
                + TRIAGE_WEIGHTS["network"] * n
            ),
            1,
        )
        got = compute_node_score(0.22, "underpass", 0.50, 0.60)
        self.assertAlmostEqual(got, expected, delta=0.01)

    def test_vectorized_matches_scalar(self) -> None:
        rng = np.random.default_rng(42)
        n = 200
        depths = rng.uniform(0.0, 0.8, n)
        assets = rng.choice(list(ASSET_WEIGHT.keys()), size=n)
        asset_w = np.array([ASSET_WEIGHT[a] for a in assets], dtype=np.float64)
        sinks = rng.uniform(0.0, 1.0, n)
        bcs = rng.uniform(0.0, 1.0, n)
        vec = compute_scores_vectorized(depths, asset_w, sinks, bcs)
        for i in range(n):
            sc = compute_node_score(float(depths[i]), str(assets[i]), float(sinks[i]), float(bcs[i]))
            self.assertAlmostEqual(float(vec[i]), sc, places=5)

    def test_consequence_beats_raw_depth_on_critical_asset(self) -> None:
        # 0.20 m hospital beats 0.40 m residential cul-de-sac
        hospital_score = compute_node_score(0.20, "hospital", sink_ratio=0.5, betweenness=0.8)
        lane_score = compute_node_score(0.40, "street", sink_ratio=0.0, betweenness=0.0)
        self.assertGreater(hospital_score, lane_score)

    def test_threshold_ladder_modes(self) -> None:
        self.assertEqual(classify_band(0.07, "normal"), "dry")
        self.assertEqual(classify_band(0.11, "normal"), "watch")
        self.assertEqual(classify_band(0.11, "red_alert"), "barrier")
        self.assertEqual(classify_band(0.27, "normal"), "barrier")
        self.assertEqual(classify_band(0.27, "red_alert"), "pump")
        self.assertEqual(classify_priority(72.0, "pump"), "P1")
        self.assertEqual(classify_priority(25.0, "watch"), "suppressed")
        self.assertEqual(classify_action("barrier", "underpass", ["underpass"]), ("barrier_closure", "Barrier Close", "barrier"))
        self.assertEqual(classify_action("barrier", "hospital", ["hospital"]), ("pump_dispatch", "Pump Dispatch", "pump"))

    def test_determinism_dedup_and_latency_gate_a(self) -> None:
        # Clear cache and test cold CPU 5-catchment triage speed (< 400 ms)
        _INFER_CACHE.clear()
        t0 = time.perf_counter()
        res1 = triage_scenario(self.reg, region="all", rain_mmhr=95.0, duration_min=60.0, mode="normal")
        cold_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(cold_ms, 400.0, f"5-catchment triage took {cold_ms:.1f} ms")

        res2 = triage_scenario(self.reg, region="all", rain_mmhr=95.0, duration_min=60.0, mode="normal")
        self.assertEqual(
            [a["alert_id"] for a in res1["alerts"]],
            [a["alert_id"] for a in res2["alerts"]],
        )
        self.assertGreater(res1["stats"]["raw_eligible"], res1["stats"]["dedup_alerts"])
        self.assertGreater(len(res1["alerts"]), 5)
        self.assertGreater(res1["stats"]["blocked_km"], 0.0)
        self.assertIn("ttp_min", res1["alerts"][0])
        self.assertEqual(res1["alerts"][0]["ttp_source"], "playback")

        # Inspect any arbitrary node even if dry
        hsr_first = self.reg.catchments["hsr"].node_ids[0]
        inspected = inspect_single_node(self.reg, hsr_first, rain_mmhr=25.0, duration_min=60.0)
        self.assertIsNotNone(inspected)
        self.assertEqual(inspected["id"], hsr_first)


if __name__ == "__main__":
    unittest.main()
