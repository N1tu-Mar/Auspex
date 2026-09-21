# Workstream: foundation

## Objective

Phase 0 vertical foundation: one command starts web/API/database and all baseline checks pass. **Status: complete on `work/foundation`, awaiting integration into `develop`.**

## Owned paths

Root configuration (`package.json`, `pnpm-workspace.yaml`, `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`, `biome.json`, `playwright.config.ts`, `alembic.ini`, `.env.example`, `.dockerignore`, `.python-version`), `compose.yaml`, `apps/*/Dockerfile`, `infra/**`, `database/**`, `packages/contracts/**`, `scripts/**`, `.github/**`.

Starter code handed to other streams after integration: `apps/api/**` → backend, `apps/web/**` → frontend, `tests/e2e/**` → QA.

## Current base commit

`c54ad44` (`develop`).

## Decisions made

- **Contract source of truth:** Pydantic models in `packages/contracts/auspex_contracts`. FastAPI renders OpenAPI (`packages/contracts/openapi/openapi.json`); `openapi-typescript` generates `packages/contracts/generated/api.d.ts`, consumed by the web app as `@auspex/contracts`. One generator, no hand-written TS domain types. `pnpm contracts:check` fails on drift.
- **Core contract:** `BetSlip` (original input, ≥1 legs, `stake_usd`, optional `gross_payout_usd`) and `BetLeg`; enums `Sport`, `MarketType`, `Side`, `LegStatus`, `Recommendation`. Strict (`extra="forbid"`, frozen). Money and prices are `Decimal`; `market_price_usd` is in (0, 1). `event_start_utc` requires an offset and is normalized to UTC.
- **API:** `GET /api/health` (probes DB), `POST /api/v1/bet-slips/validate` (validate/normalize only, no persistence). Settings validated by pydantic-settings; startup fails without a `postgresql+psycopg://` `DATABASE_URL`.
- **Database:** PostgreSQL 17, bound to `127.0.0.1` only. App uses non-superuser role `auspex_app` that owns the `auspex` database (created by `infra/postgres/init-app-role.sh`). Sessions pinned to UTC. Migration `0001` creates append-only `bet_slips` (uuid, `created_at timestamptz`, `original_input`, `slip jsonb`). The API container runs `alembic upgrade head` on start.
- **Tooling:** Biome (TS/JSON format + lint), Ruff (Python format + lint), `tsc` and `mypy --strict`, Vitest + Testing Library, pytest, Playwright (Chromium, 1 worker). TypeScript pinned to 5.x because `openapi-typescript` requires the TS 5 JS API.
- **Deferred to owning streams:** Tailwind, shadcn/ui, TanStack Query, React Hook Form, Zod (frontend); `httpx` provider clients (research); `bet_legs` table and further schema (request through foundation).

## Contracts consumed or produced

Produced: `auspex_contracts` (Python), `openapi.json`, `@auspex/contracts` TS types, fixture `packages/contracts/fixtures/bet_slip.valid.json`, migration `0001`.

## Commands and tests

Run on 2026-09-21, local (macOS, Docker via colima) and in a fresh clone:

- `docker compose up -d --build --wait` → db/api/web healthy; `curl localhost:5173/api/health` → `{"status":"ok","database":"ok"}`
- `pnpm check` → pass (Biome, Ruff, tsc, mypy strict, 2 Vitest, 14 pytest, contract drift check)
- `pnpm test:db` → 2 pass (migrations apply, `alembic check` finds no model drift, UTC round-trip)
- `pnpm test:e2e` → 1 pass (Playwright smoke: web → API → DB)
- Verified in DB: `auspex_app` is not superuser and owns `bet_slips` and `alembic_version`; timezone `UTC`.

CI (`.github/workflows/ci.yml`) mirrors this: `checks` job runs `pnpm check`; `stack` job runs Compose, `pnpm test:db`, and Playwright. CI has not run on GitHub yet (no remote configured).

## Known issues

- Generated TS types for `Decimal` fields are `number | string`; the API returns decimal strings. Clients should treat money/prices as strings and never do money math in JS floats.
- Fields with defaults (for example `BetLeg.status`) are typed required in generated TS because input/output schemas are merged (`separate_input_output_schemas=False`).
- The web container runs the Vite dev server (no hot reload from host; rebuild with `docker compose up --build`). Use `pnpm --filter web dev` on the host for iteration.
- With colima, the repo must live under `$HOME` for the database init-script bind mount to work.
- Local setup required installing Homebrew `docker-compose` and adding `cliPluginsExtraDirs` to `~/.docker/config.json` (backup at `~/.docker/config.json.bak`).
- Starlette/anyio emit a `BlockingPortal` deprecation warning under `TestClient`; filtered in pytest config.

## Integration order

Foundation first. Merge `work/foundation` into `develop`, then create backend/research/prediction worktrees per `docs/agent-workflow.md`.

## Last completed commit

`3decd0a` (implementation). This note is committed in the following docs commit on `work/foundation`.

## Next smallest task

Serve schema requests from backend (likely `bet_legs` columns or persistence endpoint support) via `docs/workstreams/requests/`.
