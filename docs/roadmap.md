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
- Sentinel health-feedback adapter and optional signed reserve-risk feed
- machine-readable non-executable action plans

## v0.3 — Shadow Autopilot

Implemented in this stacked branch:

- receding-horizon planning on a configurable cadence/horizon
- explicit per-site energy policy and weighted multi-objective score
- conservative, balanced, and maximum-utilization plan alternatives
- emergency-reserve hard objective constraint
- logical managed-load contracts without hardware addresses/write targets
- cumulative flexible-load scheduling across multiple managed loads
- optional advisory auxiliary-energy proposals
- immutable non-executable shadow action contract with policy/model provenance
- SQLite/WAL plan and action ledger with action lifecycle state
- actual-vs-shadow-vs-hindsight counterfactual replay
- decision-regret and shadow-improvement scoring
- PV/load/SOC error attribution from measured outcomes
- bounded and cooldown-limited automatic calibration feedback
- explicit model epochs and change-point detection
- 30-day-style aggregate Autopilot scorecard primitives
- periodic background shadow planning/evaluation loop
- API and local-console surfaces for plans, actions, evaluations, feedback, epochs, and scorecards

## v0.4 — deeper self-learning

- seasonal/monthly PV calibration layers with minimum-data gates
- richer recurring-load event clustering beyond hour-of-day signatures
- chemistry-specific degradation and cycle-throughput models
- exact weather-model forecast-run retention and local-skill weighting
- explicit managed-load completion evidence from read-only meters/telemetry
- probabilistic change-point detection instead of fixed relative thresholds
- longer-horizon regret decomposition by weather/load/battery/policy error source

## v0.5 — vendor-neutral site intelligence

- BMS, inverter, AC meter, generator-telemetry, and environmental read-only adapters
- normalized storage/source/load/converter/meter/environment roles
- multiple battery-bank and bus-segment simulation
- topology-aware branch constraints and conversion losses
- fleet-level compact model/health summaries while keeping raw high-frequency data local

## v0.6 — evidence intelligence and self-validating digital twin

- probabilistic parameter beliefs with explicit uncertainty, confidence, and provenance
- precision-weighted evidence updates with physical parameter bounds
- explicit competing hypothesis registry
- digital-twin ensembles with posterior weighting from measured prediction error
- champion/challenger twin promotion with minimum-history and margin gates
- passive observation opportunities ranked by expected information gain
- economic-impact weighting for evidence priorities
- decision-sensitivity tracking for assumptions that can change recommendations
- low/medium/high recommendation-stability classification
- value-of-information economics for deciding when more evidence is worth waiting for
- non-blocking async evidence-analysis service and REST API
- strict read-only boundary: evidence collection never becomes a hardware experiment executor

## Separate future product — policy-validated executor

Hardware control remains intentionally outside PowerSiteAutonomy. If closed-loop control is ever
introduced, use a separate executor with explicit operator opt-in, allowlisted actions, hard
safety limits, replayable audit logs, fail-safe defaults, and independent policy validation.
Autonomy should continue producing proposed actions rather than acquiring arbitrary write
capability.
