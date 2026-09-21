# Auspex

> **Read the signs. Price the outcome.**

Auspex is a private, evidence-first decision platform for Polymarket US sports markets and combos. It turns a proposed position into an auditable analysis: normalized legs, timestamped evidence, sport-specific probability estimates, market-price comparisons, correlation-aware combo math, and paper-trade performance tracking.

It supports disciplined decision-making—not certainty or automated wagering. A valid result can be `CONSIDER`, `PASS`, `AVOID`, or `INSUFFICIENT_DATA`; every estimate must state its uncertainty and evidence freshness.

## Why the name

In ancient Rome, an *auspex* interpreted signs to judge whether an undertaking was favorable. That is the product’s central metaphor: collect meaningful signals, distinguish evidence from noise, and judge whether a market position is worth taking. The product prices the outcome; it does not promise one. See the [Latin reference](https://logeion.uchicago.edu/auspex?utm_source=chatgpt.com).

## Scope

- Sports: NFL, college football, MLB, and selected soccer competitions.
- Initial mode: pregame analysis and paper trading only.
- Core capabilities: market intake, structured research, deterministic probability/EV/correlation calculations, concise source-backed explanations, and calibration tracking.
- Explicit exclusions: automatic execution, trading credentials, multi-user accounts, billing, and public access.

## Architecture

Auspex is a modular monolith:

```text
React/Vite web app -> FastAPI API -> research + prediction modules -> PostgreSQL
```

The prescribed stack is React, TypeScript, Vite, Tailwind, TanStack Query, React Hook Form, Zod, Python 3.12+, FastAPI, Pydantic v2, PostgreSQL, SQLAlchemy/Alembic, `pnpm`, `uv`, and Docker Compose. Quantitative calculations live in typed deterministic code; LLMs may only assist with parsing, evidence classification, summaries, and explanations.

## Current status

**Phase 0 foundation is in place**: monorepo layout, pnpm + uv workspaces, minimal React/Vite web app, FastAPI API, Docker Compose with one private PostgreSQL, SQLAlchemy/Alembic migrations, typed `BetSlip`/`BetLeg` contracts, generated TypeScript types, baseline checks, and CI. No product screens, provider integrations, or prediction models exist yet. See [docs/workstreams/foundation.md](docs/workstreams/foundation.md).

Read [prompt.md](prompt.md) for the complete product and engineering specification. Read [docs/agent-workflow.md](docs/agent-workflow.md) before launching parallel implementation work.

## Quick start

Prerequisite: Docker with the Compose plugin. Start the web/API/database stack with one command:

```bash
docker compose up --build
```

- Web: <http://localhost:5173> (shows API and database health)
- API: <http://localhost:8000/api/health>, docs at <http://localhost:8000/docs>
- PostgreSQL: `localhost:5432`, bound to localhost only

The API runs `alembic upgrade head` on start. Defaults are local-only fake credentials; copy `.env.example` to `.env` to override them. Stop with `docker compose down` (add `-v` to delete the database volume).

## Development commands

Prerequisites for host-side checks: Node 22+, pnpm 10 (`corepack enable`), uv, and Python 3.12+ (uv installs it from `.python-version` when missing).

```bash
pnpm install && uv sync          # install JS and Python dependencies
cp .env.example .env             # host-side DATABASE_URL for API, Alembic, and DB tests

pnpm check                       # all baseline checks: lint, typecheck, unit tests, contract drift
pnpm fmt                         # auto-format and fix lint (Biome + Ruff)
pnpm lint                        # Biome (TS/JSON) + Ruff lint/format check (Python)
pnpm typecheck                   # tsc + mypy --strict
pnpm test                        # Vitest + pytest (unit and contract; no database)
pnpm contracts                   # regenerate OpenAPI JSON and TypeScript types
pnpm contracts:check             # fail if generated contracts drifted from the Pydantic source

docker compose up -d --build --wait   # stack required by the next two
pnpm test:db                     # migrations apply, models match migrations, UTC round-trip
pnpm exec playwright install chromium # once
pnpm test:e2e                    # Playwright smoke test against the running stack

uv run alembic revision --autogenerate -m "describe change"   # foundation stream only
uv run uvicorn app.main:app --app-dir apps/api --reload       # API on the host
pnpm --filter web dev                                         # web on the host
```

## Contracts

The Pydantic models in `packages/contracts/auspex_contracts` are the single source of truth for cross-language domain types. `pnpm contracts` renders the FastAPI OpenAPI document to `packages/contracts/openapi/openapi.json` and generates `packages/contracts/generated/api.d.ts`; the web app imports types from `@auspex/contracts`. Never hand-edit generated files or duplicate domain types in TypeScript. CI fails on drift.

## Layout

```text
apps/api/              FastAPI app (app/) and tests
apps/web/              React/Vite app (src/) and tests
packages/contracts/    Pydantic contracts, fixtures, generated OpenAPI + TypeScript
database/migrations/   Alembic migrations (serialized through the foundation stream)
infra/postgres/        Database init script (non-superuser application role)
tests/e2e/             Playwright smoke tests
scripts/               Developer scripts
```

## Delivery path

1. Establish the foundation: monorepo structure, tooling, Compose, baseline checks, schemas, and CI.
2. Add market intake and normalized, editable bet slips.
3. Build reproducible evidence collection and snapshots.
4. Add deterministic pricing, EV, correlation, and sport adapters, starting with NFL and MLB.
5. Build the analysis workspace, then paper-trading and calibration views.

## Working on Auspex

Use `main` only for integration. After the foundation baseline exists, create isolated Git worktrees for foundation/contracts, backend, research, prediction, frontend, and QA. Each workstream owns its files, updates its status note, runs focused checks, and commits before integration. The exact handoff rules and ready-to-paste agent prompts are in [docs/agent-workflow.md](docs/agent-workflow.md).
