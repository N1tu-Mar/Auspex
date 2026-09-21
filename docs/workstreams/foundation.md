# Workstream: foundation

## Objective

Phase 0 vertical foundation: one command starts web/API/database and all baseline checks pass. **Status: complete and integrated into `main`.**

Phase 1 follow-up (integrated): serve backend intake requests — regenerated contracts and migration `0002` (`intake_records`) — and register research/prediction/sports services in root tooling. **Status: complete and integrated into `main`.**

Phase 2 (this branch, `work/foundation`): canonical append-only data and analysis contracts — migrations `0003`–`0006`, Pydantic contracts for events, markets, evidence, features, and analysis runs. **Status: ready to integrate.**

## Owned paths

Root configuration (`package.json`, `pnpm-workspace.yaml`, `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`, `biome.json`, `playwright.config.ts`, `alembic.ini`, `.env.example`, `.dockerignore`, `.python-version`), `compose.yaml`, `apps/*/Dockerfile`, `infra/**`, `database/**`, `packages/contracts/**`, `scripts/**`, `.github/**`.

Starter code handed to other streams after integration: `apps/api/**` → backend, `apps/web/**` → frontend, `tests/e2e/**` → QA.

## Current base commit

`55611ba` (`main`), plus merges of `work/backend` at `7b3e96b` (needed to regenerate contracts from its routes), `work/research` at `3601575`, and `work/prediction` at `70c560b` (needed so their service directories exist as workspace members).

## Decisions made

- **Contract source of truth:** Pydantic models in `packages/contracts/auspex_contracts`. FastAPI renders OpenAPI (`packages/contracts/openapi/openapi.json`); `openapi-typescript` generates `packages/contracts/generated/api.d.ts`, consumed by the web app as `@auspex/contracts`. One generator, no hand-written TS domain types. `pnpm contracts:check` fails on drift.
- **Core contract:** `BetSlip` (original input, ≥1 legs, `stake_usd`, optional `gross_payout_usd`) and `BetLeg`; enums `Sport`, `MarketType`, `Side`, `LegStatus`, `Recommendation`. Strict (`extra="forbid"`, frozen). Money and prices are `Decimal`; `market_price_usd` is in (0, 1). `event_start_utc` requires an offset and is normalized to UTC.
- **API:** `GET /api/health` (probes DB), `POST /api/v1/bet-slips/validate` (validate/normalize only, no persistence). Settings validated by pydantic-settings; startup fails without a `postgresql+psycopg://` `DATABASE_URL`.
- **Database:** PostgreSQL 17, bound to `127.0.0.1` only. App uses non-superuser role `auspex_app` that owns the `auspex` database (created by `infra/postgres/init-app-role.sh`). Sessions pinned to UTC. Migration `0001` creates append-only `bet_slips` (uuid, `created_at timestamptz`, `original_input`, `slip jsonb`). The API container runs `alembic upgrade head` on start.
- **Tooling:** Biome (TS/JSON format + lint), Ruff (Python format + lint), `tsc` and `mypy --strict`, Vitest + Testing Library, pytest, Playwright (Chromium, 1 worker). TypeScript pinned to 5.x because `openapi-typescript` requires the TS 5 JS API.
- **Intake persistence (migration `0002`):** append-only `intake_records` — `id` (= response `trace_id`), `received_at timestamptz` (app-supplied, indexed), `source`, `state`, `original_input`, `result jsonb` (full `IntakeResult`), nullable FKs `bet_slip_id → bet_slips` and `supersedes_id → intake_records`. Check constraints: `source ∈ {manual, paste}`, `state ∈ {RESOLVED, NEEDS_RESOLUTION, REJECTED}`, `bet_slip_id` only when `RESOLVED`. Foundation added the matching `IntakeRecord` model in `apps/api/app/db.py` so `alembic check` stays green; backend owns it from here and wires persistence.
- **Intake schemas stay API-local.** `IntakeResult`/`LegDraft`/`IssueCode` remain in `apps/api/app/intake.py` until a second consumer (research/prediction) needs them in Python; the web app already gets them via generated TS.
- **Deferred to owning streams:** Tailwind, shadcn/ui, TanStack Query, React Hook Form, Zod (frontend); `httpx` provider clients (research); `bet_legs` table and further schema (request through foundation).

