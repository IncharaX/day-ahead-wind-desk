# ADR 0001: model the purchase decision as an as-of cutoff

**Status:** Accepted  
**Date:** 2026-10-25

## Context

`WINDFOR` contains several forecast publications for one target half-hour. Selecting a later publication when simulating a D-1 purchase decision would use information that was unavailable at the time.

## Decision

The default decision cutoff is 09:30 in `Europe/London` on the calendar day before delivery. For each target interval, select the record with the largest `publishTime` less than or equal to this cutoff. The UI exposes the time as a configurable control.

## Consequences

- The analytics layer must accept timezone-aware timestamps and never select a record published after the cutoff.
- Forecast data must be fetched for late December 2025 to support 1 January delivery.
- Metrics and error bands are credible as a historical simulation, but their values change when the cutoff changes.

