# Product definition

## Primary question

> Will this site have enough energy over the next hours or days, how uncertain is that answer, and what changes improve the outcome?

Autonomy is a probabilistic planning layer above MorningstarModbusAPI. It does not duplicate Modbus discovery, device identity, register decoding, or raw history. It does not duplicate Sentinel's deterministic incident lifecycle.

## v0.1 contract

- forecast solar production and load on an hourly horizon;
- simulate usable battery reserve;
- publish P10/P50/P90 trajectories and breach probabilities;
- retain explicit input provenance/quality;
- compare baseline against read-only what-if scenarios;
- persist forecasts for later calibration and backtesting;
- remain fully useful on a local LAN without a proprietary cloud.

## Non-goals

- Modbus writes or controller configuration;
- automatic load shedding;
- generator start/stop;
- pretending probabilistic forecasts are observed facts;
- battery state-of-health claims without sufficient evidence;
- hiding missing instrumentation by silently inventing values.
