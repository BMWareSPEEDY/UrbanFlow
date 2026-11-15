"""Explicit request validation helpers for the Command API."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from command.config import (
    CATCHMENTS,
    DEFAULT_FLEET,
    DURATION_CLAMP,
    FLEET_LIMITS,
    RAINFALL_CLAMP,
    THRESHOLDS,
    VEHICLE_PROFILES,
)

DISMISS_REASONS = frozenset(
    {"false_alarm", "already_handled", "insufficient_confidence"}
)


class ValidationError(ValueError):
    """Structured client input validation error returned as HTTP 400."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message

    def to_dict(self) -> dict:
        return {"error": "validation_error", "field": self.field, "message": self.message}


def validate_float(
    val: Any,
    field: str,
    lo: float,
    hi: float,
    default: float,
) -> float:
    if val is None:
        return default
    try:
        f = float(val)
    except (TypeError, ValueError) as exc:
        raise ValidationError(field, f"must be numeric, got {val!r}") from exc
    if not math.isfinite(f):
        raise ValidationError(field, "must be finite")
    if f < lo or f > hi:
        raise ValidationError(field, f"must be between {lo} and {hi}, got {f}")
    return f


def validate_int_bound(
    val: Any,
    field: str,
    lo: int,
    hi: int,
    default: int,
) -> int:
    if val is None:
        return default
    if isinstance(val, bool):
        raise ValidationError(field, "must be an integer, not bool")
    try:
        iv = int(val)
    except (TypeError, ValueError) as exc:
        raise ValidationError(field, f"must be an integer, got {val!r}") from exc
    if str(val).strip() != str(iv) and not isinstance(val, int):
        # Reject floats like 1.5 disguised in JSON
        if isinstance(val, float) and not val.is_integer():
            raise ValidationError(field, f"must be whole integer, got {val!r}")
    if iv < lo or iv > hi:
        raise ValidationError(field, f"must be between {lo} and {hi}, got {iv}")
    return iv


def validate_region(val: Any, default: str = "all") -> str:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s != "all" and s not in CATCHMENTS:
        raise ValidationError("region", f"unknown catchment {val!r}")
    return s


def validate_mode(val: Any, default: str = "normal") -> str:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s not in THRESHOLDS:
        raise ValidationError("mode", f"must be one of {sorted(THRESHOLDS)}")
    return s


def validate_session_payload(data: dict) -> dict:
    operator = str(data.get("operator") or "duty-officer").strip()[:64]
    if not operator:
        operator = "duty-officer"

    region = validate_region(data.get("region"), "all")
    raw_rain = data.get("rain_mmhr", data.get("rainfall_mmhr", data.get("rain")))
    rain = validate_float(raw_rain, "rain_mmhr", RAINFALL_CLAMP[0], RAINFALL_CLAMP[1], 45.0)
    raw_dur = data.get("duration_min", data.get("duration"))
    dur = validate_float(raw_dur, "duration_min", DURATION_CLAMP[0], DURATION_CLAMP[1], 60.0)
    mode = validate_mode(data.get("mode"), "normal")

    fleet_in = data.get("fleet") if isinstance(data.get("fleet"), dict) else data
    fleet = {
        "pumps": validate_int_bound(
            fleet_in.get("pumps"), "pumps", *FLEET_LIMITS["pumps"], DEFAULT_FLEET["pumps"]
        ),
        "barriers": validate_int_bound(
            fleet_in.get("barriers"),
            "barriers",
            *FLEET_LIMITS["barriers"],
            DEFAULT_FLEET["barriers"],
        ),
        "wardens": validate_int_bound(
            fleet_in.get("wardens"),
            "wardens",
            *FLEET_LIMITS["wardens"],
            DEFAULT_FLEET["wardens"],
        ),
    }

    return {
        "operator": operator,
        "region": region,
        "rain_mmhr": round(rain, 1),
        "duration_min": round(dur, 1),
        "mode": mode,
        "fleet": fleet,
    }


def validate_vehicle(val: Any, default: str = "pump_truck") -> str:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s not in VEHICLE_PROFILES:
        raise ValidationError("vehicle", f"must be one of {sorted(VEHICLE_PROFILES)}")
    return s


def validate_dismiss_reason(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s not in DISMISS_REASONS:
        raise ValidationError(
            "reason", f"must be one of {sorted(DISMISS_REASONS)}"
        )
    return s
