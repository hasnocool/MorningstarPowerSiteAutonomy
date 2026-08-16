# API

## Forecast

`GET /v1/sites/{site_uid}/forecast?hours=72`

Returns hourly P10/P50/P90 values for solar power, load power, and SOC plus:

- expected solar/load energy;
- minimum SOC percentiles;
- reserve-breach probability;
- earliest simulated reserve breach;
- no-solar autonomy estimate;
- discretionary energy above reserve;
- confidence and input quality.

Horizons are bounded from 1 to 168 hours.

## Scenario

`POST /v1/sites/{site_uid}/scenarios`

Supported changes:

- one or more additional fixed-power load windows;
- array watts;
- battery capacity Wh;
- reserve percent.

The same random seed is used for baseline and scenario so the comparison is paired rather than dominated by unrelated Monte Carlo noise.

## History

`GET /v1/sites/{site_uid}/forecasts?limit=20`

Returns persisted forecast payloads newest first.
