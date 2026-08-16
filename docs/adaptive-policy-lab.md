# v0.8 Adaptive Policy Lab and Decision Intelligence

Adaptive Policy Lab is the read-only policy-learning layer above Shadow Autopilot and the
Adaptive World Model. The world model answers **what is likely to happen**. Policy Lab answers
**which bounded shadow strategy has historically made the best decisions given only what was
known at the time**.

It never executes hardware actions.

## Point-in-time policy replay

Policy Lab treats every persisted Shadow Autopilot plan as an immutable decision record. Candidate
policies can inspect only the forecast summary and conservative/balanced/maximum-utilization
alternatives stored in that plan. Later telemetry is joined only after the decision and contributes
to scoring and safety regression.

This avoids a common backtesting error: a challenger cannot use today's observations to rewrite
yesterday's forecast before deciding what it would have done.

Each replay records:

- the detected energy regime;
- the alternative the candidate policy would have selected;
- point-in-time objective score;
- observed penalty after the outcome matured;
- predicted emergency-reserve violation;
- actual reserve-breach exposure;
- actual unserved energy;
- scheduled/deferred/auxiliary energy; and
- battery-throughput and unused-surplus evidence.

## Bounded candidate generation

Candidate policies are derived from the current champion inside explicit bounds. The generator
creates global challengers for resilience, solar utilization, battery preservation, minimum
auxiliary energy, and balanced operation, plus contextual challengers for uncertain weather,
extended scarcity, and sunny-surplus regimes.

The search space is bounded for:

- minimum reserve;
- morning SOC target;
- reserve-risk weight;
- battery-degradation weight;
- curtailed-solar weight;
- auxiliary-energy weight; and
- deferred-load weight.

The emergency reserve remains a hard lower bound.

## Rolling-origin validation and promotion

Candidate scores are kept chronologically and summarized into rolling-origin folds. Promotion uses
paired replay samples, not unrelated averages.

A global challenger can replace the shadow champion only when:

1. it has the configured minimum mature replay count;
2. its paired score improves by at least the configured margin;
3. paired bootstrap confidence is at least 95%;
4. predicted emergency-reserve breaches do not increase; and
5. actual reserve-breach safety incidents do not increase.

Regime-specific challengers are reported separately and do not silently become a global policy.

A promoted champion updates only the in-memory Shadow Autopilot policy. The output remains
non-executable and the underlying hardware boundary is unchanged.

## Dynamic reserve

A fixed reserve is retained as the operator baseline, but Policy Lab can calculate a bounded
read-only effective reserve using:

- forecast confidence;
- reserve-breach probability;
- low-solar or extended-scarcity regime;
- high-load regime;
- sunny-surplus conditions;
- measured battery-health evidence; and
- recent high-probability change evidence.

The response also contains reserve pressure at 6 h, 24 h, 72 h, and 168 h when those forecast
points exist. The calculation never changes controller settings or battery protection limits.

## Regret decomposition

Mature Shadow Autopilot evaluations are decomposed into:

- weather-model error;
- PV-model error;
- load-model error;
- battery-model error;
- policy-selection error;
- optimizer approximation; and
- irreducible uncertainty.

The attribution uses the existing Shadow Autopilot feedback label and preserves unattributed
regret rather than inventing precision.

## Pareto policy frontier

Policy Lab keeps non-dominated candidate policies across decision score, emergency-reserve
violations, safety incidents, auxiliary energy, deferred load, and battery throughput. This lets
operators distinguish different objective philosophies instead of pretending there is one
universally optimal policy.

## Autonomy intelligence score

The policy snapshot combines:

- forecast feedback confidence;
- empirical uncertainty coverage;
- weather/world-model skill;
- Shadow Autopilot decision regret;
- champion policy replay quality;
- battery evidence depth; and
- recent change stability.

The score is diagnostic. Its `biggest_opportunity` field identifies the weakest evidence/decision
component rather than hiding it inside one aggregate number.

## Persistence

Policy Lab uses the same SQLite database with isolated tables:

- `policy_lab_artifacts`
- `policy_lab_champions`

Candidates, evaluations, tournaments, Pareto frontiers, regret decompositions, scorecards, and
full snapshots are replayable. SQLite work remains off the async event loop.

## API

Policy Lab is mounted under the Adaptive World router so no new application wiring is required:

- `POST /v1/sites/{site_uid}/adaptive/policy-lab/tick`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/snapshot`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/champion`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/candidates`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/evaluations`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/tournaments`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/frontier`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/regret`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/decision-sensitivity`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/dynamic-reserve`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/scorecard`
- `GET /v1/sites/{site_uid}/adaptive/policy-lab/intelligence`

## Safety boundary

Adaptive Policy Lab is a decision-analysis and shadow-policy subsystem. It does not contain
Modbus writes, relay addresses, generator controls, inverter controls, battery-protection
overrides, or arbitrary hardware commands. A policy promotion can affect which **shadow proposal**
is preferred; it cannot turn a proposal into an executable action.
