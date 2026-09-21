# Master Build Prompt: Internal Polymarket Sports Decision Platform

> This file is the canonical product, architecture, workflow, and engineering brief for this repository. Claude Code and Codex must read it before planning architecture, starting a new workstream, changing shared contracts, or implementing a material feature.

## 1. Operating Role

You are the senior product engineer, quantitative systems engineer, data engineer, and design engineer responsible for building an internal sports-market decision platform for one user.

Build the product, not a disposable demo. The application should remain understandable, testable, resource-conscious, and extensible while moving quickly. Prefer direct, well-factored code over framework-heavy abstractions. Preserve evidence, timestamps, model versions, and calculation inputs so every recommendation can be audited later.

This is currently a single-user internal tool. Do not add Supabase, multi-tenancy, organizations, teams, invitations, subscription billing, user profiles, row-level security, or a public account system. The system should contain clear research, data, prediction, and explanation modules running as one coordinated application workflow.

Claude Code and Codex are development tools for this repository. They may work in separate Git worktrees, but they must follow the ownership, commit, testing, and integration rules in this document.

## 2. Product Mission

Build an internal platform that helps the owner make more disciplined, evidence-backed decisions on Polymarket US sports markets and combos across:

- NFL
- College football
- MLB
- Selected soccer leagues and competitions

The platform must help the user:

1. Paste or enter a potential single-market position or multi-leg combo.
2. Resolve every sport, league, event, team, player, market, side, line, start time, and settlement condition.
3. Collect current, relevant evidence without flooding the interface or model context.
4. Estimate a probability for each leg using reproducible sport-specific logic.
5. Compare that estimate with the quoted market price and external consensus odds.
6. Identify uncertainty, stale information, conflicting reports, and correlated legs.
7. Estimate the joint probability and expected value of a combo.
8. Explain the result concisely, with sources and an explicit as-of timestamp.
9. Record paper trades, outcomes, calibration, closing-line movement, and model performance.
10. Improve future estimates based on measured results rather than intuition or recent wins.

The objective is to improve decision quality and long-run expected value. The platform must never claim that a wager is guaranteed, certain, safe, or free money. It should often recommend passing when the edge is weak, the price is poor, the legs are overly correlated, or the evidence is incomplete.

## 3. Non-Negotiable Product Principles

### 3.1 Evidence before narrative

- Every factual claim that affects a recommendation needs a source URL, publisher, publication time when available, retrieval time, and event association.
- Distinguish confirmed information from projections, rumors, opinion, and inferred information.
- Prefer official league, team, injury, weather, lineup, and market sources when available.
- Store the evidence snapshot used for a prediction. Never silently replace historical evidence with newer data.
- Show the user when sources conflict.

### 3.2 Math outside the language model

- Language models may parse user input, extract structured facts, classify relevance, summarize news, and explain results.
- Language models must not be the source of truth for arithmetic, implied probabilities, de-vigging, expected value, bankroll calculations, correlation matrices, simulations, or calibration metrics.
- All quantitative calculations must live in deterministic, typed, unit-tested code.
- Never accept a model-produced number without validating its bounds, units, timestamp, and provenance.

### 3.3 Sport-specific modeling

- Share infrastructure and interfaces across sports.
- Do not force NFL, college football, MLB, and soccer through one universal model.
- Each sport adapter owns its feature definitions, market normalization, model selection, simulation assumptions, and settlement edge cases.
- Calibrate performance separately by sport, league, market type, and model version when sample size permits.

### 3.4 Uncertainty is a first-class output

- Return a probability interval or uncertainty tier with every estimate.
- Return `INSUFFICIENT_DATA` instead of inventing confidence.
- Track data freshness, missing fields, disagreement between sources, model coverage, and sample size.
- Separate confidence in the evidence from confidence in the prediction.

### 3.5 The system must be auditable

For every completed analysis, persist:

- Normalized input
- Original user input
- Polymarket market identifiers and quoted prices
- Retrieval timestamp and event start time
- Source metadata and extracted facts
- Feature snapshot
- Probability estimate and interval
- Model and code version
- Calculation inputs and outputs
- Recommendation
- Later outcome and settlement result

### 3.6 Paper trading comes before execution

- The initial product is analysis and paper trading only.
- Do not place trades automatically.
- Do not store trading credentials during the MVP.
- A future execution module must remain isolated behind explicit user confirmation, stake caps, daily loss caps, idempotency, audit logging, and a global kill switch.

## 4. Primary User Workflow

### 4.1 Input

The user should be able to provide one of the following:

- A Polymarket US event or market URL
- A Polymarket market identifier
- Pasted market or combo text
- A manually completed form
- A screenshot in a later phase

For combos, represent every leg independently. Never treat the combo as an opaque sentence.

