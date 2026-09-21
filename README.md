# Auspex

> **Read the signs. Price the outcome.**

Auspex is a private, evidence-first tool for analyzing Polymarket US sports markets and combos. It turns a proposed position into an auditable analysis: normalized legs, timestamped evidence, sport-specific probability estimates, comparison with the market price, correlation-aware combo math, and (later) paper-trade performance tracking.

It is meant to support disciplined decisions. It offers no certainty and places no bets. Every result is one of `CONSIDER`, `PASS`, `AVOID`, or `INSUFFICIENT_DATA`, and every estimate must state its uncertainty and how fresh its evidence is.

## Why the name

In ancient Rome, an *auspex* read signs to judge whether an undertaking was favorable. That is the product's central metaphor: collect meaningful signals, separate evidence from noise, and judge whether a market position is worth taking. The product prices the outcome; it does not promise one. See the [Latin reference](https://logeion.uchicago.edu/auspex).

## Current status

The system works end to end for **intake**. The **analysis pipeline** is also wired through, but on purpose it produces no probabilities yet.

| Area | What works today |
|---|---|
| Intake | Paste or enter a slip by hand. The API parses it into editable legs, resolves them against Polymarket US events, and returns `RESOLVED`, `NEEDS_RESOLUTION`, or `REJECTED` with a fix hint for each issue. Every intake is stored and can be retrieved by trace ID. |
| Analysis | `POST /api/v1/analyses` fetches markets and evidence, stores snapshots, runs coverage gates, correlation warnings, and the recommendation policy, and saves an immutable `AnalysisRun`. |
| Prediction | Deterministic `Decimal` math for odds conversion, de-vig, break-even, EV, and the naive combo baseline, plus correlation warnings, a model registry, uncertainty, the recommendation policy, and evaluation metrics (Brier, log loss, calibration). |
| Sports | `SportAdapter` contract with narrow pregame NFL and MLB coverage: moneyline, spread/run line, and total. |
| Research | Read-only Polymarket US client with timeouts, bounded retries, a TTL cache, event-catalog resolution, and content-hashed evidence snapshots. |
| Web | A **New Analysis** page (paste, edit legs, check), an intake review table with recovery hints, and an **Analysis Workspace** shell. |
| Data | PostgreSQL with append-only tables. Triggers reject `UPDATE`, `DELETE`, and `TRUNCATE`; any correction is written as a new row. |

**What that means in practice:** every real analysis currently returns `INSUFFICIENT_DATA`. No validated model is registered, no feature extractor exists, and no odds, stats, news, or weather providers are connected. A combo is always `INSUFFICIENT_DATA` because no validated correlation model exists. This is by design. The platform abstains rather than invent a number.

Other known gaps:
- Polymarket US events don't say which team is home and don't give a settlement rule, so pasted legs usually need finishing by hand before they resolve.
- Payout and settlement semantics are still unconfirmed against Polymarket US rules.
- Paper trading and calibration views don't exist yet.
- CI has not run on GitHub.

Per-stream detail lives in [docs/workstreams/](docs/workstreams/).

## Scope

- **Sports:** NFL and MLB first. College football and selected soccer competitions come later.
- **Mode:** pregame analysis only, then paper trading.
- **Explicitly excluded:** automatic execution, trading credentials, multi-user accounts, billing, and public access.
- **Quantitative work** lives in typed, deterministic, unit-tested code. LLMs may help with parsing, evidence classification, summaries, and explanations, never with arithmetic, probabilities, or EV.

## Architecture

Auspex is a modular monolith:

```text
React/Vite web ──> FastAPI API ──> services/research    (Polymarket US, evidence snapshots)
                        │     └──> services/prediction  (odds, EV, de-vig, combos, policy, evaluation)
                        │     └──> services/sports      (SportAdapter: NFL, MLB coverage + estimator)
                        └──> PostgreSQL (append-only, Alembic)
```

**Stack:**
- Frontend: React 19, TypeScript, Vite, Tailwind 4, TanStack Query, React Hook Form, and Zod.
- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy/Alembic, PostgreSQL 17, and httpx.
- Tooling: pnpm, uv, and Docker Compose.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | API and database health |
| `POST` | `/api/v1/bet-slips/validate` | Validate and normalize a `BetSlip` (not stored) |
| `POST` | `/api/v1/bet-slips/intake/manual` | Intake a structured slip; stored |
| `POST` | `/api/v1/bet-slips/intake/paste` | Parse pasted text into legs and resolve events; stored |
| `GET` | `/api/v1/bet-slips/intake/{trace_id}` | Fetch a stored intake result |
| `POST` | `/api/v1/analyses` | Analyze a resolved intake or slip; stores an `AnalysisRun` |
| `GET` | `/api/v1/analyses/{analysis_id}` | Fetch a stored analysis with its snapshots |

Interactive docs: <http://localhost:8000/docs>.

