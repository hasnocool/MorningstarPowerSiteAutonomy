from __future__ import annotations

from .dashboard_script_core import DASHBOARD_SCRIPT_CORE
from .dashboard_script_overview import DASHBOARD_SCRIPT_OVERVIEW
from .dashboard_script_policy import DASHBOARD_SCRIPT_POLICY
from .dashboard_script_runtime import DASHBOARD_SCRIPT_RUNTIME

DASHBOARD_SCRIPT = "\n".join(
    (
        DASHBOARD_SCRIPT_CORE,
        DASHBOARD_SCRIPT_OVERVIEW,
        DASHBOARD_SCRIPT_POLICY,
        DASHBOARD_SCRIPT_RUNTIME,
    )
)
