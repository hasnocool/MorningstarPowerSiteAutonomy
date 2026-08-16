# Economic and hardware optimizer

PowerSiteAutonomy v0.5 adds a degradation-aware economic layer on top of the existing forecasting/sizing engine and the v0.4 fleet evidence model.

## Capabilities

- **Real-world hardware performance**: measured fleet P50 efficiency, degradation, and lifetime metrics can override optimistic nominal assumptions when matching hardware evidence exists.
- **Cost per added autonomy**: battery additions are normalized to effective Wh and translated into added hours at the site's average load.
- **Degradation-aware ROI**: expected annual value is reduced by degradation and maintenance costs and evaluated over a discounted analysis horizon.
- **Upgrade recommendations**: candidate PV, battery, controller, inverter, generator, or mixed upgrades are ranked by ROI, resilience/autonomy gain, and payback.
- **Replacement timing**: aging hardware is compared against annualized replacement cost and failure exposure to produce keep/plan/replace guidance.

## Data flow

```text
forecast + site economics + candidate hardware
                   |
                   +---- fleet hardware evidence
                   |        efficiency
                   |        degradation
                   |        lifetime
                   v
             economic evaluator
                   |
          +--------+---------+
          |        |         |
        ROI     autonomy   payback
          |        |         |
          +--------+---------+
                   v
            ranked upgrades
                   |
             replacement plan
```

The optimizer remains advisory and read-only. It does not purchase equipment or execute controller/load actions. CPU-bound ranking is isolated with `asyncio.to_thread()` through `EconomicHardwareService`.

The built-in PV-energy estimate intentionally uses a conservative generic peak-sun-hour prior when no forecast-derived candidate value is supplied. Site-specific forecast and scenario outputs should remain the preferred evidence source for production recommendations.