## Phase 2: analysis data foundation

### Contracts (`packages/contracts/auspex_contracts`)

| module | contracts |
|---|---|
| `market.py` | `Event`, `EventSnapshot`, `Market`, `MarketSnapshot`, `MarketSideQuote` |
| `evidence.py` | `SourceSnapshot`, `EvidenceItem`, `EvidenceSnapshot`, `ProviderFailure`, `ClaimKind`, `EvidenceCategory`, `ProviderErrorKind` |
| `features.py` | `FeatureSnapshot`, `FeatureObservation` |
| `analysis.py` | `LegEstimate`, `UncertaintyInterval`, `CorrelationWarning`, `DependencyKind`, `NaiveIndependentBaseline`, `ComboAssessment`, `PositionCosts`, `ExpectedValue`, `InsufficientData`, `RecommendationResult`, `LegAnalysis`, `AnalysisRun`, `AnalysisRef` |

All extend `_base.Contract` (`extra="forbid"`, frozen). Existing `BetSlip`/`BetLeg` shapes are unchanged. Money, prices, and probabilities are `Decimal`, serialized as strings. All timestamps are timezone-aware and normalized to UTC.

Evidence content hashes are identical to `services/research` (verified), so evidence already produced there stays valid. `AnalysisRun` validators enforce: leg indexes `0..n-1`; each leg has exactly one of an estimate or `InsufficientData`; a combo exists exactly when there are 2+ legs; `INSUFFICIENT_DATA` carries reasons and other recommendations do not; `CONSIDER` requires an estimate for every leg plus `expected_value`; `as_of_utc <= created_at`. `AnalysisRef` (analysis id, slip id, as-of, recommendation) is the only paper-trade-ready reference; no paper-trade behavior exists.

`scripts/render_openapi.py` (used by `scripts/contracts.sh`) merges the root contracts into `components.schemas` because no route references them yet. When a backend route returns one, FastAPI emits an identical schema and nothing changes.

### Tables

Models live in `apps/api/app/analysis_models.py`; Alembic reads them through `database/migrations/env.py`.

| table | kind | holds |
|---|---|---|
| `sources` | metadata | provider, publisher, URL, published/retrieved times, content hash for one retrieval |
| `events` | identity | canonical `event_id` (same string as `BetLeg.event_id`), sport, league |
| `event_snapshots` | snapshot | start time, status, participants at `captured_at`, plus `source_id` |
| `markets` | identity | `(provider, market_id)`, event, market type, line, slug. A different line is a different market |
| `market_snapshots` | snapshot | open flag, bid/ask, fee coefficient, side quotes, warnings, `source_id` |
| `evidence_items` | artifact | content-addressed by SHA-256 `evidence_id`; claim kind, extracted fact, `derived_from` |
| `evidence_snapshots` | artifact | content-addressed set of items for one event |
| `evidence_snapshot_items` | link | snapshot membership; `position` preserves the order the hash depends on |
| `provider_failures` | record | failed provider calls; `snapshot_id` set when they belong to a snapshot |
| `feature_snapshots` | snapshot | features for one event (`jsonb`, decimal-or-text values), feature-set version, evidence link |
| `analysis_runs` | record | slip link, as-of time, code and model version, recommendation, reasons, combo and EV (`jsonb`) |
| `analysis_legs` | record | per-leg probabilities and interval as exact `numeric`, insufficient-data reasons, FKs to the exact event/market/evidence/feature snapshots used |

