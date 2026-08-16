# Morningstar PowerSite Autonomy

**MorningstarPowerSiteAutonomy** is a local-first predictive energy, battery-autonomy, and decision-support engine for Morningstar-powered off-grid systems.

It sits above [MorningstarModbusAPI](https://github.com/hasnocool/MorningstarModbusAPI) and answers a different question from telemetry dashboards and incident monitoring:

> **Given the battery, loads, solar conditions, and weather ahead, will this site have enough energy — and what changes would improve the outcome?**

## v0.1 capabilities

- read-only site discovery and normalized live-state ingestion from MorningstarModbusAPI;
- async Open-Meteo irradiance/weather forecasts;
- hourly PV production estimates from array size, irradiance, and configurable performance ratio;
- load forecasting from measured/derived live load with explicit fallback provenance;
- battery-energy trajectory simulation with charge/discharge efficiency and reserve floor;
- Monte Carlo P10/P50/P90 solar, load, and SOC trajectories;
- reserve-breach probability and first expected breach time;
- estimated no-solar autonomy and discretionary energy budget;
- `POST` scenario analysis for additional loads, larger/smaller PV arrays, battery capacity, and reserve targets;
- SQLite/WAL forecast and scenario history without blocking the asyncio event loop;
- automatic periodic 72-hour forecasts;
- FastAPI/OpenAPI service and a small local web console;
- Python 3.12+ and Docker/systemd deployment paths.

Autonomy is **read-only**. It never writes Morningstar registers, changes charge settings, starts generators, switches loads, or performs control actions.

## Product family

```text
Morningstar hardware
       |
       v
MorningstarModbusAPI      measurement / identity / history / provenance
       |
       +--> MorningstarModbusFrontend     engineering inspection
       |
       +--> MorningstarPowerSiteSentinel  deterministic health / incidents
       |
       `--> MorningstarPowerSiteAutonomy  probabilistic forecast / planning
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

MorningstarModbusAPI normally runs at `http://127.0.0.1:8080`.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Autonomy version and Morningstar API reachability |
| `GET /v1/sites` | Upstream sites plus Autonomy configuration state |
| `GET /v1/sites/{site_uid}/forecast?hours=72` | P10/P50/P90 energy and SOC forecast |
| `GET /v1/sites/{site_uid}/forecasts` | persisted forecast history |
| `POST /v1/sites/{site_uid}/scenarios` | compare a what-if scenario to baseline |

Example scenario:

```json
{
  "horizon_hours": 48,
  "additional_loads": [
    {"power_w": 150, "start_hour": 2, "duration_hours": 8}
  ],
  "array_watts": 1200,
  "battery_capacity_wh": 5000,
  "reserve_percent": 25
}
```

## Forecast semantics

Forecasts are probabilistic estimates, not measurements. Every response exposes `input_quality`, and the service preserves the distinction between measured upstream inputs, derived values, configured fallbacks, and weather forecasts.

The default PV model converts hourly global shortwave irradiance to available array power using configured array watts and a performance ratio. Monte Carlo runs vary solar production and demand, then simulate battery state with separate charge/discharge efficiencies. P10/P50/P90 describe the distribution across those simulations.

## Non-blocking I/O

HTTP uses `httpx.AsyncClient`. SQLite work is isolated with `asyncio.to_thread()` and a write lock, so synchronous SQLite calls do not block the event loop or share mutable connections between worker threads.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest
python -m compileall -q src
```

See `docs/product.md`, `docs/architecture.md`, `docs/api.md`, and `docs/roadmap.md`.
