# v0.6 Evidence Intelligence and Self-Validating Digital Twin

PowerSiteAutonomy v0.6 adds an evidence-intelligence layer that makes uncertainty in the
site model explicit and quantifies whether additional evidence is likely to change a decision.
The subsystem remains advisory and read-only: it evaluates evidence and recommendations but does
not write controller registers, switch loads, or execute hardware actions.

## Capabilities

- parameter beliefs with mean, uncertainty, P10/P50/P90, confidence, sample counts, and provenance
- precision-weighted updates from measured, derived, configured, learned, fleet, or forecast evidence
- explicit competing hypotheses with supporting and contradicting evidence
- digital-twin ensembles with posterior weighting from prediction error
- champion/challenger promotion with minimum-history and posterior-margin gates
- expected-information-gain ranking for passive observation opportunities
- decision-sensitivity tracking for assumptions capable of changing the preferred recommendation
- recommendation stability scoring from value margin, model confidence, and sensitive parameters
- value-of-information economics for deciding whether to wait for more evidence before a purchase
- async orchestration using `asyncio.to_thread()` so CPU-heavy ensemble analysis does not block I/O

## API

`POST /v1/evidence/analyze` accepts one evidence-analysis request and returns the updated parameter
beliefs, ranked hypotheses, twin tournament result, information-gain priorities, recommendation
stability, and value-of-information estimates.

The endpoint is intentionally generic. Existing forecast, fleet, shadow-autopilot, and economic
services can assemble their current evidence into this contract without giving the evidence engine
hardware access.

## Parameter beliefs

A scalar physical parameter is represented by a distribution rather than a single point estimate.
For example, battery usable capacity can carry a mean, standard deviation, physical bounds,
confidence, sample count, and provenance. New observations are combined with the prior using
precision weighting, with observation quality widening low-quality measurement uncertainty.

This prevents one noisy measurement from silently replacing a stable calibrated estimate while
still allowing repeated high-quality measurements to reduce uncertainty.

## Twin tournament

Multiple plausible digital twins can be evaluated against reality at the same time. Their prior
weights are updated from prediction error. A challenger can replace the champion only when:

1. it has at least the configured minimum evaluation history; and
2. its posterior advantage exceeds the promotion margin.

The default implementation uses conservative fixed gates so a short lucky streak cannot replace a
well-established champion.

## Passive evidence acquisition

Evidence opportunities describe observations the site can gather naturally, such as an overnight
discharge interval or a clear-sky midday PV interval. The engine estimates the expected reduction
in parameter uncertainty and multiplies it by a caller-supplied economic-impact factor to rank what
to learn next.

No physical experiment is executed by this service.

## Decision sensitivity and recommendation stability

A sensitivity case records whether plausible low/high values for one uncertain parameter would
change the winning decision. Parameters that can flip the recommendation are surfaced as unstable.
The stability result combines:

- the economic/value margin between the best and second-best alternatives;
- average model confidence; and
- a penalty for highly sensitive or decision-changing assumptions.

This produces a low/medium/high recommendation-stability classification alongside the underlying
confidence and unstable parameters.

## Value of information

For each observation opportunity, v0.6 estimates the economic value of reducing the current
decision uncertainty. When recommendation stability is low and the expected information value is
material, the engine can advise waiting for evidence before committing to the recommendation.
When the expected value is negligible, it reports that further evidence is unlikely to justify
delaying the decision.

The value-of-information calculation is deliberately conservative and transparent rather than a
black-box purchasing model.

## Integration direction

The next integration step is to have the existing site service automatically populate the generic
v0.6 request from:

- calibrated PV/load/battery parameters;
- Shadow Autopilot forecast-error attribution;
- fleet hardware priors and degradation evidence;
- v0.5 upgrade alternatives and replacement economics; and
- naturally occurring telemetry windows.

That integration can remain read-only and can be added incrementally without changing the evidence
contract or creating a hardware executor.