`analysis_runs.id` and `bet_slips.id` are the FK targets for a future paper-trade table. `analysis_legs.leg_index` points into the saved slip's `legs` array (there is still no `bet_legs` table).

### Append-only semantics

Migration `0003` adds `forbid_row_change()` and `guard_append_only(table)`. Every table above, plus `bet_slips` and `intake_records`, has triggers that raise `restrict_violation` on `UPDATE`, `DELETE`, and `TRUNCATE`. A correction, a newer price, or a re-analysis is a new row. Content-addressed rows are inserted with `ON CONFLICT DO NOTHING`; a conflict is a duplicate, not a change. Child rows (snapshot items, failures, legs) are inserted in the same transaction as their parent. `DROP TABLE` still works, which downgrades need. The owner role can still disable triggers, so this guards against application bugs, not against the database owner. `ck_*` constraints mirror the contract validators so a bad write fails in the database even if a caller skips Pydantic.

### Migration order

`0001 bet_slips` → `0002 intake_records` → `0003 append_only_guard` (functions; triggers on 0001 and 0002 tables) → `0004 events_markets_sources` → `0005 evidence_provider_failures` → `0006 features_analysis_runs`. Each downgrade drops its tables; `0003` downgrade drops the triggers and functions, so downgrade runs in reverse order. `0004`–`0006` call `guard_append_only` for their tables.

### Checks (2026-09-21, worktree `../auspex-foundation`)

- `pnpm check` → pass (248 pytest not-db, Vitest, mypy strict on 54 files, Ruff, Biome, contract drift)
- `pnpm test:db` → 55 pass (upgrade, `alembic check`, stepwise downgrade to `0002` and re-upgrade, full chain round trip, TRUNCATE rejected on every table, UPDATE/DELETE rejected, 19 invalid rows and 9 invalid legs rejected)
- `pnpm contracts:check` → up to date; `git diff --check` → clean

### Known limitations (phase 2)

- `analysis_models.py` sits in `apps/api/app` because Alembic and the API share one `Base`; foundation created it and backend owns it from here.
- `combo`, `expected_value`, and feature values are `jsonb` shaped by the contracts, not columns; add columns when a query needs them.
- `ComboAssessment.joint_probability` is `InsufficientData` only, matching the current prediction code. Widen it when a validated correlation model exists.
- `Market.event_id` is required, so an event must be resolved before a market is stored. Research's `NormalizedMarket` has no event id yet.
- `services/research` and `services/prediction`/`sports` still define their own copies of these types until the requests below are served.
- Prediction §2 fields (period/scope, prop stat type, venue/roof) are still deferred.

## Contracts consumed or produced

Produced: `auspex_contracts` (Python), `openapi.json`, `@auspex/contracts` TS types (intake routes/schemas plus the phase 2 analysis, evidence, feature, and market schemas), fixture `packages/contracts/fixtures/bet_slip.valid.json`, migrations `0001`–`0006`.

## Commands and tests

Run on 2026-09-21, local (macOS, Docker via colima) and in a fresh clone:

- `docker compose up -d --build --wait` → db/api/web healthy; `curl localhost:5173/api/health` → `{"status":"ok","database":"ok"}`
- `pnpm check` → pass (Biome, Ruff, tsc, mypy strict, 2 Vitest, 14 pytest, contract drift check)
- `pnpm test:db` → 2 pass (migrations apply, `alembic check` finds no model drift, UTC round-trip)
- `pnpm test:e2e` → 1 pass (Playwright smoke: web → API → DB)
- Verified in DB: `auspex_app` is not superuser and owns `bet_slips` and `alembic_version`; timezone `UTC`.

CI (`.github/workflows/ci.yml`) mirrors this: `checks` job runs `pnpm check`; `stack` job runs Compose, `pnpm test:db`, and Playwright. CI has not run on GitHub yet (no remote configured).

Phase 1 follow-up, 2026-09-21 (worktree `../auspex-foundation`):

