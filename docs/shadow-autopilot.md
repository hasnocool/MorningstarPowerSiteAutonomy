# Shadow Autopilot

Shadow Autopilot is the v0.3 receding-horizon decision layer for PowerSiteAutonomy. It continuously
asks what the site *would* do under an explicit energy policy, records the proposed actions, waits
for measured outcomes, replays those decisions against actual history, and feeds bounded evidence
back into the learned site model.

It is deliberately non-executable. There is no device address, Modbus write, relay command,
generator start/stop command, or arbitrary protocol passthrough in the Shadow Autopilot action
contract.

## Loop

```text
Morningstar telemetry + history
        +
weather ensemble
        +
site calibration / battery twin
        +
energy policy + managed-load contracts
        |
        v
receding-horizon planner
        |
        +--> conservative alternative
        +--> balanced alternative
        +--> maximum-utilization alternative
        |
        v
weighted objective + emergency-reserve hard penalty
        |
        v
selected non-executable ShadowAutopilotPlan
        |
        +--> plan ledger
        +--> action ledger
        |
        v
later Morningstar history
        |
        v
actual vs shadow vs hindsight replay
        |
        v
decision regret + model-error attribution
        |
        v
bounded/cooldown-limited calibration feedback
        |
        v
next receding-horizon plan
```

The default planning cadence is 15 minutes and the default horizon is 72 hours. A plan expires
after 30 minutes so consumers cannot treat stale proposals as current advice.

## Energy policy

Each configured site can provide `shadow_policy` with reserve targets and objective weights.
The default objective contains separate penalties for:

- reserve risk;
- unserved critical demand;
- battery-throughput/degradation proxy;
- unused solar surplus;
- auxiliary energy;
- deferred managed loads; and
- interruptions of interruptible loads.

`emergency_reserve_percent` is also a hard objective penalty: a candidate whose P10 SOC crosses
that floor is strongly dominated even if it would otherwise improve solar utilization.

## Managed loads

`shadow_loads` are scheduling contracts, not hardware definitions. A contract contains a logical
load ID, priority, power/energy requirement, scheduling window, and whether the demand may be
split across hours. It intentionally contains no write-capable target.

The planner evaluates enabled loads in priority/deadline order and carries accepted schedules into
subsequent evaluations so multiple flexible loads compete for the same forecast energy budget.

## Pareto-like alternatives

Every planning cycle evaluates three policy interpretations:

- **conservative** — tight reserve-risk tolerance and minimum-reserve SOC floor;
- **balanced** — configured target risk and midpoint SOC floor;
- **maximum utilization** — wider risk tolerance but never below the emergency-reserve floor.

The alternatives are scored with the configured policy weights. The lowest objective becomes the
selected shadow plan and all alternatives remain in the response for inspection.

## Shadow action ledger

Every selected proposal is stored in SQLite/WAL with:

- action and plan IDs;
- creation/expiration times;
- logical target and operation;
- proposed power/energy/window;
- expected reserve-risk change;
- confidence/reason/evidence codes;
- preconditions and safety constraints;
- policy, forecast, calibration, and model-epoch versions;
- `executable=false`; and
- `requires_operator_approval=true`.

The ledger status moves from `proposed` to `evaluated` after counterfactual replay.

## Counterfactual replay

After the configured evaluation delay, the service loads normalized Morningstar solar, load, and
SOC history covering the elapsed part of a plan. It computes three decision scores:

1. **actual** — observed baseline operation;
2. **shadow** — measured conditions plus the actions the planner proposed; and
3. **hindsight** — managed loads rescheduled using the now-known measured solar/load sequence.

The difference between shadow and hindsight penalty is reported as decision regret. This creates a
measurable answer to whether the planner was close to the best decision available in hindsight.

When history contains gaps, replay may fill missing solar/load hours from the original P50
forecast, marks evidence quality lower, and records that fallback in evaluation notes.

## Feedback and change points

Replay compares the original forecast P50 values with measured PV, load, and SOC. Feedback stores
MAE, bias, recommended PV/load scaling, a primary error attribution, and confidence.

Automatic feedback has two anti-drift gates:

- a cooldown between applied adjustments (12 hours by default); and
- a maximum absolute correction per application (5% by default, hard-bounded at 10%).

Low-sample/low-confidence feedback is recorded but not applied.

Calibration history is also checked for large discontinuities. New model epochs are created for
large PV-scale, mean-load, usable-capacity, or battery-impedance shifts. The epoch ID is attached to
future shadow actions so decisions can be attributed to the model regime that produced them.

## Safety boundary

Shadow Autopilot is a learning and decision-evaluation service, not an executor. A future
write-capable product should consume proposed actions through a separate independently validated
policy/executor boundary. PowerSiteAutonomy itself should remain unable to perform arbitrary
hardware writes.