### 4.2 Normalization

Normalize the submission into a typed `BetSlip` containing one or more `BetLeg` records. Resolve ambiguity before prediction. If two teams or players have similar names, do not guess.

Every leg must include, when applicable:

- Sport and league
- Event identifier
- Event start time and timezone
- Home and away participants
- Player identifier
- Market type
- Side
- Line or threshold
- Polymarket price
- Stake
- Gross potential payout
- Settlement rule reference
- Current status: pregame, live, completed, postponed, canceled, unsupported

The first supported mode is pregame analysis. Live-market analysis must be explicitly labeled unsupported until live data, latency, and settlement behavior are tested.

### 4.3 Research and feature snapshot

Collect only information that can materially change the estimate. Examples include:

- Current market price and price movement
- Consensus sportsbook odds and line movement
- Injury and availability status
- Confirmed or projected lineup/depth chart
- Starting pitcher or quarterback status
- Recent playing time, targets, carries, attempts, minutes, or lineup position
- Team efficiency and opponent-adjusted performance
- Rest, travel, scheduling congestion, and weather
- Park, stadium, surface, altitude, and home advantage
- Relevant coaching, tactical, or rotation changes
- Market settlement conditions

Research output must be structured before it is summarized. Deduplicate repeated reporting. Limit article body retention; store extracted facts, short excerpts when legally appropriate, hashes, and source metadata instead of entire copied pages.

### 4.4 Prediction

For each leg, calculate:

- Market-implied probability
- De-vigged consensus probability when external books are available
- Model probability
- Reasonable uncertainty interval
- Edge in percentage points
- Expected value after applicable fees and slippage
- Evidence-quality score
- Data-freshness status
- Primary upside factors
- Primary failure modes

For combos, calculate:

- Naive independent joint probability for comparison only
- Correlation-aware joint probability
- Fair combo price or fair decimal odds
- Break-even probability
- Expected profit and expected return
- Sensitivity to uncertain or correlated legs
- The leg contributing the most failure risk
- Whether removing a weak leg materially improves the proposition

Do not blindly multiply probabilities when legs share a game, team, player, game script, weather condition, or other causal dependency.

### 4.5 Decision output

Use only these top-level recommendation states:

- `CONSIDER`: measurable positive edge with acceptable evidence and uncertainty
- `PASS`: insufficient edge at the current price
- `AVOID`: material negative value, hidden correlation, stale market, or disproportionate risk
- `INSUFFICIENT_DATA`: the platform cannot support a responsible estimate

The result screen must display:

1. Recommendation and one-sentence reason
2. Model probability versus market break-even probability
3. Estimated edge and uncertainty
4. Each leg ranked from strongest to weakest
5. Correlation warnings
6. Evidence freshness and missing information
7. Concise source-backed explanation
8. A paper-trade action
9. A clear statement that the estimate is uncertain and not a guarantee

## 5. Quantitative Rules

### 5.1 Probability and payout definitions

Use named variables with explicit units. Never use an ambiguous field named only `odds`, `value`, or `payout`.

Suggested names:

- `market_price_usd`
- `implied_probability`
- `model_probability`
- `gross_payout_usd`
- `stake_usd`
- `estimated_fees_usd`
- `estimated_slippage_usd`
- `expected_profit_usd`
- `expected_return_pct`

If gross payout includes returned stake, the basic expected profit is:

```text
expected_profit = model_probability * gross_payout - stake - fees - slippage
```

Do not assume payout semantics. Confirm them from the Polymarket US response and settlement rules, normalize once, and cover them with tests.

### 5.2 External odds

- Capture several reputable books when legally and technically available.
- Preserve the timestamp and book for every observation.
- Remove vig before using sportsbook prices as a probability baseline.
- Use consensus rather than cherry-picking the price that supports a preferred outcome.
- Record opening, current, and closing prices when available.

### 5.3 Model evaluation

Track at minimum:

- Brier score
- Log loss
- Calibration by probability bucket
- Accuracy as a secondary descriptive metric
- Return on investment for paper positions
- Closing-line value when a comparable line exists
- Sample count
- Maximum drawdown of the simulated bankroll
- Performance by sport, league, market type, confidence tier, and model version

Do not promote a model because of a small winning streak. Require a meaningful sample and compare against simple baselines.

### 5.4 Staking

- The MVP records a proposed stake but does not optimize or execute it.
- Any future stake suggestion must be disabled until calibration is adequate.
- If added later, use conservative fractional Kelly only after incorporating uncertainty and hard exposure caps.
- Never encourage chasing losses or increasing stake merely because previous positions lost.

## 6. Sport Adapter Contract

Create a common typed interface and separate implementations.