- `pnpm contracts` then `pnpm contracts:check` → up to date
- `pnpm check` → pass (221 pytest across api/contracts/prediction/research/sports, 2 Vitest, mypy strict on 42 files, Ruff, Biome, contract drift)
- `pnpm test:db` → 8 pass (upgrade + `alembic check`, downgrade to `0001` and re-upgrade, intake FK/supersedes round-trip in UTC, 4 constraint rejections)
- `git diff --check` → clean
- The research, prediction, and sports services are covered by the same `pnpm check`; `pnpm test:db` still 8 pass after registration.

## Requests

- `backend-intake-contracts-regen.md` — served (`3fdd051`).
- `backend-intake-persistence.md` — served (`460146b`).
- `research-tooling-registration.md` — served (`485dc33`, imports re-sorted in `ecb5546`). Added `services/research/pyproject.toml` (`auspex-research`: `auspex-contracts`, `httpx>=0.28`, `pydantic>=2.9`). Research should now delete the `services/research/conftest.py` `sys.path` shim.
- `prediction-to-foundation-services-tooling-and-contract-fields.md` §1 — served (same commits). Explicit `PYTHONPATH`/`MYPYPATH` invocations are no longer needed.
- Prediction §2 result dataclasses — served in phase 2 (`analysis.py`); the swap is `foundation-to-prediction-promoted-analysis-types.md`. Period/scope, player-prop stat type, and venue/roof fields remain deferred.
- `frontend-analysis-contracts.md` — schemas now in OpenAPI/TS (`AnalysisRun`, `LegAnalysis`, `ComboAssessment`, `CorrelationWarning`, `EvidenceSnapshot`, `EvidenceItem`, `ProviderFailure`, `Recommendation`, `InsufficientData`). Still blocked on a backend endpoint; see `foundation-to-backend-analysis-persistence.md`.
- Follow-up sweep on 2026-09-21: every file in `docs/workstreams/requests/` has been served or explicitly deferred, and no stream branch has commits missing from `main`. No new schema or contract changes were needed. Re-verified at `a67506b`: `pnpm contracts:check` up to date; `pnpm check` passes (221 pytest, 2 Vitest, mypy strict on 42 files); `pnpm test:db` 8 pass; `git diff --check` clean.

## Known issues

- Generated TS types for `Decimal` fields are `number | string`; the API returns decimal strings. Clients should treat money/prices as strings and never do money math in JS floats.
- Fields with defaults (for example `BetLeg.status`) are typed required in generated TS because input/output schemas are merged (`separate_input_output_schemas=False`).
- The web container runs the Vite dev server (no hot reload from host; rebuild with `docker compose up --build`). Use `pnpm --filter web dev` on the host for iteration.
- With colima, the repo must live under `$HOME` for the database init-script bind mount to work.
- Local setup required installing Homebrew `docker-compose` and adding `cliPluginsExtraDirs` to `~/.docker/config.json` (backup at `~/.docker/config.json.bak`).
- `intake_records` append-only is by convention (no UPDATE/DELETE trigger), same as `bet_slips`.
- `test:db` reuses the shared `auspex` Compose volume; the downgrade test drops and recreates `intake_records` rows.
- Starlette/anyio emit a `BlockingPortal` deprecation warning under `TestClient`; filtered in pytest config.

## Integration order

Done: `main` = `work/foundation` at `a67506b`, which includes `work/backend` `7b3e96b`, `work/research` `3601575`, and `work/prediction` `70c560b`. Each stream now merges `main`: backend persists intake through `IntakeRecord`; research removes its conftest shim.

## Last completed commit

`ecb5546` (tooling registration + import re-sort). This note is committed in the following docs commit on `work/foundation`.

## Next smallest task

After research, prediction, and backend serve the phase 2 requests: serve prediction §2 contract fields (period/scope, player-prop stat type, venue/roof) when the first real model needs them.
