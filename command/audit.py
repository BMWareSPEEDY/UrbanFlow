"""Append-only JSONL audit trail with fsync durability per event (D-16, §10)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from command.config import LOGS_DIR


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_hash(cfg: Dict[str, Any]) -> str:
    canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


class AuditLogger:
    """Thread-safe append-only JSONL logger backed by disk + per-session memory index."""

    def __init__(self, log_dir: str = LOGS_DIR) -> None:
        self._log_dir = log_dir
        os.makedirs(self._log_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        self._events: List[Dict[str, Any]] = []

    def _log_path(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return os.path.join(self._log_dir, f"audit-{day}.jsonl")

    def append(
        self,
        *,
        session_id: str,
        sim_ts: str,
        actor: str,
        action: str,
        token: str,
        msg: str,
        cfg_hash: str,
        alert_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        eta_min: Optional[float] = None,
        inter_catchment: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            entry: Dict[str, Any] = {
                "seq": self._seq,
                "ts": _utc_now_iso(),
                "sim": sim_ts,
                "session_id": session_id,
                "actor": actor,
                "action": action,
                "token": token,
                "msg": msg,
                "alert": alert_id,
                "unit": unit_id,
                "eta_min": eta_min,
                "inter_catchment": bool(inter_catchment),
                "config_hash": cfg_hash,
            }
            if details:
                entry["details"] = details

            line = json.dumps(entry, separators=(",", ":")) + "\n"
            path = self._log_path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

            self._events.append(entry)
            return entry

    def since(self, seq_after: int = 0, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                e
                for e in self._events
                if e["seq"] > seq_after and (session_id is None or e["session_id"] == session_id)
            ]

    @property
    def latest_seq(self) -> int:
        with self._lock:
            return self._seq