## Quick start

Prerequisite: Docker with the Compose plugin.

```bash
docker compose up --build
```

- **Web:** <http://localhost:5173>. This is New Analysis; the header shows API and database health.
- **API:** <http://localhost:8000/api/health>.
- **PostgreSQL:** `localhost:5432`, bound to localhost only.

The API runs `alembic upgrade head` on start. The defaults are fake, local-only credentials; to override them, copy `.env.example` to `.env`.

Paste resolution calls the public, read-only Polymarket US API, so it needs network access. Without network access, pasted legs report `CATALOG_UNAVAILABLE`, and you can still complete them by hand.

To stop the stack, run `docker compose down`. Add `-v` to also delete the database volume.

## Development commands

Prerequisites for running checks on the host: Node 22+, pnpm 10 (`corepack enable`), uv, and Python 3.12+. uv installs the Python version pinned in `.python-version` if it's missing.

```bash
pnpm install && uv sync          # install JS and Python dependencies
cp .env.example .env             # host-side DATABASE_URL for API, Alembic, and DB tests

pnpm check                       # lint, typecheck, unit tests, contract drift (run before every commit)
pnpm fmt                         # auto-format and fix lint (Biome + Ruff)
pnpm lint                        # Biome (TS/JSON) + Ruff lint/format check (Python)
pnpm typecheck                   # tsc + mypy --strict (api, contracts, services, tests)
pnpm test                        # Vitest + pytest without a database (api, contracts, services, tests/)
pnpm contracts                   # regenerate OpenAPI JSON and TypeScript types
pnpm contracts:check             # fail if generated contracts drifted from the Pydantic source

docker compose up -d --build --wait   # stack required by the next two
pnpm test:db                     # migrations up/down, model drift, append-only triggers, constraints
pnpm exec playwright install chromium # once
pnpm test:e2e                    # Playwright: intake flows, UI states, accessibility

uv run alembic revision --autogenerate -m "describe change"   # foundation stream only
uv run uvicorn app.main:app --app-dir apps/api --reload       # API on the host
pnpm --filter web dev                                         # web on the host
```

## Contracts

The Pydantic models in `packages/contracts/auspex_contracts` are the single source of truth for types shared across languages:

- `bet_slip`
- `market`
- `evidence`
- `features`
- `analysis`

`pnpm contracts` renders the FastAPI OpenAPI document to `packages/contracts/openapi/openapi.json` and generates `packages/contracts/generated/api.d.ts`. The web app imports those types from `@auspex/contracts`.

Rules:
- Never hand-edit generated files.
- Never duplicate domain types in TypeScript.
- Treat money and prices as decimal strings on the client.
- CI fails on drift.

## Layout

```text
apps/api/              FastAPI app: intake, analysis workflow, persistence, and tests
apps/web/              React/Vite app: New Analysis, intake review, Analysis Workspace
packages/contracts/    Pydantic contracts, fixtures, generated OpenAPI + TypeScript
services/research/     Provider boundaries, Polymarket US client, cache, evidence snapshots
services/prediction/   Deterministic odds/EV/de-vig/combo math, registry, policy, evaluation
services/sports/       SportAdapter contract, NFL/MLB coverage, estimate orchestration
database/migrations/   Alembic migrations 0001–0006 (serialized through the foundation stream)
infra/postgres/        Database init script (non-superuser application role)
tests/e2e/             Playwright browser tests and fixtures
tests/integration/     Cross-service checks (e2e fixture parity with the real intake code)
tests/contract/        Contract tests for shared fixtures
scripts/               Contract generation and developer scripts
docs/workstreams/      Per-stream status notes and cross-stream requests
```

## Delivery path

| Phase | Status |
|---|---|
| 0. Foundation: monorepo, tooling, Compose, schemas, CI | Done |
| 1. Market intake: normalized, editable, persisted slips | Done |
| 2. Research: evidence collection and snapshots | Polymarket US and snapshots done; odds, stats, news, and weather providers not started |
| 3. Prediction: pricing, EV, correlation, NFL/MLB adapters | Primitives, gates, registry, and policy done; no validated model yet |
| 4. Decision interface: Analysis Workspace | Shell done; not yet rendering stored analyses |
| 5. Paper trading and calibration | Not started (evaluation metrics exist) |

## Working on Auspex

`main` is for integration only. Each workstream (foundation/contracts, backend, research, prediction, frontend, QA) works in its own Git worktree and branch, owns a fixed set of paths, updates its note in `docs/workstreams/`, runs focused checks, and commits often.

When one stream needs another to change something, it files a request under `docs/workstreams/requests/`. Migrations and shared contracts go through the foundation stream.

Read these before starting:
- [prompt.md](prompt.md): the full product and engineering specification.
- [AGENTS.md](AGENTS.md): repository rules.
- [docs/agent-workflow.md](docs/agent-workflow.md): handoff rules and agent prompts.
