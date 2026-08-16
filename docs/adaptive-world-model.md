# Adaptive World Model

The Adaptive World Model is the read-only self-learning layer above the calibrated forecast engine,
Shadow Autopilot, and v0.6 evidence intelligence. Its purpose is not to make more aggressive
decisions. Its purpose is to make the site's assumptions measurable, challengeable, reproducible,
and increasingly local to the actual installation.

## Learning loop

```text
per-model weather forecasts ──┐
Morningstar history ──────────┼──> adaptive evidence builders
forecast history ─────────────┤          |
calibration history ──────────┘          v
                                 candidate world models
                                          |
                              temporal holdout evaluation
                                          |
                              v0.6 twin tournament gate
                                          |
                             promoted model only activates
                                          |
             ┌────────────────────────────┴───────────────────────┐
             v                                                    v
 horizon-weighted weather ensemble                    versioned SiteCalibration
             |                                                    |
             └──────────────────────> normal forecast engine <────┘
```

No adaptive component contains a Modbus write, relay command, generator command, controller
setting, or arbitrary hardware address. Promotion changes forecast/calibration inputs only.

## Exact weather-run retention

Every adaptive cycle stores each configured weather model separately before the outcome is known.
After the configured evaluation delay, those immutable predictions are compared with measured PV
history. Skill is retained separately for 0-12 h, 12-36 h, 36-72 h, and extended horizons.

Model weights use shrinkage toward equal weighting until enough evidence exists. A model therefore
does not dominate the ensemble merely because of a handful of lucky forecasts.

## Seasonal model

The seasonal overlay learns month/hour residual PV scaling and load mean/variance. Cells require a
minimum observation count. Missing cells fall back to the existing site calibration rather than
being fabricated.

The challenger is trained on the older part of the history window. The newest holdout period is
reserved for champion/challenger comparison. If the challenger wins the v0.6 tournament with the
configured sample and posterior-margin gates, a full-history overlay is activated and translated
into a new versioned `SiteCalibration` for the current month.

This avoids training/evaluation leakage and avoids compounding already-adaptive calibrations: each
new adaptive calibration is derived from the latest non-`+world-` base calibration. Promotion is
also reversible: a later baseline win clears the active overlay and republishes the base model as
the runtime calibration.

## Empirical uncertainty calibration

Persisted forecasts already expose P10/P50/P90. Adaptive World measures whether later observations
actually land inside P10-P90 roughly 80% of the time. Under-covered metrics widen; heavily
over-covered metrics can narrow. Solar calibration adjusts ensemble spread and load calibration
adjusts the learned hourly sigma. SOC coverage is retained for diagnosis even when no safe runtime
hook exists for changing its uncertainty directly.

## Load-event discovery

Residual load above the normal hourly/weekday baseline is grouped into contiguous events and then
clustered by approximate incremental power and duration. The output is intentionally behavioral:
it identifies recurring energy signatures without claiming to know which physical appliance
caused them.

## Managed-load completion evidence

For Shadow Autopilot load schedules, the adaptive layer can compare later measured load against
the plan's baseline forecast during the proposed scheduling window. It records an estimated
matched incremental energy and completion ratio with confidence capped below full certainty.
This is correlation evidence only; it never asserts that a shadow action was physically executed.

## Battery degradation observations

The model records:

- estimated usable capacity and capacity trend;
- estimated internal resistance and resistance trend;
- absolute battery-energy throughput; and
- equivalent full-cycle approximation.

These are evidence products, not a warranty/remaining-life claim. Missing capacity or resistance
evidence remains `null` rather than being inferred from a chemistry stereotype.

## Probabilistic change evidence

PV, load, usable capacity, and internal resistance changes are converted into standardized shifts
relative to expected background variability. A high-probability signal can create a Shadow
Autopilot model epoch, preserving the model boundary around a likely physical/configuration change.

## Persistence

Adaptive data shares the existing SQLite database but uses isolated `adaptive_*` tables. SQLite
work is serialized and moved through `asyncio.to_thread()`, matching the rest of the service's
non-blocking design.

## API

- `GET /v1/sites/{site_uid}/adaptive/snapshot`
- `POST /v1/sites/{site_uid}/adaptive/refresh`
- `POST /v1/sites/{site_uid}/adaptive/weather/capture`
- `GET /v1/sites/{site_uid}/adaptive/weather/runs`
- `GET /v1/sites/{site_uid}/adaptive/weather/skill`
- `GET /v1/sites/{site_uid}/adaptive/seasonal-model`
- `GET /v1/sites/{site_uid}/adaptive/load-events`
- `GET /v1/sites/{site_uid}/adaptive/managed-load-evidence`
- `GET /v1/sites/{site_uid}/adaptive/battery-health`
- `GET /v1/sites/{site_uid}/adaptive/uncertainty`
- `GET /v1/sites/{site_uid}/adaptive/change-points`
- `GET /v1/sites/{site_uid}/adaptive/models`
- `GET /v1/sites/{site_uid}/adaptive/promotions`
- `GET /v1/sites/{site_uid}/adaptive/scorecard`
