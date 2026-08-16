# Architecture

```text
Morningstar controllers
        |
        v
MorningstarModbusAPI ---------------------------+
normalized site state / provenance              |
        |                                        |
        v                                        |
MorningstarPowerSiteAutonomy <---- weather API  |
        |                                        |
  +-----+----------+--------------+              |
  |                |              |              |
input adapter   forecast model  scenario model   |
  |                |              |              |
  +----------------+--------------+              |
                   |                             |
              SQLite history                     |
                   |                             |
             REST + local UI                     |
                                                 |
Sentinel may consume future reserve-risk outputs +
```

## Concurrency

- Morningstar and weather reads run concurrently with `asyncio.gather`.
- HTTP clients are long-lived `httpx.AsyncClient` instances with bounded connection pools.
- SQLite is opened per worker operation; calls run in `asyncio.to_thread` and writes are serialized by an async lock.
- Periodic work uses `asyncio.sleep`, never blocking sleeps.
- Shutdown cancels and awaits the forecast task before closing HTTP clients.

## Evidence model

Observed Morningstar values and future predictions are separate evidence classes. `input_quality` records whether battery SOC and load came from upstream measurements/derivations or configuration fallbacks. Weather inputs are marked as forecasts.

## Forecast model

For each hour:

1. convert shortwave irradiance to nominal array power;
2. perturb solar according to cloud-dependent uncertainty;
3. perturb load around the current/fallback baseline;
4. apply scenario loads when present;
5. integrate net energy through charge/discharge efficiency;
6. cap battery energy to `[0, capacity]`;
7. record reserve crossings.

Repeated simulations produce percentile trajectories and reserve-breach probability.
