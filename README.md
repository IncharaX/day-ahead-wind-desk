# Wind Forecast Decision Desk

A leakage-safe decision-support desk for a UK utility buying day-ahead power. It answers: *what wind forecast was available when the D-1 decision was made, and how much additional thermal cover is prudent?*

**Live demo:** [day-ahead-wind-desk.vercel.app](https://day-ahead-wind-desk.vercel.app)

## What it does

- Selects the latest Elexon `WINDFOR` forecast published no later than a configurable D-1 UK cutoff (default **09:30 Europe/London**).
- Shows a 48 half-hour decision profile, optional actuals, and a prior-only P10–P90 uncertainty band.
- Turns the lower-tail forecast error into a clear procurement action: “buy an extra X MW on top of the thermal gap.”
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

The retrieval starts on 30 December 2025 so 1 January targets can use D-1 forecasts. Forecast error is `actual − forecast`; a wind shortfall is therefore a negative error. The 90% thermal buffer is `max(0, −P10(error))` for the relevant horizon.

WINDFOR's source targets are hourly and FUELHH is half-hourly. The app transparently carries each hourly source value across its two matching half-hours; it does not fabricate a higher-resolution forecast. P10/P90 bands only use fully observed delivery days through D−2, never D−1, the same day, or future days. Early-January delivery days may therefore have insufficient history for an uncertainty band.

See [assumptions](docs/assumptions.md) and the [cutoff ADR](docs/adr/0001-decision-cutoff.md).

## Architecture

```text
Elexon API → async ingestion CLI → Parquet snapshot → FastAPI JSON API → React + ECharts
```

`backend/analytics.py` contains the pure calculation layer and `tests/test_analytics.py` covers as-of selection, missing data, half-hour mapping, and prior-only bands. GitHub Actions runs linting, tests, frontend build, and Docker build.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI app, ingestion CLI, and pure analytics functions. |
| `frontend/` | React + TypeScript + ECharts dashboard and frontend tests. |
| `data/snapshot/` | Versioned January 2026 Elexon Parquet snapshot and metadata. |
| `tests/` | Backend leakage, error-band, buffer, and resolution-mapping tests. |
| `docs/` | Assumptions, methodology, and architecture decision record. |
| `notebooks/` | Reproducible Elexon exploration notebook. |
| `.github/workflows/` | CI workflow for linting, tests, frontend build, and Docker build. |
| `Dockerfile` | Local/portable production container image. |
| `Dockerfile.vercel` | Single-container Vercel deployment definition. |
| `docker-compose.yml` | Local API and frontend development services. |

## Limitations and next steps

This is a historical decision-support backtest, not a trading recommendation. It does not invent demand, weather, capacity, or price data. Production extensions would add live snapshot refresh, richer weather features, probabilistic modelling, and user authentication/audit trails.

## AI usage disclosure

I used OpenAI Codex as an engineering assistant during this take-home exercise.

My contributions included:
- interpreting the assignment and defining the product scope;
- deciding the D-1 decision workflow and approving the 09:30 UK cutoff assumption;
- directing the implementation priorities and reviewing the product flow, dashboard design, and data presentation;
- validating the live application, creating the GitHub repository, authorising the Vercel deployment, and reviewing the final output;
- reviewing the methodology, limitations, and submission materials.

Codex assisted with implementation, including the React frontend, FastAPI backend, Docker/CI configuration, testing, documentation, and deployment troubleshooting.

All material methodology choices are documented in the repository. The implementation was tested against the included Elexon snapshot and manually reviewed before submission.
