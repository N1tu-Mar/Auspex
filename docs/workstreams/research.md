# Workstream: research

## Objective

Research foundation: typed provider boundaries, bounded read-only retrieval, deterministic
fixtures, a Polymarket US read-only adapter with normalization, and immutable evidence snapshots.
No API endpoints, prediction formulas, scraping, browser automation, or live-provider tests.

## Owned paths

`services/research/**`, this note, `docs/workstreams/requests/research-*.md`.

## Current base commit

`55611ba` (`main`). Branch `work/research`, worktree `../auspex-research`.

## Decisions made

- **Package** `services/research/auspex_research`:
  - `errors.py` — `ProviderError` with `ProviderErrorKind` (`TIMEOUT`, `RATE_LIMITED`,
    `UNAVAILABLE`, `NOT_FOUND`, `BAD_REQUEST`, `SCHEMA`), `retryable`, `attempts`,
    `retry_after_s`, `status_code`. Messages carry no URLs, headers, or secrets.
  - `transport.py` — `Transport` Protocol (GET only; read-only by construction), `RetryPolicy`
    (5 s per-attempt `asyncio.timeout`, max 3 attempts, full-jitter exponential backoff capped at
    4 s; bounds enforced), 429 handling that honours numeric `Retry-After` and fails fast above
    30 s, 2 MB body cap, JSON decode. Clock, sleep, and jitter are injectable.
  - `providers.py` — `SourceIdentity`, `CachePolicy` + `ResponseCache` Protocol,
    `ProviderResponse[T]` (source, URL, UTC retrieval time, attempts, cache flag),
    `validate_payload`, `EventRef`, `OddsObservation` (`decimal_price`, never bare `odds`),
    `NormalizedMarket`/`MarketSideQuote`, and Protocols `PolymarketProvider`, `OddsProvider`,
    `StatsProvider`, `NewsProvider`, `WeatherProvider`, `InjuryProvider`, `LineupProvider`
    (the last five share `EvidenceProvider`, distinguished by a `Literal` category that mypy
    enforces). `build_snapshot` merges results, collapses identical reports, and records
    failures instead of dropping them.
  - `evidence.py` — frozen, `extra="forbid"` `SourceSnapshot` (URL, publisher, optional
    publication time, retrieval time, optional content hash), `EvidenceItem`, `ProviderFailure`,
    `EvidenceSnapshot`. `ClaimKind` = `CONFIRMED_FACT | PROJECTION | RUMOR | OPINION |
    INFERENCE`; an `INFERENCE` must cite `derived_from` evidence in the same snapshot and no other
    kind may. Excerpts ≤ 300 chars, facts ≤ 500. All times UTC-normalized and must be aware.
    `evidence_id`/`snapshot_id` are SHA-256 of content: re-validating stored JSON detects edits.
  - `polymarket.py` — `PolymarketUSClient` over `GET https://gateway.polymarket.us/v1/market/slug/{slug}`
    (public, unauthenticated, 20 req/s per docs). Slug allowlist regex blocks path injection
    before any request. `normalize_market` is pure: MONEYLINE/SPREAD/TOTAL map to contract
    `MarketType`; PROP/FUTURE/DRAWABLE_OUTCOME stay `None` with a warning; naive
    `gameStartTime`, out-of-range prices, and non-USD quotes become `None` with a warning,
    never guessed. Upstream extra fields are ignored; changes to used fields raise `SCHEMA`.
  - `fixtures.py` — `FixtureTransport` (ordered per-URL responses, 404 for unknown, records
    calls) and `json_fixture`.
- **No HTTP library dependency yet.** Root dev deps contain `httpx2`, not the prescribed
  `httpx`, and research may not edit root tooling. A live `Transport` is deferred (request filed).
- Uses `auspex_contracts` enums (`Sport`, `MarketType`, `Side`) read-only.

## Contracts consumed or produced

- Consumed: `auspex_contracts.MarketType`, `Side`, `Sport`.
- Produced (Python, internal to research until backend adopts them): `NormalizedMarket`,
  `EvidenceItem`, `EvidenceSnapshot`, `ProviderFailure`, `OddsObservation`, provider Protocols.
- No shared-contract, generated-type, or migration changes.

## Commands and tests

Run on 2026-09-21 from the worktree root (research is not yet in root tooling, so paths are
explicit):

- `uv run pytest services/research -q` → 45 passed
- `MYPYPATH=services/research uv run mypy services/research` → strict, no issues (11 files)
- `uv run ruff check services/research && uv run ruff format --check services/research` → pass
- `pnpm exec biome check services/research` → pass (fixture JSON)
- `pnpm check` → pass (unchanged baseline: Biome, Ruff, tsc, mypy, 14 pytest, contract drift)
- Negative check: a `WeatherProvider`-category class assigned to `NewsProvider` fails mypy.
- `git diff --check` → clean

## Known issues

- Not wired into `pnpm check`/CI until foundation lands
  `requests/research-tooling-registration.md`; `services/research/conftest.py` holds a
  `sys.path` shim until then. Ruff sorts `auspex_research` as third-party for the same reason.
- No live transport: the adapter runs only on fixtures. No live call has been made.
- Polymarket fixtures are **synthetic**, shaped from the documented schema, not recorded.
  Payout/price semantics of `marketSides[].price` vs `quote.value` are unconfirmed against
  settlement docs; prediction must not assume payout semantics from these fields yet.
- Only get-market-by-slug is implemented (no by-id, events, BBO, book, or settlement endpoints).
- Cache is interface-only (`CachePolicy`, `ResponseCache`); no store implementation.
- Rate limiting is reactive (429 + `Retry-After`); no client-side token bucket.
- Odds, stats, news, weather, injury, and lineup providers are Protocols only; no vendor chosen.
  HTML sanitization and dedupe beyond identical content belong to the future news adapter.

## Integration order

After foundation and backend. No migrations. Merge `work/research` into `main` once foundation's
tooling request is handled (or as-is; nothing outside `services/research` depends on it yet).

## Last completed commit

`8b778bf` (implementation). This note and the request are committed in the following docs commit
on `work/research`.

## Next smallest task

Once httpx is available: a ~20-line `httpx` `Transport` plus a recorded, redacted Polymarket US
fixture; then get-market-by-id and settlement-rule retrieval for leg normalization.
