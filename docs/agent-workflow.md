# Auspex multi-agent delivery workflow

## Current gate

Auspex is initialized but has no application baseline. Run the **foundation prompt** alone first. Do not create implementation worktrees until it lands on `develop` with working format, lint, type-check, test, Compose, and shared-contract commands. This follows the canonical brief and keeps later work independent.

## Operating model

`develop` is the integration branch; it is not a feature workspace. Each implementation agent receives a separate worktree and branch, owns only its assigned file surface, commits focused changes, updates its workstream note, and hands off a commit SHA. An integrator merges in this order:

```text
foundation/contracts -> backend -> research + prediction -> frontend -> QA
```

Use at most three implementation agents concurrently plus one integrator. Begin a new wave only after its dependency commits are integrated. Never give two agents ownership of a shared schema, generated client, migration, lockfile, or workstream note.

## Shared prompt preamble

Prefix every implementation prompt with this text:

```text
You are working on Auspex, a single-user, evidence-first Polymarket US sports decision platform. Read AGENTS.md, prompt.md, and docs/workstreams/<your-stream>.md before acting. Confirm your branch and worktree, inspect git status, and keep changes within your assigned ownership area. Do not add execution, credentials, accounts, billing, or public access. Preserve timestamped evidence and keep math in deterministic typed code. Work in small vertical slices: implement, run the narrowest relevant checks, update your workstream note with changed files/tests/limits, inspect git diff --check, and commit with a specific conventional message. Do not edit shared contracts or migrations unless your assignment explicitly owns them. Stop and write a request under docs/workstreams/requests/ if you need another stream to change an interface.
```

## Wave 0 — one foundation agent

Run this prompt in the local checkout (or a dedicated `work/foundation` branch after it is created):

```text
[Use the shared prompt preamble with stream foundation.]

Own Phase 0 foundation only. Establish the Auspex monorepo structure described in prompt.md; pnpm and uv project configuration; React/Vite and FastAPI starter applications; Docker Compose with one PostgreSQL service; application-owned SQLAlchemy/Alembic setup; environment example/schema; formatting, lint, type-check, unit-test, contract-test, and smoke-test commands; and CI. Define only the smallest core shared enums/schemas necessary for a typed BetSlip/BetLeg contract, with one authoritative schema source and no duplicated hand-written cross-language domain types. Keep every service as a minimal, working vertical slice. Document exact commands in README and docs/workstreams/foundation.md. Do not create real provider integrations, product screens, prediction models, or additional worktrees. Acceptance: a fresh developer can run one documented command to start web/API/database and all baseline checks pass.
```

## Worktree setup after Wave 0

From the clean integration checkout after foundation is merged:

```bash
git switch develop
git worktree add ../auspex-backend -b work/backend
git worktree add ../auspex-research -b work/research
git worktree add ../auspex-prediction -b work/prediction
git worktree add ../auspex-frontend -b work/frontend
git worktree add ../auspex-qa -b work/qa
git worktree list
```

Do not run the above over existing paths or branches. Managed Codex worktrees may be used instead, but each still needs an isolated branch before committing. Codex’s official worktree guidance confirms that worktrees enable parallel chats while a branch can only be checked out in one worktree at a time.

## Wave 1 — parallel prompts

### Backend

```text
[Use the shared prompt preamble with stream backend.]

Own apps/api/** only, consuming the integrated foundation contracts. Implement the Phase 1 API vertical slice for manual/pasted pregame market intake: validation, draft persistence, normalized BetSlip responses, trace IDs, structured provider-independent errors, and append-only analysis records. Use deterministic fixtures, never a live provider as a test dependency. Clearly return unsupported or ambiguous resolution states; never guess an event or participant. Add focused API and integration tests. Do not edit generated contracts, database migrations, or research/prediction/frontend files; request needed changes through the request directory.
```

### Research/data

```text
[Use the shared prompt preamble with stream research.]

Own services/research/** only. Implement provider interfaces, structured error types, response timestamps, cache policies, strict timeouts, bounded retries with jitter, rate-limit handling, schema validation, and fixture support. Start with a provider-neutral Polymarket US read-only adapter boundary and deterministic fixture-backed market normalization helper; do not scrape or bypass restrictions. Produce immutable source/evidence snapshot shapes that distinguish confirmed facts, projections, rumors, opinion, and inference. Add unit/contract tests. Do not own migrations, API endpoints, prediction formulas, or UI.
```

### Prediction

```text
[Use the shared prompt preamble with stream prediction.]

Own services/prediction/** and services/sports/** only. Build deterministic, typed, thoroughly tested primitives for market-price/implied-probability conversion, de-vigging, break-even probability, expected profit/return, combo independence baseline, bounds validation, and explicit insufficient-data outcomes. Establish the SportAdapter interface and begin narrow NFL/MLB pregame coverage definitions—no live analysis, opaque LLM math, or unexplained model probabilities. Treat correlation as a contract/framework with transparent warnings, not a fabricated model. Do not edit API, frontend, generated contracts, or database migrations.
```

## Wave 2 — dependent prompts

### Frontend

```text
[Use the shared prompt preamble with stream frontend.]

Own apps/web/** only. After the Phase 1 API contract is integrated, implement the New Analysis vertical slice and the Analysis Workspace shell using the prescribed React stack. Create an evidence-first research-workstation interface, not a casino: readable tables, timestamps/freshness badges, restrained status colors, clear uncertainty, and progressive disclosure. Support empty, loading, partial-success, stale, conflicting-evidence, unsupported, provider-failure, validation-error, and success states. Use the installed frontend-design and Playwright skills when available. Add accessible component/integration tests and browser coverage for paste-to-resolved-slip flow. Consume generated contracts; do not hand-maintain duplicate domain types.
```

### QA/docs

```text
[Use the shared prompt preamble with stream qa.]

Own tests/e2e/**, tests/contract/**, tests/integration/**, and operational documentation only. After the dependent services are integrated, create deterministic cross-service and Playwright tests for a single market and multi-leg combo, ambiguity correction, partial provider failure, stale/unsupported data, paper-trade capture, and core keyboard/accessibility behavior. Use resilient role/label/text locators; no arbitrary sleeps. Record run commands, known limitations, and results in your workstream note. Do not modify application behavior except minimal testability hooks agreed with the owner stream.
```

## Integrator prompt

```text
You are the Auspex integration agent on develop. Read AGENTS.md, prompt.md, all affected workstream notes, and each candidate branch’s diff before merging. Integrate only clean, focused commits in dependency order. Resolve conflicts by preserving the canonical contract and requesting clarification from the owning stream rather than silently redesigning. After each merge, run the smallest cross-boundary checks; at the milestone boundary run the full baseline suite. Update docs/workstreams/integration.md with merged SHAs, commands/results, environment or migration changes, and remaining limitations. Do not develop features directly on develop.
```

## Handoff template

Every agent ends with:

```text
Branch/worktree:
Commit SHA:
Owned files changed:
Checks run and result:
Contract/migration impact:
Known limitations:
Requests for other streams:
```
