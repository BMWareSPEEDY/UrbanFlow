"""Gate B unit tests for flood-aware routing, impassable corridors, and latency."""
from __future__ import annotations

import math
import time
import unittest
import numpy as np

from command.config import INTER_CATCHMENT_PENALTY_MIN
from command.loader import get_registry
from command.routing import passability_factor, resolve_endpoint, route_nodes


class TestRoutingGateB(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = get_registry(load_model=False)

    def _zero_depths(self) -> dict[str, np.ndarray]:
        return {
            k: np.zeros(len(c.node_ids), dtype=np.float32)
            for k, c in self.reg.catchments.items()
        }

    def test_passability_thresholds(self) -> None:
        self.assertEqual(passability_factor(0.03, "pump_truck"), 1.0)
        self.assertGreater(passability_factor(0.15, "pump_truck"), 1.0)
        self.assertTrue(math.isinf(passability_factor(0.25, "pump_truck")))
        self.assertTrue(math.isfinite(passability_factor(0.26, "ambulance")))
        self.assertTrue(math.isinf(passability_factor(0.20, "warden")))

    def test_intra_catchment_endpoints_and_flood_cut(self) -> None:
        hsr = self.reg.catchments["hsr"]
        scc_list = [n for n in hsr.node_ids if n in hsr.scc_nodes]
        orig, dest = scc_list[0], scc_list[len(scc_list) // 2]

        depths = self._zero_depths()
        dry_res = route_nodes(self.reg, orig, dest, depths, vehicle="pump_truck", scenario_key="dry")
        self.assertTrue(dry_res["reachable"])
        self.assertFalse(dry_res["inter_catchment"])
        self.assertEqual(dry_res["safe"]["path_nodes"][0], orig)
        self.assertEqual(dry_res["safe"]["path_nodes"][-1], dest)
        self.assertGreater(dry_res["safe"]["eta_min"], 0.0)

        # Flood every node along the dry path's midpoint? Better: flood dest itself to 0.50m
        flooded = self._zero_depths()
        flooded["hsr"][hsr.node_idx[dest]] = 0.50
        blk = route_nodes(self.reg, orig, dest, flooded, vehicle="pump_truck", scenario_key="cut")
        self.assertFalse(blk["reachable"])
        self.assertEqual(blk["reason"], "flood_blocked")
        self.assertFalse(blk["safe"]["reachable"])
        self.assertTrue(blk["standard"]["reachable"])
        self.assertGreaterEqual(blk["standard"]["flooded_crossings"], 1)

        # Dewatering pump staging approaches dry perimeter when terminal node itself is submerged
        staged = route_nodes(
            self.reg,
            orig,
            dest,
            flooded,
            vehicle="pump_truck",
            scenario_key="cut",
            allow_terminal_staging=True,
        )
        self.assertTrue(staged["reachable"])
        self.assertGreaterEqual(staged["safe"]["eta_min"], 1.0)

    def test_detour_and_closed_barrier_effect(self) -> None:
        hsr = self.reg.catchments["hsr"]
        scc_list = [n for n in hsr.node_ids if n in hsr.scc_nodes]
        orig, dest = scc_list[5], scc_list[len(scc_list) // 3]
        depths = self._zero_depths()
        dry = route_nodes(self.reg, orig, dest, depths, vehicle="pump_truck", scenario_key="b0")
        self.assertTrue(dry["reachable"])
        path = dry["standard"]["path_nodes"]
        if len(path) >= 4:
            mid = path[len(path) // 2]
            bar_res = route_nodes(
                self.reg,
                orig,
                dest,
                depths,
                vehicle="pump_truck",
                closed_barriers=frozenset({mid}),
                scenario_key="b0",
            )
            if bar_res["reachable"]:
                self.assertNotIn(mid, bar_res["safe"]["path_nodes"])

    def test_inter_catchment_penalty_stub(self) -> None:
        d_hsr = next(d for d in self.reg.depots if d["region"] == "hsr")["node_id"]
        d_krm = next(d for d in self.reg.depots if d["region"] == "koramangala")["node_id"]
        depths = self._zero_depths()
        res = route_nodes(self.reg, d_hsr, d_krm, depths, vehicle="pump_truck", scenario_key="x0")
        self.assertTrue(res["reachable"])
        self.assertTrue(res["inter_catchment"])
        self.assertEqual(res["penalty_min"], INTER_CATCHMENT_PENALTY_MIN)
        self.assertIsNotNone(res["stub_coords"])
        self.assertGreater(res["safe"]["eta_min"], INTER_CATCHMENT_PENALTY_MIN)

    def test_coord_snap_and_100_routes_under_250ms(self) -> None:
        hsr = self.reg.catchments["hsr"]
        resolved = resolve_endpoint(self.reg, {"lat": 12.9125, "lng": 77.6440}, region_hint="hsr")
        self.assertIsNotNone(resolved)
        depths = self._zero_depths()
        scc_list = [n for n in hsr.node_ids if n in hsr.scc_nodes]
        pairs = [(scc_list[i % 20], scc_list[(i * 17 + 31) % 300]) for i in range(100)]

        # Warm the cached digraph once (matches cached scenario routing benchmark)
        route_nodes(self.reg, pairs[0][0], pairs[0][1], depths, vehicle="pump_truck", scenario_key="bench")
        t0 = time.perf_counter()
        for u, v in pairs:
            route_nodes(self.reg, u, v, depths, vehicle="pump_truck", scenario_key="bench")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 250.0, f"100 routes took {elapsed_ms:.1f} ms")


if __name__ == "__main__":
    unittest.main()