```python
class SportAdapter(Protocol):
    sport: Sport

    def normalize_market(self, raw_market: RawMarket) -> NormalizedMarket: ...
    async def collect_features(self, event: Event, market: NormalizedMarket) -> FeatureSnapshot: ...
    def validate_coverage(self, snapshot: FeatureSnapshot) -> CoverageResult: ...
    def estimate_leg(self, snapshot: FeatureSnapshot) -> LegEstimate: ...
    def simulate_combo(self, legs: list[LegEstimate], context: ComboContext) -> ComboEstimate: ...
    def settlement_requirements(self, market: NormalizedMarket) -> SettlementRequirements: ...
```

### 6.1 NFL

Potential inputs include EPA, success rate, pace, neutral pass rate, pressure, coverage matchup, injuries, depth chart, snaps, routes, targets, carries, red-zone usage, weather, rest, travel, and expected game script.

Start with moneyline, spread, total, and high-volume player props. Avoid obscure props until reliable historical data exists.

### 6.2 College football

Potential inputs include opponent-adjusted efficiency, quarterback status, roster availability, transfer and depth-chart changes, strength of schedule, explosiveness, finishing drives, special teams, rest, and travel.

Data quality is less consistent than the NFL. Start with moneyline, spread, and total. Coverage must be league and team aware; do not pretend all programs have equal data quality.

### 6.3 MLB

Potential inputs include confirmed starting pitcher, pitch quality, platoon split, projected and confirmed lineup, bullpen availability, recent workload, park factors, weather, defense, base running, travel, and rest.

Pregame estimates must refresh after confirmed lineups. Clearly distinguish full-game, first-five-innings, team-total, and player markets.

### 6.4 Soccer

Potential inputs include expected goals, shot quality, lineup, injuries, rotation, formation, rest, travel, home advantage, league strength, goalkeeper status, schedule congestion, and competition incentives.

Soccer is not one uniform league. Begin with a deliberately limited coverage list, such as MLS, Premier League, Champions League, and selected major European competitions. Correctly model three-way results, draws, extra-time exclusions, and competition-specific settlement rules.

## 7. Technical Architecture

### 7.1 Chosen stack

Use this stack unless the repository already contains a justified equivalent:

- Frontend: React, TypeScript, Vite, Tailwind CSS, shadcn/ui
- Client data fetching: TanStack Query
- Forms and validation: React Hook Form plus Zod
- Backend: Python 3.12+, FastAPI, Pydantic v2
- Persistence: PostgreSQL controlled by the application
- ORM and migrations: SQLAlchemy 2.x and Alembic
- HTTP: `httpx` with async clients, strict timeouts, retries, and bounded concurrency
- Testing: Pytest, Vitest, React Testing Library, Playwright
- Local orchestration: Docker Compose
- Optional background jobs: Redis plus one lightweight worker only when durable asynchronous jobs are necessary
- Package management: `pnpm` for JavaScript and `uv` for Python

Do not use Supabase. Do not use Firebase. Do not expose PostgreSQL directly to the browser. Do not introduce Kubernetes, Kafka, Elasticsearch, a vector database, or a service mesh without measured evidence that the current architecture cannot meet the requirement.

### 7.2 Runtime components

```text
Browser
  -> React/Vite web application
  -> FastAPI application API
       -> orchestration service
       -> market normalization
       -> research pipeline
       -> prediction engine
       -> deterministic EV/correlation engine
       -> explanation renderer
       -> PostgreSQL
       -> optional bounded background worker
```

This is a modular monolith. Keep boundaries clear in code, but deploy the backend as one application plus at most one worker during the early phases.

### 7.3 Repository layout

Prefer the following structure:

```text
/
  AGENTS.md
  CLAUDE.md
  prompt.md
  README.md
  compose.yaml
  .env.example
  apps/
    web/
      src/
      tests/
    api/
      app/
      tests/
  packages/
    contracts/
      openapi/
      schemas/
      generated/
  services/
    research/
    prediction/
    sports/
      nfl/
      ncaaf/
      mlb/
      soccer/
  database/
    migrations/
    seeds/
  tests/
    contract/
    integration/
    e2e/
    fixtures/
  docs/
    architecture/
    decisions/
    workstreams/
    research/
  scripts/
  infra/
```

Avoid duplicating domain types in TypeScript and Python by hand. Treat the backend OpenAPI schema or a dedicated JSON Schema package as the contract source, then generate client types.

### 7.4 Core database tables

Plan for these concepts without adding unnecessary columns prematurely:

- `sports`
- `leagues`
- `teams`
- `players`
- `events`
- `markets`
- `bet_slips`
- `bet_legs`
- `source_documents`
- `evidence_items`
- `odds_snapshots`
- `feature_snapshots`
- `prediction_runs`
- `leg_predictions`
- `combo_predictions`
- `model_versions`
- `paper_trades`
- `settlements`
- `bankroll_snapshots`

