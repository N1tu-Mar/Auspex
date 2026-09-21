# Workstream: research

## Objective

Research foundation: typed provider boundaries, bounded read-only retrieval, deterministic
fixtures, a Polymarket US read-only adapter with normalization, and immutable evidence snapshots.
No API endpoints, prediction formulas, scraping, browser automation, or live-provider tests.

## Owned paths

`services/research/**`, this note, `docs/workstreams/requests/research-*.md`.

## Current base commit

`267557e` (`main`, merged into `work/research`). Branch `work/research`, worktree `../auspex-research`.

## Decisions made

- **Package** `services/research/auspex_research` (provider-neutral; backend calls `PolymarketUSClient`
  and `build_snapshot`; nothing here imports API or DB code):
  - `errors.py` — `ProviderError` + `ProviderErrorKind` (`TIMEOUT`, `RATE_LIMITED`, `UNAVAILABLE`,
    `NOT_FOUND`, `AUTH`, `BAD_REQUEST`, `SCHEMA`, `STALE`). Messages carry no URLs/headers/secrets.
  - `transport.py` — `Transport` Protocol (GET only), `RetryPolicy` (bounded: 1-5 attempts, 30 s cap),
    and `Fetcher`: per-attempt `asyncio.timeout`, full-jitter exponential backoff, `Retry-After`
    (seconds or HTTP-date, on 429 and 503; fails fast above 30 s), 2 MB body cap, redirects are errors,
    optional `asyncio.Semaphore` for bounded concurrency, optional TTL cache, and a `RequestEvent`
    sink (provider, redacted URL, attempt, outcome, status, kind, elapsed_ms, retry delay). URLs are
    built with sorted params (`build_url`) so a request has one stable cache key; `redact_url`
    strips userinfo/fragments and masks credential-looking query values in logs and provenance.
  - `httpx_transport.py` — live `HttpxTransport` (httpx, `follow_redirects=False`, connect/read/write/pool
    timeouts, streamed body cut at the cap, httpx errors mapped to `TimeoutError`/`OSError` carrying only
    the exception type). Tested with `httpx.MockTransport`; no test uses a network.
  - `settings.py` — `load_settings(environ)` reads `AUSPEX_RESEARCH_*` (`POLYMARKET_US_BASE_URL` https-only, no
    credentials/query; `CONNECT_TIMEOUT_S`, `READ_TIMEOUT_S`, `MAX_ATTEMPTS`, `MAX_CONCURRENCY`,
    `CACHE_MAX_ENTRIES`). Unknown `AUSPEX_RESEARCH_*` names and bad values fail with variable names only.
    No secret is needed for the public endpoints, so none is read; a keyed provider must add `SecretStr`.
  - `cache.py` — `TTLCache`: explicit TTL per `set`, key = provider + full URL, bounded, expired entries
    evicted on read. **Caches decoded raw JSON, not normalized output** (normalization is pure and cheap;
    this avoids serving old-shape data after a normalizer change). Only successes are cached; a hit keeps the
    original `retrieved_at` and reports `from_cache=True, attempts=0`; a failed refresh raises, never falls
    back to expired data. TTLs: market 15 s, catalog 300 s, settlement 60 s.
  - `catalog.py` — provider-neutral `CatalogEvent`/`CatalogTeam`/`CatalogMarketRef`, `CatalogPage` (names rows
    skipped as malformed), `EventQuery`, `resolve_event`. Matching is exact after `normalize_name`
    (casefold, accent/punctuation strip) against team name/abbreviation/alias/safeName; no fuzzy or substring
    matching. Result is `MATCHED` (exactly one), `AMBIGUOUS` (2+, sorted by start then id), or `NO_MATCH`.
    With a query start time, events lacking a start are excluded and the count is reported.
  - `polymarket.py` — read-only `PolymarketUSClient(Fetcher)` over documented public GETs only:
    `/v1/market/slug/{slug}`, `/v1/market/id/{id}`, `/v1/markets/{slug}/settlement`,
    `/v1/events/slug/{slug}`, `/v1/events` (window on `startTimeMin/Max`, `active=true&closed=false`, page <= 100).
    Slugs/ids/page bounds validated before any request. Settlement returns the upstream number as-is; a 404 is
    reported as "not found or not settled (upstream does not say)". Rules are exposed only as verbatim
    `description`/`rulesDisclaimer` (markets) and `description`/`resolutionSource` (events), never parsed.
    Market type reads V2 enum first, older `sportsMarketType` only if V2 is absent; only
    MONEYLINE/SPREAD/TOTAL map to contract `MarketType`. Event `startTime` is the only start used
    (`startDate`/`eventDate` are never substituted). League/sport come from market tags only when unanimous.
  - `evidence.py` / `providers.py` — snapshot assembly: `build_snapshot(..., max_age={category: timedelta})`
    requires an explicit window for every category present (no silent default). Older evidence (by
    `published_at`, else `retrieved_at`) is dropped and recorded as a `STALE` `ProviderFailure`; provider
    failures are kept; each successful call is a `SourceRun` (provider, redacted URL, retrieved_at, from_cache,
    attempts, item_count) even if it returned nothing; duplicates (same category + claim kind + normalized
    fact) collapse to the earliest report and inferences citing a collapsed item are re-pointed to the survivor.
    Snapshots stay frozen and content-hashed.
