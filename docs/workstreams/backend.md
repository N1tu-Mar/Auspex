# Workstream: backend

## Objective

Phase 1 market intake plus the first end-to-end analysis workflow: intake results are stored append-only
and retrievable by trace ID; a RESOLVED slip is analyzed (research, features, estimate, correlation,
recommendation policy) into an immutable stored `AnalysisRun`. Never guess events, participants,
settlement, or probabilities.

## Owned paths

`apps/api/**`, `docs/workstreams/backend.md`, `docs/workstreams/requests/backend-*.md`.

## Current base commit

`b2e05a6` (`main`, merged into `work/backend`). Branch `work/backend`, worktree `../auspex-backend`.

## Decisions made

### Intake (unchanged rules; see git history for the grammar)

- `POST /bet-slips/intake/manual` and `/paste` now insert one `intake_records` row per call (plus a
  `bet_slips` row when RESOLVED) in one transaction. `IntakeResult.bet_slip_id` is set only when RESOLVED.
  `trace_id` = `intake_records.id`. A DB failure returns 503 `PERSISTENCE_FAILED` and stores nothing.
- `GET /bet-slips/intake/{trace_id}` returns the stored `IntakeResult` (editable legs, issues, slip).
- Paste resolution is provider-backed: `get_event_catalog` loads open Polymarket US events for the next
  14 days through the research `PolymarketUSClient` (bounded paging, error if the window exceeds 10 pages;
  never silently truncates). Only NFL/MLB league slugs with exactly two teams and a start time are
  resolvable. Matching is exact after `normalize_name` on team name, abbreviation, alias, safe name.
- The provider does **not** say which team is home. So a provider-matched moneyline/spread leg stays
  `NEEDS_RESOLUTION` (`MISSING_FIELD` on `side`), totals need home/away supplied, and the provider gives no
  settlement rule ref (`SETTLEMENT_UNCONFIRMED`). The user completes the leg via manual intake. Fixture
  catalogs (tests) may still carry home/away and rule refs and can reach RESOLVED.
- Catalog fetch failure -> `CATALOG_UNAVAILABLE` per leg (not `EVENT_NOT_FOUND`), state NEEDS_RESOLUTION.
- Structured errors for non-validation failures: `ApiError` (`trace_id`, `received_at_utc`, `code`,
  `message`), codes `NOT_FOUND`, `INTAKE_NOT_RESOLVED`, `PERSISTENCE_FAILED`. Validation errors on
  `/bet-slips/intake` and `/analyses` keep the `IntakeError` envelope.

### Analysis workflow (`app/analysis.py`, `analysis_store.py`, `analysis_record.py`, `providers.py`)

- `POST /api/v1/analyses` body `{intake_trace_id | bet_slip_id, estimated_fees_usd?, estimated_slippage_usd?}`
  -> 201 `AnalysisRecord`: `analysis` (`AnalysisRun`), `events`, `markets`, `market_snapshots`,
  `evidence_snapshots`, `feature_snapshots`, `provider_failures`. `GET /api/v1/analyses/{id}` returns the same
  object rebuilt from rows (POST also returns the reloaded rows, so they are identical). 409 if the intake is
  not RESOLVED; 404 for unknown ids. Re-analysis inserts a new run.
- Per event: fetch each leg's market by `polymarket_market_id` and every injected evidence provider; failures
  (provider errors, stale drops, market schema errors) are kept inside that event's evidence snapshot
  through research `build_snapshot`. Freshness windows are explicit constants (`MAX_AGE`). No retry logic here:
  the research `Fetcher` retries are bounded and every attempt is logged (`auspex.providers`).
- Features: no extractor exists, so a `FeatureSnapshot` with `feature_set_version="unassembled-v0"` and no
  features is stored per event; the sport adapter's coverage gate then abstains with named missing features.
- Estimates: `estimate_leg` with an empty registry, so every leg is INSUFFICIENT_DATA today (no ACTIVE model
  exists). Sports without an adapter (NCAAF, SOCCER) abstain with "no model coverage for X".