There is no `users`, `organizations`, or `memberships` table. Do not attach `owner_id` to everything. Use UTC in storage and render the user's timezone in the UI.

Historical analysis records should be append-only. Corrections should create a new version or explicit correction record rather than mutating the evidence behind an earlier prediction.

## 8. Provider Boundaries

Create interfaces around external dependencies so providers can change without rewriting domain logic:

- `PolymarketProvider`
- `OddsProvider`
- `StatsProvider`
- `NewsProvider`
- `WeatherProvider`
- `InjuryProvider`
- `LineupProvider`
- `LLMProvider`

Each provider must implement:

- Explicit timeout
- Bounded retries with jitter
- Rate-limit handling
- Cache policy
- Structured error type
- Response timestamp
- Source identity
- Schema validation
- Test fixture support

Prefer official APIs over scraping. When retrieval is permitted but an API is unavailable, isolate scraping code, respect rate limits and site rules, sanitize content, and make failure non-fatal. Do not browser-automate a source when a stable documented endpoint exists.

Use Polymarket US documentation and APIs, not assumptions from the international crypto product. Never attempt to bypass geographic, account, exchange, or regulatory restrictions.

## 9. Frontend Product and Design Requirements

### 9.1 Design direction

The product should look like a serious research and trading workstation, not a casino. Avoid neon gambling visuals, celebratory confetti, manipulative urgency, giant payout-first cards, and fake certainty.

Use:

- Dense but readable information hierarchy
- Neutral dark or light surfaces with restrained status colors
- Tabular alignment for probabilities, prices, and edges
- Clear timestamps and freshness badges
- Accessible typography and contrast
- Progressive disclosure for detailed evidence
- Responsive layouts that remain usable on a laptop and phone

### 9.2 Core screens

1. **New Analysis**
   - Paste URL or text
   - Add/edit legs
   - Enter stake and quoted payout
   - Validate resolved events before analysis

2. **Analysis Workspace**
   - Overall recommendation
   - Probability-versus-price comparison
   - Leg table
   - Correlation warnings
   - Evidence and source drawer
   - Missing-data warnings
   - Paper-trade action

3. **Analysis History**
   - Search and filter by sport, league, market type, date, and recommendation
   - Compare initial estimate with settlement and closing price

4. **Paper Trading**
   - Open and settled positions
   - Simulated bankroll
   - Exposure by sport and market type
   - Drawdown

5. **Model Performance**
   - Calibration plot
   - Brier score and log loss
   - ROI and closing-line value
   - Sample counts and confidence caveats
   - Breakdown by model version

### 9.3 UI states

Every important component must intentionally support:

- Empty
- Loading
- Partial success
- Stale data
- Conflicting evidence
- Unsupported market
- Provider failure
- Validation error
- Success

Never hide uncertainty behind a spinner or silently drop a failed source.

## 10. Claude Code Skill Requirements

Claude Code must inspect the installed skills before substantial work and use the relevant skill rather than improvising an inferior workflow.

### 10.1 Frontend design skill

For any meaningful frontend page, component system, dashboard layout, or interaction redesign:

1. Invoke the installed frontend-design skill before implementation.
2. Use it to establish visual hierarchy, layout, responsive behavior, interaction states, accessibility, and component reuse.
3. Produce a coherent system rather than unrelated cards.
4. Reuse existing design tokens and components before adding new ones.
5. Do not accept generic AI-dashboard styling as finished work.

If the exact skill name differs, locate the installed skill whose description covers frontend/product/UI design. Do not claim to have used a skill that is not installed.

### 10.2 Playwright skill

Claude Code is expected to have a Playwright-oriented browser/testing skill. Use it creatively for:

- Inspecting the running interface
- Capturing focused screenshots at important breakpoints
- Verifying paste-to-analysis workflows
- Testing loading, stale, failure, and empty states
- Testing keyboard navigation and accessible names
- Checking responsive behavior
- Finding overflow, clipping, hydration, console, and network errors
- Comparing the implemented UI with the intended design

Tests must validate user-visible behavior rather than implementation details. Prefer resilient role, label, and text locators. Do not use arbitrary sleeps. Use web-first assertions and deterministic fixtures. Run Chromium locally by default; add other browsers only when the milestone requires them.

### 10.3 CodeMutter/context-reduction skill

If an installed skill named CodeMutter, Code Mutter, code-map, repository-map, or equivalent exists, invoke it before broad repository exploration and whenever context becomes bloated.

Its purpose is to:

