# Roadmap

## v0.1 — predictive reserve foundation

- Morningstar normalized site adapter
- Open-Meteo weather/irradiance adapter
- hourly solar/load/battery simulation
- P10/P50/P90 trajectories
- reserve-risk probability
- what-if scenarios
- local persistence and web/API surfaces

## v0.2 — site intelligence foundation

Implemented in the current branch:

- historical Morningstar system-history ingestion
- historical weather alignment and automatic calibration
- hourly/weekday load baselines and recurring demand signatures
- multi-array PV geometry/temperature/shading/controller model
- learned PV correction factors
- optional multi-model weather ensembles and spread propagation
- battery digital twin with capacity/temperature/power-limit modeling
- learned usable-capacity and resistance estimates when evidence supports them
- conservative surplus/discretionary-energy forecasts
- unmet-load probability
- forecast-vs-actual MAE/bias/P10-P90 scoring by lead time
- flexible and interruptible load scheduling
- bounded PV/battery sizing optimization
- read-only auxiliary-energy planner
- topology/ledger-backed digital-twin output
- Sentinel health-feedback adapter
- optional HMAC-signed reserve-risk feed for Sentinel
- machine-readable non-executable action plans

## v0.3 — deeper self-learning

- seasonal/monthly PV calibration layers with minimum-data gates
- explicit change-point detection when hardware/configuration changes
- richer recurring-load event clustering beyond hour-of-day signatures
- battery capacity/impedance trend analysis across calibration history
- chemistry-specific degradation and cycle-throughput models
- historical forecast-run ingestion for exact lead-time weather-model backtesting
- automatic weather-model weighting by local measured forecast skill

## v0.4 — vendor-neutral site intelligence

- BMS, inverter, AC meter, generator-telemetry, and environmental read-only adapters
- normalized storage/source/load/converter/meter/environment roles
- multiple battery-bank and bus-segment simulation
- topology-aware branch constraints and conversion losses
- fleet-level compact model/health summaries while keeping raw high-frequency data local

## Separate future product — policy-validated executor

Hardware control remains intentionally outside PowerSiteAutonomy. If closed-loop control is ever
introduced, use a separate executor with explicit operator opt-in, allowlisted actions, hard
voltage/current/temperature limits, replayable audit logs, fail-safe defaults, and independent
policy validation. Autonomy should continue producing proposed actions rather than acquiring
arbitrary write capability.
