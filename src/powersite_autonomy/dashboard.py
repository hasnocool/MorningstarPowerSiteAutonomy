from __future__ import annotations

from .dashboard_css import DASHBOARD_CSS
from .dashboard_script import DASHBOARD_SCRIPT


DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>PowerSite Autonomy</title>
<style>
__DASHBOARD_CSS__
</style>
</head>
<body>
<div class="shell">
<header class="topbar">
  <div class="brand">
    <div class="logo" aria-hidden="true">PA</div>
    <div class="brand-copy">
      <div class="brand-title">PowerSite Autonomy</div>
      <div class="brand-subtitle">Read-only energy intelligence</div>
    </div>
  </div>
  <div class="top-actions">
    <label class="small muted" for="siteSelect">Site</label>
    <select id="siteSelect" class="site-select" aria-label="Select power site">
      <option>Loading sites…</option>
    </select>
    <button id="refreshButton" class="soft-button" type="button">
      <span class="refresh-label">Refresh</span> ↻
    </button>
  </div>
</header>
<div class="layout">
  <aside class="sidebar" aria-label="Dashboard sections">
    <div class="nav-title">Workspace</div>
    <button class="nav-button active" data-view="overview" type="button">
      <span class="nav-icon">●</span> Overview
    </button>
    <button class="nav-button" data-view="forecast" type="button">
      <span class="nav-icon">⌁</span> Forecast
    </button>
    <button class="nav-button" data-view="decisions" type="button">
      <span class="nav-icon">◇</span> Decisions
    </button>
    <button class="nav-button" data-view="policy" type="button">
      <span class="nav-icon">↯</span> Policy Lab
    </button>
    <button class="nav-button" data-view="learning" type="button">
      <span class="nav-icon">◎</span> Learning
    </button>
    <button class="nav-button" data-view="diagnostics" type="button">
      <span class="nav-icon">⋯</span> Diagnostics
    </button>
    <div class="read-only">
      <strong>Read-only boundary</strong><br>
      This interface forecasts, explains, and proposes. It does not control site hardware.
    </div>
  </aside>
  <main class="content">
    <section class="view active" id="view-overview">
      <div class="page-header">
        <div>
          <div class="eyebrow">Operator overview</div>
          <h1 id="siteTitle">Power site</h1>
          <p class="muted" id="summaryLine">Loading the latest site intelligence…</p>
        </div>
        <div class="status-row" id="statusRow" aria-live="polite"></div>
      </div>
      <div class="grid metrics" id="metricGrid"></div>
      <div class="section-spacer"></div>
      <div class="grid two-col">
        <article class="card">
          <div class="card-header">
            <div>
              <h2>72-hour battery outlook</h2>
              <p class="small muted">Expected state of charge with uncertainty</p>
            </div>
            <div class="legend">
              <span class="legend-item">
                <span class="legend-swatch"></span>P50 SOC
              </span>
              <span class="legend-item">
                <span class="legend-swatch blue"></span>P10–P90
              </span>
            </div>
          </div>
          <div class="chart-wrap" id="socChart"></div>
        </article>
        <article class="card">
          <div class="card-header">
            <div>
              <h2>Needs attention</h2>
              <p class="small muted">Highest-value information first</p>
            </div>
          </div>
          <div class="attention-list" id="attentionList"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header">
            <div>
              <h2>Current decision posture</h2>
              <p class="small muted">Latest Shadow Autopilot plan, not executable</p>
            </div>
          </div>
          <div id="postureCard"></div>
        </article>
        <article class="card">
          <div class="card-header">
            <div>
              <h2>Learning health</h2>
              <p class="small muted">How much the site model knows about itself</p>
            </div>
          </div>
          <div id="learningHealth"></div>
        </article>
      </div>
    </section>

    <section class="view" id="view-forecast">
      <div class="page-header">
        <div>
          <div class="eyebrow">Forecast</div>
          <h1>Energy outlook</h1>
          <p class="muted">Solar, demand, reserve risk, and battery trajectory.</p>
        </div>
      </div>
      <div class="grid metrics" id="forecastMetrics"></div>
      <div class="section-spacer"></div>
      <article class="card">
        <div class="card-header">
          <div>
            <h2>Solar generation vs. demand</h2>
            <p class="small muted">P50 hourly forecast</p>
          </div>
          <div class="legend">
            <span class="legend-item">
              <span class="legend-swatch"></span>Solar
            </span>
            <span class="legend-item">
              <span class="legend-swatch warn"></span>Load
            </span>
          </div>
        </div>
        <div class="chart-wrap" id="powerChart"></div>
      </article>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Battery model</h2></div>
          <div id="batteryDetails"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Forecast confidence</h2></div>
          <div id="forecastConfidence"></div>
        </article>
      </div>
    </section>

    <section class="view" id="view-decisions">
      <div class="page-header">
        <div>
          <div class="eyebrow">Decision support</div>
          <h1>Shadow Autopilot</h1>
          <p class="muted">Compare strategies and understand proposed actions.</p>
        </div>
        <button id="runShadowButton" class="primary-button" type="button">
          Run fresh shadow cycle
        </button>
      </div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Plan alternatives</h2></div>
          <div class="table-wrap" id="alternativeTable"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Policy guardrails</h2></div>
          <div id="policyCard"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Latest proposed actions</h2></div>
          <div class="action-list" id="shadowActions"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Decision scorecard</h2></div>
          <div id="autopilotScore"></div>
        </article>
      </div>
    </section>

    <section class="view" id="view-policy">
      <div class="page-header">
        <div>
          <div class="eyebrow">Policy intelligence</div>
          <h1>Adaptive Policy Lab</h1>
          <p class="muted">
            Which shadow strategy is working best, and why? Nothing here executes hardware.
          </p>
        </div>
      </div>
      <div class="grid metrics" id="policyMetrics"></div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header">
            <div>
              <h2>Champion policy</h2>
              <p class="small muted">Current globally preferred shadow strategy</p>
            </div>
          </div>
          <div id="policyChampion"></div>
        </article>
        <article class="card">
          <div class="card-header">
            <div>
              <h2>Dynamic reserve</h2>
              <p class="small muted">Advisory planning reserve, bounded by operator limits</p>
            </div>
          </div>
          <div id="dynamicReserve"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Pareto policy frontier</h2></div>
          <div class="table-wrap" id="policyFrontier"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Regret decomposition</h2></div>
          <div class="learning-list" id="policyRegret"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Decision-sensitive priorities</h2></div>
          <div class="learning-list" id="decisionSensitivity"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Latest tournament</h2></div>
          <div id="policyTournament"></div>
        </article>
      </div>
    </section>

    <section class="view" id="view-learning">
      <div class="page-header">
        <div>
          <div class="eyebrow">Adaptive intelligence</div>
          <h1>What the site is learning</h1>
          <p class="muted">Weather skill, model confidence, battery trends, and change evidence.</p>
        </div>
      </div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>World model</h2></div>
          <div id="worldModel"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Weather model skill</h2></div>
          <div id="weatherSkill"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Battery learning</h2></div>
          <div id="adaptiveBattery"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Recent change evidence</h2></div>
          <div class="learning-list" id="changeEvidence"></div>
        </article>
      </div>
    </section>

    <section class="view" id="view-diagnostics">
      <div class="page-header">
        <div>
          <div class="eyebrow">Diagnostics</div>
          <h1>Raw evidence</h1>
          <p class="muted">API details are available here without dominating the main workflow.</p>
        </div>
      </div>
      <div class="grid equal-col">
        <article class="card">
          <div class="card-header"><h2>Service health</h2></div>
          <div id="healthDetails"></div>
        </article>
        <article class="card">
          <div class="card-header"><h2>Data freshness</h2></div>
          <div id="freshnessDetails"></div>
        </article>
      </div>
      <div class="section-spacer"></div>
      <article class="card">
        <div class="card-header"><h2>Inspect API data</h2></div>
        <div class="raw-controls">
          <select id="rawSelect" class="site-select" aria-label="Select raw dataset"></select>
          <button id="copyRawButton" class="soft-button" type="button">Copy JSON</button>
        </div>
        <pre class="raw-output" id="rawOutput">Loading…</pre>
      </article>
    </section>
  </main>
</div>
</div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>
__DASHBOARD_SCRIPT__
</script>
</body>
</html>"""


def dashboard_html() -> str:
    return (
        DASHBOARD_TEMPLATE.replace("__DASHBOARD_CSS__", DASHBOARD_CSS)
        .replace("__DASHBOARD_SCRIPT__", DASHBOARD_SCRIPT)
    )