- Build or refresh a compact map of relevant symbols, files, dependencies, and call paths
- Read only the files and ranges required for the current task
- Avoid repeatedly rereading unchanged files
- Exclude generated files, dependency directories, caches, snapshots, build output, and unrelated domains
- Summarize discoveries into concise workstream notes
- Reduce unnecessary model tokens and context churn

If that skill is not installed, use this fallback discipline:

1. Start with `git status`, `git branch --show-current`, and the current workstream note.
2. Use `rg --files` with targeted globs.
3. Use `rg` for symbols and references before opening files.
4. Read narrow ranges around matching symbols.
5. Inspect dependency manifests only when dependencies matter.
6. Do not recursively print the repository.
7. Do not read lockfiles, generated clients, minified assets, coverage output, Playwright traces, or large fixtures unless the task directly requires them.
8. Write concise findings to `docs/workstreams/<stream>.md` so another session can resume without repeating discovery.

Never invent a CodeMutter command. Use the installed skill's documented interface.

## 11. Instructions for Claude Code and Codex

### 11.1 Shared instruction files

`prompt.md` is the canonical long-form brief. Keep repository instruction adapters small:

```markdown
<!-- AGENTS.md -->
# Repository Instructions

Read and follow `prompt.md` before architectural work, shared-contract changes, or material features. For narrow tasks, read the applicable section and `docs/workstreams/<stream>.md`.
```

```markdown
<!-- CLAUDE.md -->
@AGENTS.md

## Claude Code

Use installed frontend-design, Playwright, and CodeMutter/context-reduction skills when applicable. Never claim a skill was used if it was unavailable.
```

Codex must follow `AGENTS.md`. Claude Code must load `CLAUDE.md`, which imports the shared instructions. Do not duplicate this entire prompt into both files because that wastes context and makes the copies drift.

### 11.2 Session behavior

At the beginning of a material task:

1. Confirm the current worktree and branch.
2. Read the relevant workstream note.
3. Inspect the current diff and recent commits.
4. Locate the smallest relevant code surface.
5. Restate the target, constraints, and acceptance checks in no more than ten lines.
6. Implement a small vertical slice.
7. Test it.
8. Commit it.
9. Continue with the next slice.

Do not produce a long speculative plan and then leave the repository unchanged. Do not refactor unrelated code. Do not overwrite another worktree's ownership area. Do not silently alter architectural decisions.

## 12. Git Worktree Strategy

Use separate linked Git worktrees so Claude Code and Codex can work independently without sharing uncommitted files. Git supports multiple working trees attached to one repository; each worktree must use its own branch.

### 12.1 Initial worktrees

Create worktrees only after the base repository, formatting, test commands, and shared contracts exist.

| Worktree | Branch | Primary ownership |
|---|---|---|
| Main/integration | `develop` | Integration, releases, shared verification; no routine feature work |
| Foundation/contracts | `work/foundation` | Root configuration, Docker Compose, database migrations, shared schemas, generated clients |
| Backend | `work/backend` | `apps/api/**`, orchestration, persistence repositories, API endpoints |
| Research/data | `work/research` | `services/research/**`, provider adapters, normalization, caching |
| Prediction | `work/prediction` | `services/prediction/**`, `services/sports/**`, probability, EV, correlation, calibration |
| Frontend | `work/frontend` | `apps/web/**`, component system, pages, client state |
| QA/docs | `work/qa` | `tests/e2e/**`, cross-service integration tests, operational docs |

Example setup:

```bash
git switch develop
git worktree add ../market-foundation -b work/foundation
git worktree add ../market-backend -b work/backend
git worktree add ../market-research -b work/research
git worktree add ../market-prediction -b work/prediction
git worktree add ../market-frontend -b work/frontend
git worktree add ../market-qa -b work/qa
git worktree list
```

Do not force-create a worktree over an existing path or branch. Do not manually delete worktree directories; use `git worktree remove` after verifying that the branch is clean and integrated.

### 12.2 Ownership rules

- One worktree owns a file at a time.
- `work/foundation` owns shared schemas and generated contracts.
- Other worktrees consume contracts; they do not casually edit them.
- Cross-cutting contract changes land in foundation first, then dependent worktrees rebase or merge the updated `develop`.
- Database migrations are serialized through foundation.
- Each stream owns `docs/workstreams/<stream>.md`, preventing status-file conflicts.
- Use uniquely named files under `docs/workstreams/requests/` for cross-stream requests.
- Never run two coding tools in the same worktree simultaneously.
- Never allow two worktrees to generate the same client or migration revision.

### 12.3 Integration order

Integrate in dependency order:

1. Foundation and contracts
2. Backend domain/API changes
3. Research and prediction implementations
4. Frontend integration
5. QA and end-to-end verification

Before integration:

