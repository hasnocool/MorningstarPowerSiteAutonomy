# Fleet intelligence

PowerSiteAutonomy v0.4 adds a local-first fleet learning layer. Sites exchange compact statistical observations rather than raw high-frequency telemetry.

## Capabilities

- **Site cohorts** group similar systems using storage size, PV size, base load, climate, chemistry, and controller identity.
- **Transferable priors** use similarity-weighted peer observations for cold-start calibration while preserving local evidence as the long-term authority.
- **Hardware performance learning** aggregates measured controller, battery, PV, inverter, and other component metrics into P10/P50/P90 summaries.
- **Policy benchmarking** compares policy utility and decision regret across sites.
- **Compact/federated exchange** exports count/mean/P50/stddev summaries and can HMAC-sign them for authenticated exchange.
- **SQLite persistence** stores only compact fleet observations and performs synchronous database work through `asyncio.to_thread()`.

## Privacy and safety

Fleet exchange is deliberately summary-based. Raw telemetry, controller register writes, credentials, and arbitrary operator actions are outside the exchange schema. A deployment can remain fully standalone and never publish a fleet summary.

## Typical flow

```text
local telemetry -> local calibration/shadow outcomes
                         |
                         v
                 compact observations
                         |
              local fleet intelligence
               /        |         \
          cohorts      priors     benchmarks
               \        |         /
                         v
                compact signed summary
```

`FleetIntelligenceService` provides async orchestration over the persistent observation store while CPU-bound aggregation runs in worker threads so the FastAPI event loop remains non-blocking.
