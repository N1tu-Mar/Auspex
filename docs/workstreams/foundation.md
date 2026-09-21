# Workstream: foundation

## Objective

Phase 0 vertical foundation: one command starts web/API/database and all baseline checks pass. **Status: complete and integrated into `main`.**

Phase 1 follow-up (this branch): serve backend intake requests — regenerated contracts and migration `0002` (`intake_records`) — and register research/prediction/sports services in root tooling. **Status: ready to integrate.**

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

## Contracts consumed or produced

Produced: `auspex_contracts` (Python), `openapi.json`, `@auspex/contracts` TS types (now including intake routes/schemas), fixture `packages/contracts/fixtures/bet_slip.valid.json`, migrations `0001`, `0002`.

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
- Prediction §2 (period/scope, player-prop stat type, venue/roof, promoting result dataclasses) — deferred; request marks it future and no consumer needs it yet.
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

Serve prediction §2 contract fields (period/scope, player-prop stat type, venue/roof) when the first real model needs them.
