"""Pure, leakage-safe analytics for the Wind Forecast Decision Desk."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd


def select_latest_forecast(forecasts: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    """Return the last forecast available for every target at an as-of cutoff.

    `cutoff` must be timezone aware. A forecast published after it is never eligible.
    """
    cutoff_timestamp = pd.Timestamp(cutoff)
    if cutoff_timestamp.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    required = {"publishTime", "startTime", "generation"}
    if missing := required.difference(forecasts.columns):
        raise ValueError(f"forecasts missing columns: {sorted(missing)}")
    eligible = forecasts.loc[forecasts["publishTime"] <= cutoff_timestamp].copy()
    eligible = eligible.sort_values(["startTime", "publishTime"])
    selected = eligible.drop_duplicates("startTime", keep="last").copy()
    selected["horizon_hours"] = (
        (selected["startTime"] - selected["publishTime"]).dt.total_seconds() / 3600
    )
    return selected.reset_index(drop=True)


def compute_errors(selected: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Join hourly forecasts to half-hourly actuals without inventing actual data.

    WINDFOR targets are hourly whereas FUELHH actuals are half-hourly. Each hourly
    source forecast is held for the following two half-hour observations; this
    transparent display-resolution mapping preserves the original forecast value.
    """
    forecasts = selected.rename(columns={"generation": "forecast_mw"}).copy()
    observed = actuals.rename(columns={"generation": "actual_mw"}).copy()
    forecasts["forecast_slot"] = forecasts["startTime"].dt.floor("h")
    observed["forecast_slot"] = observed["startTime"].dt.floor("h")
    result = observed.merge(
        forecasts[["forecast_slot", "publishTime", "forecast_mw", "horizon_hours"]],
        on="forecast_slot",
        how="left",
        validate="many_to_one",
    )
    result["error_mw"] = result["actual_mw"] - result["forecast_mw"]
    result["abs_error_mw"] = result["error_mw"].abs()
    # January is GMT, so this equals UTC for the supplied snapshot. Converting
    # explicitly keeps delivery dates and hours correct when BST dates are added.
    london_time = result["startTime"].dt.tz_convert("Europe/London")
    result["delivery_date"] = london_time.dt.date
    result["hour"] = london_time.dt.hour
    result["horizon_bucket_hours"] = (result["horizon_hours"] * 2).round() / 2
    return result.sort_values("startTime").reset_index(drop=True)


def metrics(errors: pd.DataFrame) -> dict[str, float | int | None]:
    """Calculate headline accuracy metrics over rows with both values present."""
    valid = errors.dropna(subset=["actual_mw", "forecast_mw", "error_mw"])
    if valid.empty:
        return {"count": 0, "mae_mw": None, "rmse_mw": None, "bias_mw": None, "nmae": None}
    error = valid["error_mw"]
    capacity_proxy = float(valid["actual_mw"].max())
    mae = float(error.abs().mean())
    return {
        "count": len(valid),
        "mae_mw": mae,
        "rmse_mw": float(np.sqrt(np.mean(np.square(error)))),
        "bias_mw": float(error.mean()),
        "nmae": float(mae / capacity_proxy) if capacity_proxy else None,
    }


def add_prior_error_bands(
    errors: pd.DataFrame, min_samples: int = 20, lag_days: int = 2
) -> pd.DataFrame:
    """Add P10/P90 error bands using fully observed delivery dates only.

    A matching half-hour horizon is preferred. If it has fewer than `min_samples`,
    all prior horizons are used; if that is still sparse, the band is null.

    For a D-1 morning decision, D-1 actuals are incomplete. `lag_days=2`
    ensures the history for delivery day D ends at D-2.
    """
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    if lag_days < 1:
        raise ValueError("lag_days must be positive")
    output = errors.copy()
    output["p10_error_mw"] = np.nan
    output["p90_error_mw"] = np.nan
    output["band_sample_count"] = 0
    for delivery_day, same_day in output.groupby("delivery_date", sort=True):
        history = output.loc[
            output["delivery_date"] <= delivery_day - timedelta(days=lag_days)
        ]
        for index, row in same_day.iterrows():
            candidates = history.loc[
                history["horizon_bucket_hours"].eq(row["horizon_bucket_hours"]), "error_mw"
            ].dropna()
            if len(candidates) < min_samples:
                candidates = history["error_mw"].dropna()
            if len(candidates) >= min_samples:
                output.loc[index, "p10_error_mw"] = candidates.quantile(0.10)
                output.loc[index, "p90_error_mw"] = candidates.quantile(0.90)
                output.loc[index, "band_sample_count"] = len(candidates)
    return output


def procurement_buffer_mw(decision: pd.DataFrame) -> float | None:
    """Return the maximum 90% thermal buffer implied by lower error tails.

    Error is actual minus forecast. Therefore wind shortfall is a *negative*
    error; P10 is the lower tail and `-P10` is the associated thermal buffer.
    """
    lower_tail = decision["p10_error_mw"].dropna()
    if lower_tail.empty:
        return None
    return max(0.0, float(-lower_tail.min()))


def procurement_buffer_slot(decision: pd.DataFrame) -> pd.Timestamp | None:
    """Return the UK delivery timestamp of the worst lower-tail buffer slot."""
    valid = decision.dropna(subset=["p10_error_mw"])
    if valid.empty or "startTime" not in valid:
        return None
    return valid.loc[valid["p10_error_mw"].idxmin(), "startTime"]


def decision_for_day(
    forecasts: pd.DataFrame, actuals: pd.DataFrame, delivery_day: date, cutoff: datetime
) -> pd.DataFrame:
    """Produce a selected day view, including historical uncertainty when available."""
    selected = select_latest_forecast(forecasts, cutoff)
    today = compute_errors(selected, actuals)
    cutoff_clock = cutoff.timetz().replace(tzinfo=None)
    history = errors_at_daily_cutoff(forecasts, actuals, delivery_day, cutoff_clock, cutoff.tzinfo)
    history = pd.concat([history, today.loc[today["delivery_date"] == delivery_day]], ignore_index=True)
    with_bands = add_prior_error_bands(history)
    return with_bands.loc[with_bands["delivery_date"] == delivery_day].reset_index(drop=True)


def errors_at_daily_cutoff(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    through_day: date,
    cutoff_time: time,
    tzinfo: Any,
) -> pd.DataFrame:
    """Reconstruct each prior day with its own D-1 as-of cutoff."""
    records: list[pd.DataFrame] = []
    days = sorted({day for day in actuals["startTime"].dt.date if day < through_day})
    for day in days:
        cutoff = datetime.combine(day - timedelta(days=1), cutoff_time, tzinfo=tzinfo)
        selected = select_latest_forecast(forecasts, cutoff)
        errors = compute_errors(selected, actuals)
        records.append(errors.loc[errors["delivery_date"] == day])
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def error_by_hour(errors: pd.DataFrame) -> pd.DataFrame:
    valid = errors.dropna(subset=["error_mw"])
    return valid.groupby("hour", as_index=False).agg(mae_mw=("abs_error_mw", "mean"), bias_mw=("error_mw", "mean"))


def serialise_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert timestamp/dataframe scalar values into JSON-friendly records."""
    return json_safe(frame.to_dict(orient="records"))


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Interval):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if pd.isna(value) else float(value)
    return value
