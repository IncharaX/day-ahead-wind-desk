from datetime import date, datetime, timezone

import pandas as pd
import pytest

from backend.analytics import add_prior_error_bands, compute_errors, metrics, select_latest_forecast


def utc(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def test_as_of_selection_never_uses_a_future_publication() -> None:
    forecasts = pd.DataFrame(
        {
            "startTime": [utc("2026-01-02T00:00:00"), utc("2026-01-02T00:00:00")],
            "publishTime": [utc("2026-01-01T08:00:00"), utc("2026-01-01T10:00:00")],
            "generation": [100, 200],
        }
    )
    result = select_latest_forecast(forecasts, datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc))
    assert result["generation"].tolist() == [100]


def test_as_of_selection_rejects_naive_cutoff() -> None:
    forecasts = pd.DataFrame(columns=["startTime", "publishTime", "generation"])
    with pytest.raises(ValueError, match="timezone-aware"):
        select_latest_forecast(forecasts, datetime(2026, 1, 1, 9, 30))


def test_half_hour_actuals_use_the_hourly_source_forecast() -> None:
    selected = pd.DataFrame(
        {
            "startTime": [utc("2026-01-02T00:00:00")],
            "publishTime": [utc("2026-01-01T09:00:00")],
            "generation": [100],
            "horizon_hours": [15.0],
        }
    )
    actuals = pd.DataFrame(
        {"startTime": [utc("2026-01-02T00:00:00"), utc("2026-01-02T00:30:00")], "generation": [110, 90]}
    )
    result = compute_errors(selected, actuals)
    assert result["forecast_mw"].tolist() == [100, 100]
    assert result["error_mw"].tolist() == [10, -10]


def test_bands_only_use_prior_delivery_days() -> None:
    times = [utc("2026-01-01T00:00:00"), utc("2026-01-02T00:00:00")]
    errors = pd.DataFrame(
        {
            "startTime": times,
            "delivery_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "horizon_bucket_hours": [20.0, 20.0],
            "error_mw": [10.0, 1000.0],
        }
    )
    result = add_prior_error_bands(errors, min_samples=1)
    assert pd.isna(result.loc[0, "p90_error_mw"])
    assert result.loc[1, "p90_error_mw"] == 10.0


def test_metrics_excludes_missing_matches() -> None:
    summary = metrics(pd.DataFrame({"actual_mw": [100, 100], "forecast_mw": [90, None], "error_mw": [10, None]}))
    assert summary["count"] == 1
    assert summary["mae_mw"] == 10.0
    assert summary["nmae"] == 0.1
