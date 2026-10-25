# Decision assumptions

## Decision boundary

The desk represents a utility purchasing power for a delivery day `D` at **09:30 Europe/London on D-1**. This is a product assumption, rather than a claim about a particular market gate closure. The control is configurable so an analyst can test another decision time.

For every target half-hour `T` on `D`, the selected record is the forecast with the greatest `publishTime` that is no later than that decision cutoff. This is an **as-of** join and prevents future information leaking into the backtest.

All timestamps are retained in UTC for storage and comparisons. The user-facing cutoff is interpreted in `Europe/London`; January is GMT, so the initial default is 09:30 UTC. The code must use timezone-aware datetimes so the control remains correct across daylight-saving changes.

## Data and units

- Source: Elexon Insights API only.
- Actuals: `FUELHH`, filtered to `fuelType=WIND`, using half-hourly generation in MW.
- Forecasts: `WINDFOR`, retaining `startTime`, `publishTime`, and `generation` in MW.
- Scope: delivery dates 1–31 January 2026 (48 half-hourly settlement periods per normal day).
- Retrieval: request forecast publication history from at least 30 December 2025 through 31 January 2026 so the first delivery day has usable D-1 forecasts. The exact retrieval window is recorded in snapshot metadata.
- Capacity normalisation: normalized MAE is MAE divided by the maximum observed actual wind generation in the evaluation cohort. This is explicit and avoids importing an external installed-capacity series.

## Accuracy and uncertainty

- Error is `actual_mw - forecast_mw`: a positive error means wind was under-forecast, so the buyer would have over-purchased thermal generation; negative error means a wind shortfall.
- MAE, RMSE, bias, and normalized MAE are calculated only where both a selected forecast and an actual are present.
- P10/P90 error bands are estimated using delivery days through **D-2** only. At a D-1 morning decision, D-1 actuals are incomplete and are excluded to avoid leakage. The initial policy uses an expanding history with a minimum number of observations, falling back to an all-prior-horizons pool when a horizon bucket is sparse. The precise fallback is exposed in the API response.
- The headline horizon is `startTime - publishTime`; for a 09:30 D-1 decision it should broadly land in the 14–38 hour range.
- A 90% procurement buffer is `max(0, -P10(actual - forecast))` for the relevant horizon. It is added to the thermal gap, never presented as demand data.

## Limitations

- Missing, duplicate, or non-30-minute records are flagged during ingestion rather than silently imputed.
- The product does not infer demand. A user-provided demand profile is optional and remains clearly labelled as user input.
- This is a historical decision-support backtest, not a probabilistic forecast model or a trading recommendation.