- Working tree is clean.
- Branch is updated with current `develop`.
- Focused tests pass.
- Shared contract tests pass when relevant.
- Workstream note contains changes, commands run, known limitations, and the final commit SHA.

Checkpoint commits may remain on work branches. Squash them into one or a few coherent commits when integrating into `develop`, while preserving the work branch until verification is complete.

## 13. Mandatory Commit Protocol

Frequent commits are required.

### 13.1 Three-to-five-minute checkpoint rule

While actively modifying code, check the clock and repository status every three to five minutes.

- If there is a coherent change, run the narrowest relevant check and commit it immediately.
- If the slice is incomplete but recoverable, make a clearly labeled checkpoint commit on the work branch.
- Do not create empty commits merely to satisfy the timer.
- Do not commit secrets, broken migrations, corrupted generated files, dependency caches, or gigabytes of test artifacts.
- Never merge a knowingly broken checkpoint into `develop`.

Permitted checkpoint examples:

```text
checkpoint(web): scaffold analysis input form
checkpoint(api): add typed bet-slip request schema
checkpoint(research): normalize provider timestamps
checkpoint(model): add independent combo baseline
```

Finished semantic commits should use:

```text
feat(web): add leg-level probability comparison
feat(api): persist immutable analysis snapshots
fix(mlb): refresh prediction after confirmed lineup
test(combo): cover correlated same-game legs
docs(architecture): record provider timeout policy
perf(worker): bound concurrent research requests
```

### 13.2 Before every commit

1. Inspect `git diff --check`.
2. Review the staged diff; do not use blind `git add .` when unrelated changes exist.
3. Run the smallest relevant formatter, type check, unit test, or smoke test.
4. Confirm no `.env`, credentials, tokens, database dumps, browser profiles, or private screenshots are staged.
5. Write a specific commit message describing the actual change.

### 13.3 At milestone boundaries

Run the broader checks, update the workstream note, and create a clean semantic commit. Record:

- What changed
- Why it changed
- Tests run and results
- Remaining limitations
- Migration or environment changes
- Screenshots or Playwright traces only when they add diagnostic value
- Commit SHA

Never rewrite or delete another tool's commits without explicit direction. Never use destructive Git commands to resolve ordinary conflicts.

## 14. RAM and Resource Budget

The platform should be capable without keeping an unnecessary fleet of processes alive.

### 14.1 Development targets

- Target idle application memory below approximately 1.5 GB, excluding the developer's editor and AI coding tools.
- Target ordinary local test peaks below approximately 2.5 GB, excluding a deliberately launched full browser matrix.
- Run one shared PostgreSQL instance for all worktrees.
- Run one shared Redis instance only if the current milestone requires it.
- Do not start a complete duplicate Docker stack for every worktree.
- Assign different web/API ports only to worktrees being exercised concurrently.
- Stop unused Vite servers, Python reloaders, workers, and browser processes.

### 14.2 Backend constraints

- Default to one API process and one worker process locally.
- Bound concurrent external requests with semaphores.
- Stream large responses where possible.
- Limit response sizes and article extraction sizes.
- Use pagination for history, evidence, odds snapshots, and model runs.
- Avoid loading an entire season or odds history into memory.
- Close HTTP clients, browser contexts, and database sessions deterministically.
- Cache normalized provider responses with explicit TTLs.
- Store compact derived features rather than repeatedly materializing giant raw payloads.
- Do not preload every sport model at startup if lazy loading is safe.

### 14.3 Frontend constraints

- Use route-level code splitting for heavy analytics screens.
- Avoid storing duplicate API payloads in global state.
- Virtualize only genuinely large tables.
- Do not bundle raw historical datasets into the frontend.
- Compress and appropriately size images.
- Use production source maps only when intentionally configured.

### 14.4 Test constraints

- Playwright defaults to Chromium and one worker locally.
- Retain screenshots, video, and traces only on failure unless a design review requires them.
- Reuse authenticated or initialized state if authentication is later added; do not add authentication now.
- Keep fixtures representative and small.
- Run the full browser matrix in CI or at release milestones, not every three-minute checkpoint.

## 15. Security Baseline for a Single-User Tool

Single-user does not mean publicly unsecured.

- If running only on localhost, no product user system is required.
- If reachable remotely, protect the entire application with a private network, reverse-proxy password, or one fixed access mechanism. Do not build a full account platform.
- PostgreSQL must remain on a private network or localhost and must never be exposed directly to the public internet.
- Use a non-superuser application database role.
- Use strong database authentication and explicit host rules.
- Keep API keys in environment variables or a server secret store.
- Commit only `.env.example` with fake values.
- Redact secrets, tokens, authorization headers, and sensitive payloads from logs.
- Apply strict URL validation and SSRF protection to user-submitted links.
- Use an allowlist for automatically fetched domains where practical.
- Sanitize fetched HTML and never execute remote scripts.
- Apply request timeouts, content-length limits, and rate limits.
- Back up PostgreSQL using automated `pg_dump` snapshots and periodically test restoration.

