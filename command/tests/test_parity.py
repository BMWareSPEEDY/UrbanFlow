"""Parity tests for command.loader against frozen graphs, SWMM truth, and V4 predictor."""
from __future__ import annotations

import unittest
import numpy as np
import torch

from command.config import CATCHMENTS, EXPECTED_TOTAL_EDGES, EXPECTED_TOTAL_NODES
from command.loader import get_registry
from core.production_v4 import EnsembleFloodPredictorV4


class TestLoaderParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = get_registry(load_model=True)

    def test_node_and_edge_counts(self) -> None:
        self.assertEqual(self.reg.total_nodes(), EXPECTED_TOTAL_NODES)
        self.assertEqual(self.reg.total_edges(), EXPECTED_TOTAL_EDGES)
        for key, meta in CATCHMENTS.items():
            c = self.reg.catchments[key]
            self.assertEqual(len(c.node_ids), meta["expected_nodes"], key)
            self.assertEqual(len(c.edges), meta["expected_edges"], key)
            self.assertEqual(c.graph.number_of_nodes(), meta["expected_nodes"], key)
            self.assertEqual(c.graph.number_of_edges(), meta["expected_edges"], key)

    def test_load_speed_under_budget(self) -> None:
        self.assertLess(self.reg.load_sec, 10.0)

    def test_depots_are_valid_high_ground_scc(self) -> None:
        self.assertEqual(len(self.reg.depots), 6)
        for depot in self.reg.depots:
            found = self.reg.find_node(depot["node_id"])
            self.assertIsNotNone(found, depot["id"])
            c, idx = found
            self.assertEqual(c.key, depot["region"])
            self.assertIn(depot["node_id"], c.scc_nodes)
            self.assertFalse(bool(c.is_basement[idx]), depot["id"])

    def test_edge_geometries_and_speeds(self) -> None:
        for key, c in self.reg.catchments.items():
            sample = c.edges[:50]
            self.assertGreater(len(sample), 10)
            for e in sample:
                self.assertGreater(e.length_m, 0.0)
                self.assertGreater(e.t0_sec, 0.0)
                self.assertGreaterEqual(len(e.coords), 2)
                for lng, lat in e.coords:
                    self.assertTrue(77.4 <= lng <= 77.95, (key, lng))
                    self.assertTrue(12.75 <= lat <= 13.15, (key, lat))

    def test_predictor_exact_parity(self) -> None:
        ref = EnsembleFloodPredictorV4(device=torch.device("cpu"))
        for key in CATCHMENTS:
            pyg = self.reg.catchments[key].pyg_graph
            got, _, _ = self.reg.predictor.predict(pyg, 50.0, 60.0)
            exp, _, _ = ref.predict(pyg, 50.0, 60.0)
            max_diff = float(np.max(np.abs(got - exp)))
            self.assertLess(max_diff, 1e-5, f"{key} drift={max_diff}")

    def test_swmm_interpolation_and_snap(self) -> None:
        hsr = self.reg.catchments["hsr"]
        for rain in (20, 50, 80, 100, 120):
            self.assertIn(rain, hsr.swmm_truth)
            self.assertEqual(len(hsr.swmm_truth[rain]), len(hsr.node_ids))
        poi = self.reg.all_pois[0]
        snapped = self.reg.snap_coord(poi["lng"], poi["lat"], poi["catchment"], max_dist_m=100.0)
        self.assertIsNotNone(snapped)
        self.assertEqual(snapped[1], poi["node_id"])


if __name__ == "__main__":
    unittest.main()
