# Product contract

Morningstar PowerSite Autonomy is the **predictive planning** member of the Morningstar software
family. Its job is to turn normalized site evidence and future weather into calibrated estimates
of reserve risk, energy surplus, safe scheduling windows, sizing alternatives, and advisory action
plans.

## It owns

- historical site calibration and model-version history;
- probabilistic PV/load/SOC forecasting;
- battery digital-twin estimates derived from configured and observed evidence;
- flexible-load scheduling and system-sizing optimization;
- advisory external-energy requirement calculations;
- forecast-vs-actual scoring and calibration diagnostics;
- compact risk output for downstream incident/alert consumers.

## It consumes rather than duplicates

MorningstarModbusAPI remains authoritative for controller identity, device/register semantics,
telemetry, history, component graph/topology, power flow, energy ledger, and provenance.
PowerSiteSentinel remains authoritative for deterministic health findings and incident lifecycle.

## Non-goals and safety contract

Autonomy does not expose Modbus writes, coil writes, equalization, reset/configuration changes,
relay/load switching, generator start/stop, SNMP SET, or arbitrary command passthrough. Scheduling,
optimization, auxiliary-energy results, risk feeds, and action plans are decision-support output.
They do not execute hardware actions.

## Trust model

The service prefers explicit uncertainty over fake certainty:

- missing measurements are not converted to zero;
- historical learning has sample-count and fallback notes;
- Sentinel warnings widen uncertainty instead of inventing unsupported derating values;
- forecasts identify their model/calibration version;
- predicted values are never presented as measurements;
- paired Monte Carlo seeds are used for comparative planning where possible.
