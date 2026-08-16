# API

All planning endpoints are read-only with respect to power hardware. They return forecasts,
recommendations, or proposed schedules; they do not execute them.

## Forecast

`GET /v1/sites/{site_uid}/forecast?hours=72`

Returns hourly P10/P50/P90 values for solar power, load power, conservative instantaneous
surplus, and battery SOC plus:

- expected solar/load/surplus energy;
- minimum SOC percentiles;
- reserve-breach probability and first simulated breach;
- unmet-load probability;
- no-solar autonomy estimate;
- expected and conservative safe discretionary energy;
- effective battery capacity used by the simulation;
- model/calibration versions, confidence, and input quality.

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

Returns calibration history. This is also the source for observing usable-capacity and resistance
trends over time.

## Forecast scoring

`GET /v1/sites/{site_uid}/forecast-score?limit=20`

Compares persisted forecast points with later Morningstar observations. Metrics include MAE,
bias, and P10-P90 empirical coverage for PV, load, and SOC. When the stored horizons permit it,
metrics are also reported at 1, 6, 24, 48, and 72 hours ahead.

## Flexible-load scheduling

`POST /v1/sites/{site_uid}/schedule`

Example:

```json
{
  "horizon_hours": 48,
  "energy_required_wh": 500,
  "max_power_w": 150,
  "earliest_start_hour": 2,
  "deadline_hour": 30,
  "priority": "flexible",
  "interruptible": true
}
```

Interruptible loads are distributed across the strongest conservative-surplus/SOC hours.
Non-interruptible loads are evaluated across every feasible contiguous start window and ranked by
reserve risk and minimum SOC.

## PV/battery optimizer

`POST /v1/sites/{site_uid}/optimize`

Performs a bounded grid search over PV watts and battery Wh. Candidates are paired with the same
weather/load uncertainty seed, ranked by target risk and optional incremental cost, and returned
as a compact Pareto-like frontier.

The request supports min/max/step fields, a target reserve-breach probability, optional
`pv_cost_per_w` / `battery_cost_per_wh`, and a bounded `max_candidates`.

## Auxiliary-energy planner

`POST /v1/sites/{site_uid}/auxiliary-plan`

Quantifies the minimum advisory external energy needed to reach a target reserve-risk probability
within a permitted time window. The response always has `operator_action_required=true` and
`executable=false`; Autonomy never starts or controls an external source.

## Digital twin

`GET /v1/sites/{site_uid}/digital-twin`

Returns the current battery twin, resolved PV arrays, latest calibration, and the upstream
Morningstar component graph and energy ledger. Topology/provenance remain owned by
MorningstarModbusAPI rather than duplicated locally.

## Sentinel risk feed

`GET /v1/sites/{site_uid}/risk-feed?hours=72`

Returns a compact reserve-risk payload suitable for Sentinel consumption. If
`AUTONOMY_RISK_FEED_SECRET` is set, the canonical payload is signed with HMAC-SHA256 and the hex
signature is returned in `signature`. With no secret the feed remains read-only and unsigned.

## Action plan

`GET /v1/sites/{site_uid}/action-plan?hours=72`

Returns machine-readable recommendations such as `use_surplus`, `defer_flexible_loads`,
`preserve_reserve`, `plan_auxiliary_source`, and `improve_observability`. Every action is marked
`executable=false` and `requires_operator_approval=true`.

## Forecast history

`GET /v1/sites/{site_uid}/forecasts?limit=20`

Returns persisted forecast payloads newest first.
