from __future__ import annotations

from powersite_autonomy.dashboard import dashboard_html


def test_dashboard_prioritizes_operator_workflow_over_raw_json() -> None:
    html = dashboard_html()
    assert "Operator overview" in html
    assert "Needs attention" in html
    assert "72-hour battery outlook" in html
    assert "Current decision posture" in html
    assert "Raw evidence" in html
    assert html.index("Operator overview") < html.index("Raw evidence")


def test_dashboard_has_site_discovery_and_responsive_navigation() -> None:
    html = dashboard_html()
    assert 'id="siteSelect"' in html
    assert 'data-view="overview"' in html
    assert 'data-view="forecast"' in html
    assert 'data-view="decisions"' in html
    assert 'data-view="policy"' in html
    assert 'data-view="learning"' in html
    assert 'data-view="diagnostics"' in html
    assert "@media (max-width: 820px)" in html


def test_dashboard_uses_read_only_refresh_paths() -> None:
    html = dashboard_html()
    assert "/autopilot/plans?limit=1" in html
    assert "/autopilot/actions?limit=20" in html
    assert "/autopilot/plan?" not in html
    assert 'method: "POST"' in html
    assert "Run fresh shadow cycle" in html


def test_dashboard_surfaces_safety_boundary_and_core_intelligence() -> None:
    html = dashboard_html()
    assert "Read-only boundary" in html
    assert "does not control site hardware" in html
    assert "Reserve risk" in html
    assert "Safe flexible energy" in html
    assert "Shadow Autopilot" in html
    assert "Adaptive Policy Lab" in html
    assert "Dynamic reserve" in html
    assert "What the site is learning" in html
    assert "Weather model skill" in html


def test_dashboard_has_no_external_frontend_dependency() -> None:
    html = dashboard_html()
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    assert "https://cdn" not in html
