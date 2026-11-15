"""Precompute exact float32 HydroGINE-v5 depth + TTP keyframe grid for UI slider ticks.

Usage:
  .venv/bin/python -m command.precompute_grid
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from command.config import DURATION_CLAMP, RAINFALL_CLAMP
from command.loader import get_registry


def main() -> None:
    t0 = time.perf_counter()
    reg = get_registry(load_model=True)
    if reg.predictor is None:
        raise RuntimeError("GNN predictor not loaded")

    rains = np.arange(5.0, 125.0, 5.0, dtype=np.float32)
    durs = np.array([15.0, 30.0, 60.0, 120.0], dtype=np.float32)

    out_path = Path(__file__).resolve().parent.parent / "data" / "command" / "precompute_grid.npz"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arrays: dict[str, np.ndarray] = {"rains": rains, "durs": durs}
    m0 = reg.predictor.members[0] if reg.predictor.members else None

    for ck, c in reg.catchments.items():
        n_nodes = len(c.node_ids)
        d_mat = np.zeros((len(rains), len(durs), n_nodes), dtype=np.float32)
        re_mat = np.zeros((len(rains), len(durs), n_nodes), dtype=np.float32)
        rm_mat = np.zeros((len(rains), len(durs), n_nodes), dtype=np.float32)

        for ri, r_val in enumerate(rains):
            rain = float(max(RAINFALL_CLAMP[0], min(RAINFALL_CLAMP[1], float(r_val))))
            for di, d_val in enumerate(durs):
                dur = float(max(DURATION_CLAMP[0], min(DURATION_CLAMP[1], float(d_val))))
                depths, _, _ = reg.predictor.predict(c.pyg_graph, rain, dur)
                d_mat[ri, di] = np.asarray(depths, dtype=np.float32)

                if m0 is not None:
                    early_rain = max(RAINFALL_CLAMP[0], rain * (0.2 + 0.8 * ((2.0 / 11.0) / 0.3)))
                    early_dur = max(DURATION_CLAMP[0], dur * 0.25)
                    mid_dur = max(DURATION_CLAMP[0], dur * 0.50)
                    d_early = np.asarray(m0.predict(c.pyg_graph, early_rain, early_dur)[0], dtype=np.float32)
                    d_mid = np.asarray(m0.predict(c.pyg_graph, rain, mid_dur)[0], dtype=np.float32)
                    d_end = np.asarray(m0.predict(c.pyg_graph, rain, dur)[0], dtype=np.float32)
                    denom = np.maximum(d_end, 1e-4)
                    r_early = np.clip(d_early / denom, 0.05, 1.0)
                    r_mid = np.clip(np.maximum(d_mid / denom, r_early), 0.15, 1.0)
                else:
                    r_early = np.full(n_nodes, 0.45, dtype=np.float32)
                    r_mid = np.full(n_nodes, 0.85, dtype=np.float32)
                re_mat[ri, di] = r_early
                rm_mat[ri, di] = r_mid

        arrays[f"depths_{ck}"] = d_mat
        arrays[f"r_early_{ck}"] = re_mat
        arrays[f"r_mid_{ck}"] = rm_mat
        print(f"Precomputed {ck}: shape={d_mat.shape}", flush=True)

    np.savez_compressed(out_path, **arrays)
    dt = time.perf_counter() - t0
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Saved {out_path} ({size_mb:.2f} MB) in {dt:.1f}s", flush=True)


if __name__ == "__main__":
    main()
