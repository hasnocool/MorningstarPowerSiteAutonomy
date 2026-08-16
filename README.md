# Morningstar PowerSite Autonomy

**MorningstarPowerSiteAutonomy** is a local-first predictive energy, battery-autonomy,
digital-twin, scheduling, and decision-support engine for Morningstar-powered off-grid systems.

It sits above [MorningstarModbusAPI](https://github.com/hasnocool/MorningstarModbusAPI) and
answers a different question from telemetry dashboards and incident monitoring:

> **Given the battery, loads, solar conditions, learned site behavior, and weather ahead, will
> this site have enough energy — and what read-only plan produces the safest outcome?**

## v0.2 intelligence foundation

The v0.2 implementation keeps the service read-only while expanding it from a configured
simulator into a self-calibrating planning engine:

- normalized live-state ingestion from MorningstarModbusAPI;
- historical system-metric ingestion for self-calibration;
- hourly and weekday load baselines learned from site history;
- recurring hourly load-pattern detection with occurrence probability;
- historical weather alignment and learned PV correction factors;
- multi-array PV modeling with tilt, azimuth, temperature coefficient, wiring loss, controller
  efficiency/clipping, albedo, and hourly shading factors;
- optional multi-model Open-Meteo forecasts with model spread propagated into uncertainty;
- battery digital twin with chemistry, configured usable capacity, learned usable-capacity
  estimate, temperature derating, charge/discharge power limits, and resistance estimate;
- Monte Carlo P10/P50/P90 solar, load, surplus, and SOC trajectories;
- reserve-breach and unmet-load probabilities;
- conservative/safe discretionary-energy budget and no-solar autonomy estimate;
- flexible/interruptible load scheduling into lower-risk or conservative-surplus windows;
- bounded PV/battery sizing optimization with optional incremental-cost ranking;
- advisory auxiliary-energy planner that estimates how much external energy is required to
  reach a target reserve-risk probability;
- forecast-vs-actual MAE, bias, and P10-P90 coverage scoring, including 1/6/24/48/72-hour
  lead-time views when enough data exists;
- topology-aware digital-twin output using the upstream component graph and energy ledger;
- optional read-only Sentinel feedback to widen uncertainty when telemetry is stale/degraded;
- compact reserve-risk feed for Sentinel, optionally HMAC-SHA256 signed with
  `AUTONOMY_RISK_FEED_SECRET`;
- machine-readable read-only action plans for surplus use, flexible-load deferral, reserve
  preservation, auxiliary-energy evaluation, and observability improvement;
- SQLite/WAL persistence with synchronous SQLite work isolated using `asyncio.to_thread()`;
- FastAPI/OpenAPI service, local web console, Docker/systemd deployment paths, and Python 3.12+.

## Safety boundary

Autonomy **does not write controller registers or perform control actions**. It never changes
charge settings, starts/stops generators, switches loads, performs equalization/reset actions,
or exposes arbitrary Modbus writes.

Scheduling, optimization, auxiliary-energy results, and action plans are recommendations. Every
machine-readable action is marked non-executable and operator approval remains outside this
service. If a future hardware executor is added, it should be a separate component with its own
policy/safety boundary.

## Product family

```text
Morningstar hardware
       |
       v
MorningstarModbusAPI      measurement / identity / history / topology / provenance
       |
       +--> MorningstarModbusFrontend     engineering inspection
       |
       +--> MorningstarPowerSiteSentinel  deterministic health / incidents
       |                |
       |                `---- read-only health feedback ----+
       |                                                  |
       `--> MorningstarPowerSiteAutonomy  <---------------+
              calibration / forecast / digital twin / planning
                         |
                         `---- signed reserve-risk feed ---> Sentinel
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp config.example.toml config.toml
powersite-autonomy --config config.toml serve
```

Open `http://127.0.0.1:8091/` or `http://127.0.0.1:8091/docs`.
MorningstarModbusAPI normally runs at `http://127.0.0.1:8080` and Sentinel at `8090` when used.

## Core API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | service/upstream status |
| `GET /v1/sites` | upstream sites plus Autonomy configuration state |
| `GET /v1/sites/{site_uid}/forecast?hours=72` | calibrated P10/P50/P90 forecast |
| `GET /v1/sites/{site_uid}/forecasts` | persisted forecast history |
| `POST /v1/sites/{site_uid}/scenarios` | paired what-if analysis |
| `GET /v1/sites/{site_uid}/calibration` | current learned calibration |
| `POST /v1/sites/{site_uid}/calibration/refresh` | refresh historical calibration |
| `GET /v1/sites/{site_uid}/calibrations` | calibration history/capacity trend source |
| `GET /v1/sites/{site_uid}/forecast-score` | forecast-vs-actual scoring |
| `POST /v1/sites/{site_uid}/schedule` | schedule a flexible/interruptible load |
| `POST /v1/sites/{site_uid}/optimize` | search PV/battery sizing candidates |
| `POST /v1/sites/{site_uid}/auxiliary-plan` | quantify advisory external-energy need |
| `GET /v1/sites/{site_uid}/digital-twin` | battery/PV/topology/ledger twin snapshot |
| `GET /v1/sites/{site_uid}/risk-feed` | compact optional-signed Sentinel risk feed |
| `GET /v1/sites/{site_uid}/action-plan` | machine-readable read-only recommendations |

See `docs/api.md` for request shapes and semantics.

## Calibration model

Automatic calibration runs on a configurable interval (default six hours) and learns from
normalized upstream 1-hour history plus historical weather. The model stores:

```text
site calibration
├── load
│   ├── 24-hour mean profile
│   ├── 24-hour uncertainty profile
│   ├── weekday multipliers
│   └── recurring hourly signatures
├── PV
│   ├── global observed/model scale
│   └── hourly scale factors
└── battery
    ├── estimated usable capacity (when evidence supports it)
    └── estimated internal resistance (when evidence supports it)
```

When evidence is insufficient, Autonomy preserves configured fallbacks and records notes/sample
counts instead of fabricating learned values.

## Forecast semantics

Forecasts are probabilistic estimates, not measurements. Every response exposes `input_quality`
and a model/calibration version. The service preserves the distinction between measured upstream
inputs, derived values, configured fallbacks, learned historical parameters, Sentinel feedback,
and weather forecasts.

P10/P50/P90 are generated from repeated site simulations. Solar uncertainty includes cloud
uncertainty and optional inter-model weather spread. Demand uncertainty uses learned hourly
variance when calibration exists. Battery simulation applies effective capacity, separate
charge/discharge efficiency, charge/discharge power limits, reserve floor, and temperature
capacity derating.

## Non-blocking I/O

HTTP uses long-lived `httpx.AsyncClient` instances and concurrent `asyncio.gather()` reads.
SQLite work is isolated with `asyncio.to_thread()` and a write lock, so synchronous SQLite calls
do not block the event loop or share mutable connections between worker threads. Periodic work
uses `asyncio.sleep()` and shutdown cancels/awaits all background tasks.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python -m compileall -q src
```

See `docs/product.md`, `docs/architecture.md`, `docs/api.md`, and `docs/roadmap.md`.
