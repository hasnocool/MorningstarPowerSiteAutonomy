# Operator dashboard

The root page (`/`) is the human-facing view of PowerSite Autonomy. It is designed around the
questions an operator normally asks first instead of exposing the API structure directly.

## Overview

The default view answers:

1. **Is the site okay right now?** — current battery SOC, reserve risk, telemetry status, forecast
   confidence, and the conservative 72-hour SOC floor.
2. **What happens next?** — a 72-hour SOC uncertainty chart, expected solar/load, safe flexible
   energy, and no-solar autonomy.
3. **What needs attention?** — reserve warnings and the highest-priority read-only action-plan
   recommendations.
4. **What is Autonomy doing?** — latest persisted Shadow Autopilot posture and Adaptive World
   learning health.

The page automatically discovers configured sites and remembers the last selected site in the
browser. Successful API data refreshes once per minute while the page is visible.

## Forecast

The Forecast workspace separates operational energy questions from model details. It includes:

- expected solar, load, surplus, reserve risk, and unmet-load risk;
- P50 solar-vs-load trajectories;
- battery digital-twin capacity, health, temperature, resistance, and SOC confidence; and
- per-input forecast quality.

## Decisions

The Decisions workspace explains Shadow Autopilot rather than presenting its JSON contract. It
shows the conservative, balanced, and maximum-utilization alternatives side by side, the active
policy guardrails, recent shadow actions, and the counterfactual decision scorecard.

Normal dashboard refreshes only read the latest persisted plan. They do **not** create new plans.
`Run fresh shadow cycle` is an explicit operator action that calls the existing read-only Shadow
Autopilot tick endpoint. It may create local planning/evaluation records, but it cannot execute site
hardware.

## Policy Lab

The Policy Lab workspace translates v0.8 decision intelligence into operator language. It shows
the current champion shadow policy, bounded dynamic reserve, replay depth, policy improvements,
non-dominated Pareto choices, regret attribution, decision-sensitive learning priorities, and the
latest champion/challenger tournament.

The interface deliberately distinguishes **base reserve** from **effective planning reserve** so a
learned recommendation cannot be mistaken for a controller or BMS protection setting. Policy
promotion changes only non-executable Shadow Autopilot preferences.

## Learning

The Learning workspace translates Adaptive World state into operator-oriented concepts:

- active champion world model;
- weather-model skill and learned weights;
- battery degradation evidence and data depth; and
- probabilistic change evidence.

Missing evidence is shown as unavailable or insufficient instead of being converted to a synthetic
value.

## Diagnostics

Raw API responses remain available for troubleshooting, but they are intentionally moved to the
Diagnostics workspace. Service health, data freshness, a selectable JSON inspector, and copy action
are available without forcing ordinary users to interpret raw response objects.

## Frontend design

The dashboard is dependency-free: HTML, CSS, SVG charts, and JavaScript are served directly by the
FastAPI process. There is no CDN or Node build step. The layout adapts from a desktop sidebar to a
mobile horizontal workspace selector and keeps the physical-hardware read-only boundary visible.
