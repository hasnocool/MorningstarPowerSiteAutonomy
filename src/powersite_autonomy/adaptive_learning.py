# src/powersite_autonomy/adaptive_learning.py
from .adaptive_model_learning import (
    build_battery_degradation_snapshot,
    build_uncertainty_calibration,
    decide_model_promotion,
    detect_probabilistic_change_points,
    evaluate_world_model_candidates,
)
from .adaptive_site_learning import (
    build_seasonal_overlay,
    discover_load_events,
    infer_managed_load_completion,
)
from .adaptive_weather_learning import (
    build_weather_skill_summary,
    score_weather_run,
    series_map,
)

__all__ = [
    "build_battery_degradation_snapshot",
    "build_seasonal_overlay",
    "build_uncertainty_calibration",
    "build_weather_skill_summary",
    "decide_model_promotion",
    "detect_probabilistic_change_points",
    "discover_load_events",
    "evaluate_world_model_candidates",
    "infer_managed_load_completion",
    "score_weather_run",
    "series_map",
]