- Contracts: consumes `auspex_contracts` `MarketType`/`Side`/`Sport` read-only; no shared-contract, endpoint,
  migration, or frontend changes. `conftest.py` sys.path shim removed (foundation registered the package).

## Contracts consumed or produced

- Consumed: `auspex_contracts.MarketType`, `Side`, `Sport`.
- Produced (Python, internal until backend adopts): `NormalizedMarket` (+ verbatim `description`,
  `rules_disclaimer`), `MarketSettlement`, `CatalogEvent`, `CatalogPage`, `EventResolution`,
  `EvidenceSnapshot` (+ `runs`), `ProviderFailure`, `Fetcher`, `HttpxTransport`, `ResearchSettings`.
  Breaking vs. the previous note: `PolymarketUSClient` now takes a `Fetcher`; `ResponseCache.set` takes a TTL;
  `build_snapshot` requires `max_age`.

## Commands and tests

Run 2026-09-21 in the worktree root:

- `uv run pytest services/research -q` -> 124 passed (deterministic fixtures / `MockTransport` only)
- `uv run mypy` -> strict, no issues (51 files); `uv run ruff check` / `ruff format --check` -> pass
- `pnpm exec biome check services/research` -> pass; `pnpm check` -> pass (300 pytest, contracts up to date)
- `git diff --check` -> clean
- Covered: timeout, retry + jitter bounds, 429 + `Retry-After` (seconds/date/past/junk/excessive), 503 `Retry-After`,
  redirects, 401/403/4xx kinds, oversize/non-JSON/malformed bodies (market, settlement, catalog envelope, bad row),
  cache hit/expiry-boundary/eviction/no-stale-on-failed-refresh/no-error-caching, redaction, concurrency bound,
  env validation, ambiguous/no-match catalog resolution, stale/duplicate/partial-failure snapshots.

## Known issues

- Fixtures are **synthetic**, shaped from docs.polymarket.us (read 2026-09-21); none is a recorded response. No
  live call has been made. Event/list field names come from the docs page; real payloads may differ (e.g. whether
  `teams[].alias` carries nicknames), which changes how often pasted names resolve, not correctness.
- `marketSides[].price` vs `quote.value` payout semantics remain unconfirmed; prediction must not assume them.
  Settlement `settlement` is an unexplained number here (no scale/side semantics inferred).
- Catalog resolution needs parsed participants; extracting them from pasted text/URLs is the backend intake's job.
  Sports-API endpoints (leagues, teams, per-league events) are not used; list filtering is by start window and `tagSlug`.
- Rate limiting is a concurrency bound plus reactive 429 handling; no token bucket against the documented 20 req/s.
- No cache single-flight: concurrent identical misses each fetch. Cache is in-process only.
- Odds, stats, news, weather, injury, and lineup providers are still Protocols only.

## Integration order

After foundation and backend. No migrations. Backend builds one `Fetcher` (shared `TTLCache` and
`Semaphore`) inside an `HttpxTransport.from_settings(...)` context and injects `PolymarketUSClient`.

## Last completed commit

See `git log work/research` (feature commit precedes the docs commit).

## Next smallest task

Record one redacted, approved read-only Polymarket US capture per endpoint and add it beside the synthetic
fixtures; confirm event/team field shapes and settlement semantics against it and the settlement docs.
