# Wind Forecast Decision Desk

A leakage-safe decision-support desk for a UK utility buying day-ahead power. It answers: *what wind forecast was available when the D-1 decision was made, and how much additional thermal cover is prudent?*

**Live demo:** [day-ahead-wind-desk.vercel.app](https://day-ahead-wind-desk.vercel.app)

## What it does

- Selects the latest Elexon `WINDFOR` forecast published no later than a configurable D-1 UK cutoff (default **09:30 Europe/London**).
- Shows a 48 half-hour decision profile, optional actuals, and a prior-only P10–P90 uncertainty band.
- Turns the P90 forecast error into a clear procurement action: “buy an extra X MW on top of the thermal gap.”
- Provides accuracy KPIs, error by hour, horizon analysis, and forecast-publication evolution.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn backend.api:app --reload
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open `http://localhost:5173`. The API OpenAPI documentation is at `http://localhost:8000/docs`.

Or run both services with:

```bash
docker compose up --build
```

## Data and methodology

Only Elexon data is used. `FUELHH` (filtered to `WIND`) provides actual half-hourly generation. `WINDFOR` provides forecast publication history. The baked January 2026 snapshot is in `data/snapshot/`; regenerate it with:

```bash
.venv/bin/python -m backend.ingest
```

The retrieval starts on 30 December 2025 so 1 January targets can use D-1 forecasts. Forecast error is `actual − forecast`, so a positive P90 error is the extra wind shortfall that a prudent buyer buffers.

WINDFOR's source targets are hourly and FUELHH is half-hourly. The app transparently carries each hourly source value across its two matching half-hours; it does not fabricate a higher-resolution forecast. P10/P90 bands use delivery days earlier than the day being assessed—never the same or future days.

See [assumptions](docs/assumptions.md) and the [cutoff ADR](docs/adr/0001-decision-cutoff.md).

## Architecture

```text
Elexon API → async ingestion CLI → Parquet snapshot → FastAPI JSON API → React + ECharts
```

`backend/analytics.py` contains the pure calculation layer and `tests/test_analytics.py` covers as-of selection, missing data, half-hour mapping, and prior-only bands. GitHub Actions runs linting, tests, frontend build, and Docker build.

## Limitations and next steps

This is a historical decision-support backtest, not a trading recommendation. It does not invent demand, weather, capacity, or price data. Production extensions would add live snapshot refresh, richer weather features, probabilistic modelling, and user authentication/audit trails.

## AI usage disclosure

This project was implemented with assistance from OpenAI Codex. AI assistance was used to scaffold the frontend and backend, draft documentation, and propose tests; the data selection, assumptions, leakage controls, validation, and final verification are represented explicitly in the source and documentation.