- Combos (2+ legs): correlation warnings and a labeled naive baseline are stored; the baseline uses
  market-implied probabilities when any leg lacks an estimate (stated in the reasons). Joint probability is
  always INSUFFICIENT_DATA; a combo is therefore always INSUFFICIENT_DATA.
- Recommendation: INSUFFICIENT_DATA (with reasons) when any leg lacks an estimate, a market is closed/of a
  different type or line, the slip is a combo, or fees/slippage were not supplied (never assumed). Otherwise
  the prediction `recommend` policy runs on a single-leg EV. Gross payout defaults to stake / price rounded
  down to cents (contract precision) when the slip has none.
- `code_version` = `AUSPEX_CODE_VERSION` env, else `git rev-parse HEAD`, else `unknown` (Dockerfile has a
  build arg). `model_version` = comma-joined estimate versions, else `none`. `as_of_utc` = clock at start;
  `created_at` after all retrievals.
- Persistence is one transaction, insert-only: sources, events/markets (`ON CONFLICT DO NOTHING`), market
  snapshots, evidence items/snapshots (content-addressed, idempotent), failures, feature snapshots, run, legs.
  Failures are stored in the evidence snapshot's canonical order (provider, kind, message) so the content
  hash re-validates on read.

## Contracts consumed or produced

Consumed: `auspex_contracts` `BetSlip`, `AnalysisRun`, `LegAnalysis`, `EvidenceSnapshot`, `FeatureSnapshot`,
`Market`, `MarketSnapshot`, `Event`, `ProviderFailure`; research, prediction, and sports Python APIs.
Produced (API-local): `IntakeResult` (+`bet_slip_id`), `IntakeIssue` (+`CATALOG_UNAVAILABLE`), `EventCandidate`
(+`participants`, home/away optional), `AnalysisRequest`, `AnalysisRecord`, `ApiError`, `ErrorCode`.
Generated OpenAPI/TS types are NOT regenerated here: see `requests/backend-to-foundation-analysis-contracts.md`.

## Commands and tests

Run 2026-09-21 in `../auspex-backend` (Postgres from `docker compose`, `DATABASE_URL` from `.env.example`):

- `uv run pytest -q` -> 451 pass (apps/api: 62, incl. 21 db-marked); `uv run pytest apps/api -m 'not db'` -> 41 pass
- `uv run mypy` (strict) -> clean; `pnpm lint` -> pass
- `pnpm contracts:check` -> **fails**: `schema name collision with an API model: AnalysisRun` (foundation request)
- New tests: `test_intake_provider.py` (fixture transport, outage, persistence calls), `test_analysis_policy.py`
  (stubbed estimator: CONSIDER/AVOID/PASS/fees-missing), `test_analysis_workflow.py` (db: intake round trip,
  409/404, insufficient data, POST==GET, re-run is a new run, partial provider failure, stale drop, market
  outage, combo, unmodeled sport, market mismatch).

## Known issues

- Contracts/generated types are stale until foundation serves the request; CI (`contracts:check`) red until then.
- Every real analysis is INSUFFICIENT_DATA: no feature extractor, no ACTIVE model, no odds/stats/news providers.
  The CONSIDER/AVOID/PASS path is tested only with a stubbed estimator.
- Provider events give no home/away or settlement rule, so provider-backed paste never reaches RESOLVED alone.
- Manual intake still trusts a supplied `event_id`; the analysis only cross-checks the market's type and line.
- No `EventSnapshot`, `SourceRun` persistence, or consensus (de-vigged odds) probability.
- `AUTH`/`STALE` failure kinds are remapped (request filed). DB tests commit rows (append-only; not deletable).
- Analyses run inside a sync DB session in an async route; fine for single-user, revisit if concurrency grows.

## Integration order

After foundation serves the contracts request; then frontend consumes regenerated types.

## Last completed commit

See `git log work/backend`.

## Next smallest task

Feature extraction for one sport (owned by prediction/research), then a recorded provider capture so
home/away and settlement refs can be confirmed.