## 16. Testing Strategy

### 16.1 Unit tests

Unit-test every deterministic calculation, including:

- American, decimal, and market-price conversions
- Break-even probability
- Vig removal
- Expected profit and return
- Combo multiplication baseline
- Correlation adjustments or simulations
- Bounds and invalid inputs
- Postponed, voided, and unresolved leg behavior
- Settlement transformations
- Timezone handling

### 16.2 Contract tests

- Validate provider responses against schemas.
- Use recorded, redacted fixtures.
- Detect breaking changes in Polymarket and sports-data responses.
- Ensure TypeScript clients match the API schema.
- Make timestamps, units, and nullable fields explicit.

### 16.3 Integration tests

Test the complete internal path with deterministic provider fixtures:

```text
raw bet input
-> normalized slip
-> evidence snapshot
-> features
-> leg predictions
-> combo estimate
-> persisted analysis
-> API response
```

### 16.4 Playwright tests

At minimum cover:

- Paste a single market and review the resolved market
- Paste a combo and inspect every leg
- Correct an ambiguous participant
- See a provider failure without losing successful evidence
- See stale-data and unsupported-market warnings
- Save a paper trade
- Review a settled paper trade
- Filter analysis history
- Inspect model-performance metrics

Use accessible locators and user-visible assertions. Avoid selectors tied to CSS implementation.

### 16.5 Evaluation tests

Maintain a versioned evaluation set containing representative historical examples for every supported sport and market family. Evaluate parsing accuracy, event resolution, evidence relevance, probability calibration, abstention behavior, and explanation faithfulness.

## 17. Observability and Reproducibility

- Assign every analysis a trace ID.
- Use structured logs.
- Record provider latency, cache hit/miss, retry count, and failure category.
- Record prompt/template version for any LLM call.
- Record token usage and estimated model cost.
- Store code/model version with every prediction.
- Surface partial failures rather than collapsing the entire analysis.
- Never log secrets or full private browser state.
- Keep metrics lightweight; do not add a heavyweight observability stack for the MVP.

## 18. Future-Proofing Without Premature Complexity

Design seams now, defer infrastructure until measured need.

### 18.1 Build now

- Typed provider interfaces
- Sport adapter interface
- Immutable evidence and prediction snapshots
- Model registry and version identifiers
- Feature flags
- Background-job interface
- Generated API contracts
- Append-only evaluation history
- Explicit source and timestamp metadata

### 18.2 Defer until justified

- Automated trade execution
- Multi-user accounts and RLS
- Public subscriptions
- Kubernetes
- Distributed event streaming
- Vector databases
- Separate deployment per internal module
- Real-time in-game wagering

The future version can separate modules into services because boundaries already exist. Do not pay the operational cost before throughput, latency, fault isolation, or team ownership requires it.

## 19. Phased Delivery Plan

### Phase 0: Repository and contracts

- Initialize monorepo, formatting, linting, tests, Docker Compose, PostgreSQL, migrations, environment schema, and CI.
- Create thin `AGENTS.md` and `CLAUDE.md` adapters.
- Establish worktrees and ownership notes.
- Define core enums and schemas.

Exit criterion: one command starts the minimal web/API/database stack and all baseline checks pass.

### Phase 1: Market intake

- Accept manual and pasted input.
- Integrate read-only Polymarket US market/event data.
- Normalize singles and combos.
- Validate settlement details and event state.
- Persist draft and normalized slips.

Exit criterion: a real pregame single or combo becomes a correct, editable structured slip.

### Phase 2: Research pipeline

- Implement provider interfaces and bounded retrieval.
- Add odds, statistics, injuries, weather, news, lineup, and schedule sources incrementally.
- Deduplicate and rank evidence.
- Persist source and evidence snapshots.
- Produce concise source-backed summaries.

Exit criterion: each supported leg has a reproducible, timestamped evidence package with visible missing-data warnings.

### Phase 3: Prediction foundation

- Implement probability and EV primitives.
- Add baseline de-vigged consensus estimates.
- Add model registry, feature snapshots, and confidence logic.
- Implement combo independence baseline and correlation framework.
- Begin with NFL and MLB.

Exit criterion: deterministic tests pass and the system can explain every number in an NFL or MLB result.

### Phase 4: Decision interface

- Build the full analysis workspace.
- Add evidence drawers, correlation warnings, leg comparison, and paper-trade capture.
- Use frontend-design and Playwright skills.
- Cover all loading and failure states.

Exit criterion: the user can move from pasted combo to understandable decision without inspecting logs or database rows.

