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

The repository is at **Phase 0 / foundation setup**. The canonical brief, repository guidance, Git ignore rules, and the multi-agent delivery workflow are present. Application code, dependency manifests, database schema, Compose configuration, CI, tests, and worktrees have not been created yet.

Read [prompt.md](prompt.md) for the complete product and engineering specification. Read [docs/agent-workflow.md](docs/agent-workflow.md) before launching parallel implementation work.

## Delivery path

1. Establish the foundation: monorepo structure, tooling, Compose, baseline checks, schemas, and CI.
2. Add market intake and normalized, editable bet slips.
3. Build reproducible evidence collection and snapshots.
4. Add deterministic pricing, EV, correlation, and sport adapters, starting with NFL and MLB.
5. Build the analysis workspace, then paper-trading and calibration views.

## Working on Auspex

Use `develop` only for integration. After the foundation baseline exists, create isolated Git worktrees for foundation/contracts, backend, research, prediction, frontend, and QA. Each workstream owns its files, updates its status note, runs focused checks, and commits before integration. The exact handoff rules and ready-to-paste agent prompts are in [docs/agent-workflow.md](docs/agent-workflow.md).
