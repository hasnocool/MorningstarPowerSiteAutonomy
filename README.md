# Morningstar PowerSite Autonomy

**MorningstarPowerSiteAutonomy** is a local-first predictive energy, battery-autonomy,
digital-twin, scheduling, and decision-support engine for Morningstar-powered off-grid systems.

It sits above [MorningstarModbusAPI](https://github.com/hasnocool/MorningstarModbusAPI) and
answers a different question from telemetry dashboards and incident monitoring:

> **Given the battery, loads, solar conditions, learned site behavior, and weather ahead, will
> this site have enough energy — what is the best read-only plan, and did that plan prove good
> after reality arrived?**

## v0.3 Shadow Autopilot

v0.3 adds a closed **learning loop** without creating a closed **hardware-control loop**:

- receding-horizon planning on a configurable cadence (15 minutes by default);
- explicit per-site energy policies with reserve, morning-SOC, and risk targets;
- weighted objectives for reserve risk, unserved demand, battery throughput, unused solar,
  auxiliary energy, deferred loads, and interruptions;
- conservative, balanced, and maximum-utilization alternatives on every cycle;
- emergency-reserve hard objective penalty;
- logical managed-load contracts with priority/window/interruptibility but no hardware address;
- cumulative multi-load scheduling so flexible demands compete for the same forecast energy;
- optional advisory auxiliary-energy proposals;
- immutable, expiring, non-executable shadow action records with full model/policy provenance;
- SQLite/WAL plan, action, evaluation, feedback, and model-epoch ledgers;
- actual-vs-shadow-vs-hindsight counterfactual replay using later Morningstar history;
- decision regret and shadow-improvement scoring;
- PV/load/SOC model-error attribution;
- bounded, confidence-gated, cooldown-limited automatic calibration feedback;
- change-point detection and explicit model epochs for major PV/load/battery shifts;
- aggregate Shadow Autopilot scorecards; and
- API/web-console access to plans, actions, evaluations, feedback, scorecards, and epochs.

The v0.2 intelligence foundation remains underneath v0.3: historical self-calibration,
multi-array PV and battery digital twins, weather ensembles, probabilistic forecasts, forecast
backtesting, flexible-load scheduling, sizing optimization, topology/ledger views, Sentinel
feedback, and signed risk feeds.

## Safety boundary

Autonomy **does not write controller registers or perform control actions**. It never changes
charge settings, starts/stops external sources, switches loads, performs equalization/reset
actions, or exposes arbitrary Modbus writes.

Shadow Autopilot actions always have `executable=false`. Managed loads are logical scheduling
contracts rather than device/protocol definitions. A future write-capable executor must remain a
separate product with independent policy validation and operator opt-in.

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
                         +--> Shadow Autopilot
                         |      plan -> ledger -> replay -> score -> feedback -> replan
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
| `GET /health` | service/upstream/shadow status |
| `GET /v1/sites/{site_uid}/forecast` | calibrated probabilistic forecast |
| `GET /v1/sites/{site_uid}/digital-twin` | battery/PV/topology/ledger twin |
| `POST /v1/sites/{site_uid}/schedule` | one-shot flexible-load scheduler |
| `POST /v1/sites/{site_uid}/optimize` | PV/battery sizing frontier |
| `GET /v1/sites/{site_uid}/autopilot/policy` | resolved shadow policy/load contracts |
| `GET /v1/sites/{site_uid}/autopilot/plan` | persist a receding-horizon shadow plan |
| `POST /v1/sites/{site_uid}/autopilot/tick` | run one plan/evaluate/feedback iteration |
| `GET /v1/sites/{site_uid}/autopilot/actions` | shadow action ledger |
| `GET /v1/sites/{site_uid}/autopilot/evaluations` | counterfactual replay results |
| `GET /v1/sites/{site_uid}/autopilot/scorecard` | aggregate decision-quality scorecard |
| `GET /v1/sites/{site_uid}/autopilot/epochs` | model regime/change-point history |

See `docs/api.md` and `docs/shadow-autopilot.md` for detailed semantics.

## Shadow feedback safeguards

The feedback loop does not blindly rewrite the site model. By default:

- a plan must age six hours before first counterfactual evaluation;
- low-sample/low-confidence feedback is recorded but not applied;
- applied calibration changes are limited to ±5% per feedback event;
- another automatic correction cannot occur for 12 hours; and
- major learned-model discontinuities create a new model epoch rather than silently erasing
  provenance.

## Non-blocking runtime

HTTP uses long-lived `httpx.AsyncClient` instances and concurrent `asyncio.gather()` reads.
Synchronous SQLite and CPU-heavy forecast/planning/replay work are isolated with
`asyncio.to_thread()`. Periodic forecast, calibration, and Shadow Autopilot loops use
`asyncio.sleep()` and are cancelled/awaited during shutdown.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python -m compileall -q src
```

See `docs/product.md`, `docs/architecture.md`, `docs/api.md`, `docs/shadow-autopilot.md`, and
`docs/roadmap.md`.
