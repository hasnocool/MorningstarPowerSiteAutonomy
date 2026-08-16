# Architecture

```text
Morningstar controllers
        |
        v
MorningstarModbusAPI ----------------------------------------------+
measurement / identity / normalized history / topology / ledger   |
        |                                                          |
        +-------------------+                                      |
        |                   |                                      |
        v                   v                                      |
PowerSiteSentinel       PowerSiteAutonomy <---- Open-Meteo         |
health/incidents          |      ^               forecast/archive  |
        |                 |      |                                 |
        | read-only       |      +---- optional health feedback ---+
        | feedback        |
        +---------------->|
                          |
                 +--------+---------+-----------+-----------+
                 |                  |           |           |
             calibration         forecast    planning    scoring
                 |                  |           |           |
                 +------------------+-----------+-----------+
                                    |
                               SQLite/WAL
                                    |
                         REST / local web console
                                    |
                         signed reserve-risk feed
                                    |
                                 Sentinel
```

## Responsibility boundaries

- **MorningstarModbusAPI** owns physical-controller identity, register decoding, raw/normalized
  telemetry, system history, topology, component graph, power flow, energy ledger, and provenance.
- **PowerSiteSentinel** owns deterministic health findings and incident lifecycle.
- **PowerSiteAutonomy** owns probabilistic calibration, forecasting, digital-twin interpretation,
  scheduling, sizing, advisory external-energy planning, backtesting, and action recommendations.
- **No hardware executor exists in this service.** Planning output is explicitly non-executable.

## Historical calibration

Autonomy requests bounded 1-hour normalized system histories and historical weather concurrently.
The calibration engine computes 24-hour load mean/variance profiles, weekday multipliers,
recurring hourly demand signatures, observed-vs-modeled PV scale factors, and battery
capacity/resistance estimates when the evidence is sufficient.

Each calibration is immutable and timestamped. Forecasts store the calibration version they used,
so later scoring can distinguish model changes rather than silently mixing them.

## PV model

Each configured array is simulated independently. The model estimates solar geometry and
plane-of-array irradiance from GHI, tilt, azimuth, latitude, longitude, cloud-dependent diffuse
fraction, and ground albedo. It then applies module temperature coefficient, NOCT-derived cell
temperature, shading profile, wiring loss, controller efficiency, controller clipping, and learned
site correction factors.

Optional weather-model ensembles are fetched concurrently; their radiation spread becomes an
additional uncertainty term rather than being averaged away without provenance.

## Battery digital twin

The twin combines configured chemistry/capacity with learned usable capacity when available,
temperature capacity derating, health, charge/discharge efficiency, and optional charge/discharge
power limits. SOC uncertainty is widened when the upstream measurement is absent or Sentinel marks
SOC evidence unreliable.

The simulator never interprets missing evidence as zero.

## Planning layer

The planning layer reuses the same calibrated Monte Carlo model:

- flexible-load scheduler evaluates feasible time windows or distributes interruptible energy;
- PV/battery optimizer performs a bounded grid search and returns a Pareto-like shortlist;
- auxiliary-energy planner uses a paired-seed binary search to quantify advisory energy needed to
  meet a target risk;
- action-plan builder emits only non-executable recommendations.

Because all candidate simulations use paired random seeds, changes in risk primarily reflect the
candidate decision rather than unrelated Monte Carlo draws.

## Sentinel integration

Sentinel integration is deliberately evidence-conservative. Autonomy consumes the assessment API
read-only. Explicit future forecast-feedback fields are honored when present; otherwise only
well-defined stale/offline/conflict findings widen uncertainty. Autonomy does not invent a PV
failure percentage from a generic health warning.

The reverse path is `/risk-feed`. It can be HMAC-SHA256 signed with a local secret so Sentinel can
consume compact reserve-risk output without needing the full forecast payload.

## Concurrency

- Morningstar and weather reads use long-lived `httpx.AsyncClient` instances.
- Independent reads use `asyncio.gather()`.
- Multi-model weather requests run concurrently.
- SQLite is opened per worker operation; synchronous calls run in `asyncio.to_thread()` and writes
  are serialized by an async lock.
- Periodic forecast/calibration loops use `asyncio.sleep()`.
- Shutdown cancels and awaits all periodic tasks before HTTP clients are closed.

## Evidence policy

Measured, derived, configured, learned, health-derived, and forecast values remain distinct.
`input_quality`, calibration sample counts/notes, model versions, and upstream graph/ledger
provenance preserve that distinction throughout the service.
