"""Thread-safe per-session operational state store for UrbanFLOW Command."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from command.fleet import FleetUnit, build_initial_fleet, format_sim_ts
from command.loader import CommandRegistry


def _compute_cfg_hash(cfg: dict) -> str:
    raw = json.dumps(cfg, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class CommandSession:
    """Isolated operator session holding setup fleet, scenario params, clock, and locks."""

    session_id: str
    operator: str
    region: str
    rain_mmhr: float
    duration_min: float
    mode: str
    fleet_config: dict
    cfg_hash: str
    units: List[FleetUnit]
    sim_clock_min: float = 0.0
    created_at: float = field(default_factory=time.time)
    dismissed: Dict[str, dict] = field(default_factory=dict)
    cleared_nodes: Dict[str, float] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def sim_ts(self) -> str:
        return format_sim_ts(self.sim_clock_min)


class SessionStore:
    """Thread-safe registry mapping `session_id -> CommandSession`.

    Bounded so a long demo or a fuzzing run cannot grow memory without limit;
    the oldest session is evicted once `max_sessions` is reached.
    """

    def __init__(self, max_sessions: int = 64) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, CommandSession] = {}
        self._evicted: Dict[str, float] = {}
        self._max_sessions = max(1, int(max_sessions))

    def create(self, reg: CommandRegistry, validated_cfg: dict) -> CommandSession:
        sid = f"SES-{uuid.uuid4().hex[:8].upper()}"
        units = build_initial_fleet(reg, validated_cfg["fleet"])
        sess = CommandSession(
            session_id=sid,
            operator=validated_cfg["operator"],
            region=validated_cfg["region"],
            rain_mmhr=validated_cfg["rain_mmhr"],
            duration_min=validated_cfg["duration_min"],
            mode=validated_cfg["mode"],
            fleet_config=dict(validated_cfg["fleet"]),
            cfg_hash=_compute_cfg_hash(validated_cfg),
            units=units,
        )
        with self._lock:
            while len(self._sessions) >= self._max_sessions:
                oldest = min(self._sessions.values(), key=lambda s: s.created_at)
                self._sessions.pop(oldest.session_id, None)
                self._evicted[oldest.session_id] = time.time()
                while len(self._evicted) > 256:
                    first_k = next(iter(self._evicted))
                    self._evicted.pop(first_k, None)
            self._sessions[sid] = sess
        return sess

    def get(self, session_id: str) -> Optional[CommandSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def is_evicted(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._evicted

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


_STORE = SessionStore()


def get_session_store() -> SessionStore:
    return _STORE
