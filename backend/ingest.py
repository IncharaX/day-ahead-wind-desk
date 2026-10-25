"""Fetch, validate, and persist a reproducible Elexon dataset snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

API_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
LOGGER = logging.getLogger(__name__)
FORECAST_COLUMNS = ("publishTime", "startTime", "generation")
ACTUAL_COLUMNS = ("publishTime", "startTime", "fuelType", "generation")


@dataclass(frozen=True)
class SnapshotMetadata:
    created_at: str
    api_base: str
    publish_from: str
    publish_to: str
    delivery_from: str
    delivery_to: str
    forecast_rows: int
    actual_rows: int


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


async def fetch_dataset(
    client: httpx.AsyncClient, dataset: str, params: dict[str, str], attempts: int = 3
) -> list[dict[str, Any]]:
    """Fetch a stream endpoint with bounded retries for transient failures."""
    url = f"{API_BASE}/datasets/{dataset}/stream"
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError(f"Unexpected {dataset} response: expected a JSON array")
            LOGGER.info("fetched_dataset", extra={"dataset": dataset, "rows": len(payload)})
            return payload
        except (httpx.HTTPError, TypeError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Failed to fetch {dataset} after {attempts} attempts") from exc
            await asyncio.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _frame(rows: Iterable[dict[str, Any]], required: tuple[str, ...], name: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"{name}: missing required columns {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{name}: API returned no rows")
    for column in ("publishTime", "startTime"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    frame["generation"] = pd.to_numeric(frame["generation"], errors="coerce")
    if frame[list(required)].isna().any().any():
        raise ValueError(f"{name}: required values contain nulls or invalid timestamps")
    if (frame["generation"] < 0).any():
        raise ValueError(f"{name}: generation cannot be negative")
    return frame


def validate_forecasts(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = _frame(rows, FORECAST_COLUMNS, "WINDFOR")
    duplicates = frame.duplicated(["publishTime", "startTime"], keep=False)
    if duplicates.any():
        raise ValueError("WINDFOR: duplicate publishTime/startTime pairs")
    if (frame["startTime"] < frame["publishTime"]).all():
        raise ValueError("WINDFOR: every target precedes its publication")
    return frame.loc[:, list(FORECAST_COLUMNS)].sort_values(["startTime", "publishTime"])


def validate_actuals(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = _frame(rows, ACTUAL_COLUMNS, "FUELHH")
    frame = frame.loc[frame["fuelType"].eq("WIND")].copy()
    if frame.empty:
        raise ValueError("FUELHH: no WIND rows returned")
    # A later publication is the authoritative actual if the source republishes a slot.
    frame = frame.sort_values("publishTime").drop_duplicates("startTime", keep="last")
    return frame.loc[:, ["startTime", "generation"]].sort_values("startTime")


async def build_snapshot(publish_from: str, publish_to: str, output_dir: Path) -> SnapshotMetadata:
    from_dt, to_dt = _utc(publish_from), _utc(publish_to)
    if from_dt >= to_dt:
        raise ValueError("publish_from must precede publish_to")
    params = {
        "publishDateTimeFrom": from_dt.isoformat().replace("+00:00", "Z"),
        "publishDateTimeTo": to_dt.isoformat().replace("+00:00", "Z"),
    }
    async with httpx.AsyncClient(timeout=60.0, headers={"Accept": "application/json"}) as client:
        forecast_rows, actual_rows = await asyncio.gather(
            fetch_dataset(client, "WINDFOR", params),
            fetch_dataset(client, "FUELHH", {**params, "fuelType": "WIND"}),
        )
    forecasts, actuals = validate_forecasts(forecast_rows), validate_actuals(actual_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    forecasts.to_parquet(output_dir / "forecasts.parquet", index=False)
    actuals.to_parquet(output_dir / "actuals.parquet", index=False)
    delivery_from = actuals["startTime"].min().isoformat()
    delivery_to = actuals["startTime"].max().isoformat()
    metadata = SnapshotMetadata(
        created_at=datetime.now(timezone.utc).isoformat(),
        api_base=API_BASE,
        publish_from=params["publishDateTimeFrom"],
        publish_to=params["publishDateTimeTo"],
        delivery_from=delivery_from,
        delivery_to=delivery_to,
        forecast_rows=len(forecasts),
        actual_rows=len(actuals),
    )
    (output_dir / "metadata.json").write_text(json.dumps(asdict(metadata), indent=2) + "\n")
    LOGGER.info("snapshot_written", extra=asdict(metadata))
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-from", default="2025-12-30T00:00:00Z")
    parser.add_argument("--publish-to", default="2026-02-01T00:00:00Z")
    parser.add_argument("--output-dir", type=Path, default=Path("data/snapshot"))
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    metadata = asyncio.run(build_snapshot(args.publish_from, args.publish_to, args.output_dir))
    print(json.dumps(asdict(metadata), indent=2))


if __name__ == "__main__":
    main()
