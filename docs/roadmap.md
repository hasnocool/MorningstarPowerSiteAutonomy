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
- optional multi-model Open-Meteo forecasts and model spread
- battery digital twin with capacity/temperature/power-limit modeling
- forecast-vs-actual scoring, scheduling, sizing, and advisory planning

## v0.3 — Shadow Autopilot

- receding-horizon planning and explicit energy policy
- conservative/balanced/maximum-utilization alternatives
- non-executable shadow action ledger
- actual-vs-shadow-vs-hindsight replay and decision regret
- bounded automatic feedback and model epochs
- aggregate Autopilot scorecards

## v0.4 — deeper self-learning

The original v0.4 goals are implemented by the later Adaptive World Model work in v0.7 so they
can build on the evidence-intelligence layer added in v0.6:

- seasonal/monthly PV and load calibration
- richer recurring-load event discovery
- chemistry-aware battery degradation/throughput observations
- exact weather-model forecast-run retention and local-skill weighting
- empirical uncertainty calibration
- probabilistic change-point detection
- model promotion based on held-out forecast skill

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
- decision-sensitivity and recommendation-stability tracking
- value-of-information economics
- strict read-only evidence boundary

## v0.7 — Adaptive World Model

- retain immutable per-model weather forecasts before outcomes are known
- score weather models by site and lead-time bucket against measured PV outcomes
- learn horizon-specific ensemble weights and restore them after restart
- propagate empirical solar-forecast coverage into ensemble spread calibration
- learn month/hour PV residuals and load distributions with minimum-sample gates
- discover recurring load-event clusters from residual demand rather than hour-of-day alone
- infer confidence-capped managed-load completion evidence from read-only telemetry windows
- track observed battery throughput, equivalent full cycles, capacity trend, and resistance trend
- calibrate P10-P90 uncertainty from measured forecast coverage
- replace fixed change thresholds with probability-like standardized change evidence
- train seasonal challengers on older history and evaluate promotion only on a recent holdout window
- reuse v0.6 twin-tournament logic for champion/challenger promotion
- activate only promoted seasonal overlays by publishing a versioned SiteCalibration
- persist weather runs, skills, overlays, events, battery health, uncertainty, changes, model
  candidates, promotion decisions, and adaptive scorecards in SQLite/WAL
- expose adaptive-world REST and local-console surfaces
- remain strictly read-only with respect to physical hardware

## v0.8 — Adaptive Policy Lab and Decision Intelligence

- immutable point-in-time policy replay over mature Shadow Autopilot plans
- bounded global and regime-specific policy candidate generation
- rolling-origin validation folds
- paired bootstrap confidence for challenger promotion
- hard no-regression gate for emergency-reserve and observed safety incidents
- automatic shadow-policy champion restoration after restart
- contextual energy-regime classification
- bounded dynamic-reserve recommendations with multi-timescale reserve pressure
- Pareto policy frontier across risk, auxiliary energy, deferral, throughput, and score
- longer-horizon regret decomposition by weather/PV/load/battery/policy/optimizer source
- autonomy intelligence score with explicit weakest-component attribution
- persistent policy registry, evaluations, tournaments, frontiers, regret, and scorecards
- promoted policies affect Shadow Autopilot proposals only; hardware remains non-executable

## Future — adaptive model and policy depth

- weather-regime-specific weighting using explicit meteorological features
- dedicated rolling-origin world-model cross-validation beyond the policy replay folds
- chemistry-specific calendar/cycle aging priors combined with observed degradation
- stronger managed-load identity/completion attribution from dedicated metered signatures
- multi-site transfer priors with privacy-preserving local raw telemetry
- learned policy portfolios with independently promoted per-regime champions
- 7-14 day external forecast ingestion for scarcity planning beyond the current 168 h horizon
- decision-sensitive data acquisition that prioritizes errors most likely to change recommendations

## Separate future product — policy-validated executor

Hardware control remains intentionally outside PowerSiteAutonomy. If closed-loop control is ever
introduced, use a separate executor with explicit operator opt-in, allowlisted actions, hard
safety limits, replayable audit logs, fail-safe defaults, and independent policy validation.
Autonomy should continue producing proposed actions rather than acquiring arbitrary write
capability.
