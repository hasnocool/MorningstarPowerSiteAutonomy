# Roadmap

## v0.1 — predictive reserve foundation

- Morningstar normalized site adapter
- Open-Meteo weather/irradiance adapter
- hourly solar/load/battery simulation
- P10/P50/P90 trajectories
- reserve-risk probability
- what-if scenarios
- local persistence and web/API surfaces

## v0.2 — historical calibration

- train hourly/day-of-week load baselines from Morningstar system history
- compare prior forecasts with actual energy and SOC
- MAE/bias/coverage calibration metrics
- learn per-site PV performance ratio by season and time of day
- retain forecast-model version with every run

## v0.3 — planning optimizer

- calculate maximum discretionary energy by time window
- find minimum additional PV or battery capacity needed for a target reserve probability
- replay historical weather/energy windows for sizing decisions
- rank candidate load schedules by reserve risk

## v0.4 — Sentinel integration

- signed/read-only reserve-risk feed for MorningstarPowerSiteSentinel
- predicted reserve-breach incidents with confidence thresholds
- forecast-vs-actual diagnostic events

## Future

- vendor-neutral site adapters
- ensemble weather providers
- battery chemistry/degradation models
- optional operator-approved control recommendations, while keeping automated control out of the forecasting service
