# Request: collect QA pytest suites in root tooling

- From: QA (`work/qa`)
- To: foundation (root `pyproject.toml`)
- Blocking: no. The suites run when you name them explicitly.

## Ask

Add `tests/integration` and `tests/contract` to `[tool.pytest.ini_options].testpaths` so that
`pnpm test` and CI run them. Both need no database and finish in under a second:

- `tests/contract/test_e2e_fixtures_contract.py`: e2e JSON fixtures validate against the API's
  `IntakeResult` and `CatalogEvent` models.
- `tests/integration/test_e2e_fixture_parity.py`: each routed paste fixture must equal the real
  intake response for the fixture catalog.

Until then, run `uv run pytest tests/integration tests/contract`.