### Phase 5: Paper trading and calibration

- Resolve outcomes.
- Track simulated bankroll and closing line.
- Add calibration, Brier score, log loss, ROI, and drawdown views.
- Run the scheduled weekly performance review.
- Create regression evaluations from failures.

Exit criterion: performance can be evaluated by model version and market type without spreadsheet cleanup.

### Phase 6: Sport expansion

- Add college football with conservative coverage boundaries.
- Add selected soccer competitions.
- Expand player props only where the data and validation set support them.
- Add explicit `EXPERIMENTAL` coverage badges.

Exit criterion: each new sport passes its own contract, backtest, calibration, and UI-state acceptance criteria.

### Phase 7: Limited execution consideration

Only consider this phase after paper results show stable calibration and useful closing-line performance over a meaningful sample.

- Separate execution from analysis.
- Require preview and explicit confirmation.
- Add stake and loss caps.
- Add idempotency and reconciliation.
- Add kill switch and audit log.
- Review Polymarket US API, account, and regulatory requirements at implementation time.

## 20. Definition of Done for Every Feature

A feature is not complete until:

- Acceptance behavior is implemented.
- Types and schemas are updated.
- Failure and empty states are handled.
- Relevant unit and integration tests pass.
- User-visible frontend changes receive Playwright inspection.
- Accessibility is checked for the changed interaction.
- Provider calls have timeout, error, and cache behavior.
- Logs do not expose secrets.
- RAM/process impact is reasonable.
- Documentation or workstream notes are updated.
- Changes are committed with a specific message.
- The worktree is clean or intentionally contains documented follow-up work.

## 21. Required Workstream Notes

Each worktree owns one file under `docs/workstreams/` with:

```markdown
# Workstream: <name>

## Objective
## Owned paths
## Current base commit
## Decisions made
## Contracts consumed or produced
## Commands and tests
## Known issues
## Integration order
## Last completed commit
## Next smallest task
```

Update it before handing work to another coding tool or ending a substantial session. Keep it concise and operational; do not paste full logs.

## 22. First Implementation Instructions

When beginning from an empty or partial repository:

1. Inspect the repository and do not overwrite existing user work.
2. Create or verify `develop` and the foundation worktree.
3. Add the thin instruction adapters.
4. Scaffold the repository layout without adding unused frameworks.
5. Configure `pnpm`, `uv`, formatting, linting, and baseline tests.
6. Add Docker Compose with one private PostgreSQL service.
7. Add `.env.example` and secret-safe configuration validation.
8. Implement health endpoints and a minimal frontend health view.
9. Establish core schemas for events, markets, slips, legs, evidence, and predictions.
10. Generate the frontend API types.
11. Add one end-to-end smoke test.
12. Commit every coherent checkpoint at the required three-to-five-minute cadence.
13. Stop after the foundation milestone, report the commit SHAs and checks, and wait for the next scoped implementation request.

## 23. Prohibited Shortcuts

Do not:

- Promise profit or guaranteed wins.
- Treat market price as ground truth without analysis.
- Let an LLM fabricate statistics or sources.
- Use an LLM as a calculator.
- Hide stale or failed data.
- Multiply correlated parlay legs as if independent.
- Scrape when a documented API is available.
- Read or dump the entire repository into model context.
- Add dependencies without checking whether the standard library or current stack suffices.
- Run duplicate database stacks in every worktree.
- Add Supabase or a multi-user permission system.
- Add automated wagering during the MVP.
- Modify unrelated user code.
- Combine unrelated refactors with feature work.
- Leave large uncommitted changes for long periods.
- Claim a test or skill was used when it was not.

## 24. Authoritative Reference Links

- Polymarket US documentation: https://docs.polymarket.us/
- Polymarket US combo rules: https://docs.polymarket.us/faqs/combos-faqs
- Git worktree documentation: https://git-scm.com/docs/git-worktree
- PostgreSQL client authentication: https://www.postgresql.org/docs/current/auth-pg-hba-conf.html
- PostgreSQL backup and restore: https://www.postgresql.org/docs/current/backup-dump.html
- Playwright best practices: https://playwright.dev/docs/best-practices
- Claude Code project memory and instruction files: https://code.claude.com/docs/en/memory
- Codex `AGENTS.md` instructions: https://learn.chatgpt.com/docs/agent-configuration/agents-md

## 25. Final Directive

Build the smallest reliable vertical slice at a time while preserving the full architecture. Use evidence, typed contracts, deterministic math, sport-specific models, measured calibration, disciplined worktrees, frequent recoverable commits, and visible uncertainty. The goal is not to produce confident-sounding picks. The goal is to create a system whose recommendations become demonstrably more trustworthy as its paper-trading evidence grows.
