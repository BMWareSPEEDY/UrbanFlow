"""Named storm scenario presets for quick control-room testing."""
from __future__ import annotations

from typing import List, Dict, Any

SCENARIO_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "light_monsoon",
        "label": "Light Monsoon",
        "rain_mm_hr": 25,
        "duration_min": 60,
        "mode": "normal",
        "description": "Routine Bengaluru evening shower — minimal ponding, baseline calm state.",
    },
    {
        "id": "urban_squall",
        "label": "Urban Squall (Ref)",
        "rain_mm_hr": 50,
        "duration_min": 60,
        "mode": "normal",
        "description": "50 mm/hr reference regime (model MAE 2.44 cm, F1 90.8%).",
    },
    {
        "id": "severe_cloudburst",
        "label": "95 mm/hr Cloudburst",
        "rain_mm_hr": 95,
        "duration_min": 60,
        "mode": "red_alert",
        "description": "Peak arterial & underpass inundation exceeding the 12-pump municipal pool.",
    },
    {
        "id": "oct2024_extreme",
        "label": "Oct-2024 GKVK Extreme",
        "rain_mm_hr": 120,
        "duration_min": 90,
        "mode": "red_alert",
        "description": "Extreme cloudburst stress with Red-Alert conservative margin active.",
    },
]
