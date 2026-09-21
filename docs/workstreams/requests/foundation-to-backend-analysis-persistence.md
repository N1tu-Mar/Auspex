# Request: backend to adopt analysis models and expose analysis runs

- From: foundation (`work/foundation`)
- To: backend (`apps/api/**`)
- Blocking: `frontend-analysis-contracts.md` (needs an endpoint that returns `AnalysisRun`).

## What landed

- Migrations `0003`–`0006` and `apps/api/app/analysis_models.py` (new file; no edits to `db.py`). It imports `Base` from `app.db`; you own it from here. `database/migrations/env.py` imports it so `alembic check` covers the tables.
- Contracts `AnalysisRun`, `LegAnalysis`, `EvidenceSnapshot`, `FeatureSnapshot`, `EventSnapshot`, `MarketSnapshot`, and others in `auspex_contracts`. Already in `openapi.json` and `api.d.ts`.
- **Behavior change:** `bet_slips` and `intake_records` now reject `UPDATE`, `DELETE`, and `TRUNCATE` with a database trigger. Your intake persistence must only insert (it already does; `supersedes_id` is the edit path). Any test cleanup that deletes rows will fail; use rollback or unique ids.

## Ask

1. Add a route that returns `AnalysisRun` (for example `GET /api/v1/analyses/{id}`) so the frontend types are referenced by a route. Run `pnpm contracts` afterward; `scripts/render_openapi.py` will keep the schemas identical.
2. Persist an analysis in one transaction: sources, events/markets (idempotent lookup by natural key), snapshots, then `analysis_runs`, then `analysis_legs`. Insert evidence rows with `ON CONFLICT DO NOTHING`. Never update.
3. Set `code_version` to the git commit and `as_of_utc` to the data cutoff.
