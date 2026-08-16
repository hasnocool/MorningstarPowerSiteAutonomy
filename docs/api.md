# API

All planning endpoints are read-only with respect to power hardware. They return forecasts,
recommendations, proposed schedules, or shadow decisions; they do not execute them.

## Forecast

`GET /v1/sites/{site_uid}/forecast?hours=72`

Returns hourly P10/P50/P90 values for solar power, load power, conservative instantaneous
surplus, and battery SOC plus expected energy, reserve/unmet-load risk, autonomy, safe
discretionary energy, effective battery capacity, model versions, confidence, and input quality.

Horizons are bounded from 1 to 168 hours.

## Scenarios

`POST /v1/sites/{site_uid}/scenarios`

Supported changes include fixed-power load windows, advisory external-source windows, array
watts, battery capacity Wh, and reserve percent. Baseline and scenario use the same random seed so
risk deltas are paired rather than dominated by unrelated Monte Carlo noise.

## Historical calibration

`GET /v1/sites/{site_uid}/calibration`

Returns the most recent learned site calibration.

`POST /v1/sites/{site_uid}/calibration/refresh?days=30`

Reads normalized Morningstar system history and historical weather concurrently and persists a
new calibration. The response includes sample counts and notes describing fallbacks.

`GET /v1/sites/{site_uid}/calibrations?limit=20`

Returns calibration history. This is also the source for usable-capacity/resistance trends and
Shadow Autopilot model-epoch change detection.

## Forecast scoring

`GET /v1/sites/{site_uid}/forecast-score?limit=20`

Compares persisted forecast points with later Morningstar observations. Metrics include MAE,
bias, and P10-P90 empirical coverage for PV, load, and SOC.

## Flexible-load scheduling

`POST /v1/sites/{site_uid}/schedule`

Schedules one explicit flexible/interruptible load request into lower-risk forecast windows. The
v0.3 Shadow Autopilot builds on this primitive and carries accepted managed-load schedules forward
so multiple loads compete for one energy budget.

## PV/battery optimizer

`POST /v1/sites/{site_uid}/optimize`

Performs a bounded grid search over PV watts and battery Wh, ranks candidates by risk and optional
cost, and returns a compact Pareto-like frontier.

## Auxiliary-energy planner

`POST /v1/sites/{site_uid}/auxiliary-plan`

Quantifies the minimum advisory external energy needed to reach a target reserve-risk probability.
The response always remains non-executable; Autonomy never starts or controls an external source.

## Digital twin

`GET /v1/sites/{site_uid}/digital-twin`

Returns the current battery twin, resolved PV arrays, latest calibration, and the upstream
Morningstar component graph and energy ledger.

## Sentinel risk feed

`GET /v1/sites/{site_uid}/risk-feed?hours=72`

Returns a compact reserve-risk payload suitable for Sentinel consumption. If
`AUTONOMY_RISK_FEED_SECRET` is set, the canonical payload is HMAC-SHA256 signed.

## Action plan

`GET /v1/sites/{site_uid}/action-plan?hours=72`

Returns the v0.2 machine-readable read-only recommendation surface.

# Shadow Autopilot API

Every Shadow Autopilot response is advisory. Plans/actions contain `read_only=true` or
`executable=false`, and the action contract contains no write-capable hardware target.

## Policy and managed loads

`GET /v1/sites/{site_uid}/autopilot/policy`

Returns the resolved per-site `EnergyPolicy`, logical managed-load contracts, and the explicit
non-executable state.

## Receding-horizon plan

`GET /v1/sites/{site_uid}/autopilot/plan?hours=72`

Builds and persists a new plan. The response contains:

- baseline forecast;
- selected planned forecast;
- conservative/balanced/maximum-utilization alternatives;
- weighted objective scores;
- managed-load schedule/deferral decisions;
- optional advisory auxiliary-energy proposal;
- policy, forecast, calibration, and model-epoch provenance; and
- non-executable shadow actions with a short expiry.

## Run one complete Shadow Autopilot iteration

`POST /v1/sites/{site_uid}/autopilot/tick`

Performs one iteration of the same loop used by the background task:

1. build/persist a fresh receding-horizon plan;
2. find old enough plans that do not yet have evaluations;
3. replay them against available Morningstar history;
4. persist evaluations and model feedback;
5. apply at most one cooldown/rate-limited calibration adjustment when evidence is sufficient;
6. detect calibration change points/model epochs.

No action is executed.

## Plan history

`GET /v1/sites/{site_uid}/autopilot/plans?limit=20`

Returns persisted shadow plans newest first.

## Action ledger

`GET /v1/sites/{site_uid}/autopilot/actions?limit=100`

Returns the individual action ledger. `status` is initially `proposed` and becomes `evaluated`
when the parent plan has been replayed.

## Counterfactual evaluations

`GET /v1/sites/{site_uid}/autopilot/evaluations?limit=100`

Returns actual/shadow/hindsight decision scores, absolute and percent decision regret, shadow
improvement versus observed baseline, evidence quality, and the associated model feedback.

`POST /v1/sites/{site_uid}/autopilot/replay/{plan_id}`

Manually evaluates one stored plan when enough elapsed history exists. If it was already evaluated,
the stored evaluation is returned. Manual replay does not apply calibration feedback.

## Model feedback

`GET /v1/sites/{site_uid}/autopilot/feedback?limit=20`

Returns PV/load/SOC MAE and bias, recommended scaling multipliers, primary attribution,
confidence, and whether that feedback was applied to calibration.

Applied feedback is bounded by `feedback_max_adjustment_fraction` and protected by
`feedback_cooldown_hours`.

## Autopilot scorecard

`GET /v1/sites/{site_uid}/autopilot/scorecard?limit=200`

Aggregates decision regret, shadow improvement, actual/shadow/hindsight reserve-breach counts,
potential surplus recovered, shadow auxiliary/deferred energy, and feedback confidence.

## Model epochs

`GET /v1/sites/{site_uid}/autopilot/epochs?limit=20`

Returns the initial Shadow Autopilot epoch plus later change-point epochs created when calibration
shows large PV, load, usable-capacity, or battery-impedance discontinuities.

## Forecast history

`GET /v1/sites/{site_uid}/forecasts?limit=20`

Returns persisted forecast payloads newest first.
