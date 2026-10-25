"""FastAPI application serving the baked decision-support snapshot."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.analytics import (
    compute_errors,
    error_by_hour,
    json_safe,
    metrics,
    select_latest_forecast,
    serialise_records,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshot"
LONDON = ZoneInfo("Europe/London")

app = FastAPI(title="Wind Forecast Decision Desk API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def snapshot() -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        return pd.read_parquet(DATA_DIR / "forecasts.parquet"), pd.read_parquet(DATA_DIR / "actuals.parquet")
    except FileNotFoundError as exc:
        raise RuntimeError("Snapshot unavailable. Run `python -m backend.ingest` first.") from exc


def decision_cutoff(delivery_day: date, cutoff: time) -> datetime:
    return datetime.combine(delivery_day - timedelta(days=1), cutoff, tzinfo=LONDON)


def daily_errors(delivery_day: date, cutoff: time) -> pd.DataFrame:
    forecasts, actuals = snapshot()
    selected = select_latest_forecast(forecasts, decision_cutoff(delivery_day, cutoff))
    errors = compute_errors(selected, actuals)
    return errors.loc[errors["delivery_date"] == delivery_day].reset_index(drop=True)


def historical_errors(cutoff: time) -> pd.DataFrame:
    _, actuals = snapshot()
    dates = sorted(actuals["startTime"].dt.date.unique())
    return pd.concat([daily_errors(day, cutoff) for day in dates], ignore_index=True)


@app.get("/health")
def health() -> dict[str, str]:
    forecasts, actuals = snapshot()
    return {"status": "ok", "forecasts": str(len(forecasts)), "actuals": str(len(actuals))}


@app.get("/decision")
def decision(
    delivery_day: date = Query(..., description="UK delivery date"),
    cutoff_hour: int = Query(9, ge=0, le=23),
    cutoff_minute: int = Query(30, ge=0, le=59),
) -> dict:
    cutoff = time(cutoff_hour, cutoff_minute)
    frame = daily_errors(delivery_day, cutoff)
    if frame.empty:
        raise HTTPException(status_code=404, detail="No snapshot data for this delivery date")
    # Prior-only uncertainty is computed by the analytics core; importing here avoids API mutation.
    from backend.analytics import add_prior_error_bands

    prior = historical_errors(cutoff)
    limited = prior.loc[prior["delivery_date"] <= delivery_day]
    bands = add_prior_error_bands(limited)
    result = bands.loc[bands["delivery_date"] == delivery_day]
    return {
        "delivery_day": delivery_day.isoformat(),
        "cutoff": decision_cutoff(delivery_day, cutoff).isoformat(),
        "slots": serialise_records(result),
        "metrics": metrics(result),
        "method": "Hourly WINDFOR values are held across each following two FUELHH half-hours.",
    }


@app.get("/accuracy")
def accuracy(cutoff_hour: int = Query(9, ge=0, le=23), cutoff_minute: int = Query(30, ge=0, le=59)) -> dict:
    frame = historical_errors(time(cutoff_hour, cutoff_minute))
    valid = frame.dropna(subset=["error_mw"])
    horizon = valid.groupby("horizon_bucket_hours", as_index=False).agg(
        mae_mw=("abs_error_mw", "mean"), bias_mw=("error_mw", "mean"), count=("error_mw", "size")
    )
    by_wind = valid.assign(wind_bin=pd.cut(valid["forecast_mw"], bins=5)).groupby("wind_bin", observed=False).agg(
        mae_mw=("abs_error_mw", "mean"), count=("error_mw", "size")
    ).reset_index()
    return {
        "metrics": metrics(valid),
        "errors": serialise_records(valid),
        "by_hour": serialise_records(error_by_hour(valid)),
        "by_horizon": serialise_records(horizon),
        "by_wind": json_safe(by_wind.to_dict(orient="records")),
    }


@app.get("/evolution")
def evolution(delivery_day: date = Query(...)) -> dict:
    forecasts, actuals = snapshot()
    target = forecasts.loc[forecasts["startTime"].dt.date == delivery_day].copy()
    actual = actuals.loc[actuals["startTime"].dt.date == delivery_day, ["startTime", "generation"]]
    if target.empty:
        raise HTTPException(status_code=404, detail="No forecast data for this delivery date")
    target = target.rename(columns={"generation": "forecast_mw"})
    actual = actual.rename(columns={"generation": "actual_mw"})
    actual["forecast_slot"] = actual["startTime"].dt.floor("h")
    target["forecast_slot"] = target["startTime"].dt.floor("h")
    joined = target.merge(actual[["forecast_slot", "actual_mw"]], on="forecast_slot", how="left")
    return {"delivery_day": delivery_day.isoformat(), "points": serialise_records(joined)}
