# Request: register services/research in root tooling

- From: research (`work/research`)
- To: foundation
- Status: done (2026-09-21) — foundation registered `services/research`, root tooling, and `httpx`; research removed the `conftest.py` shim.

## Why

`services/research` cannot edit root tooling, so it is not yet part of `pnpm check`. It runs today
only through explicit paths (see `docs/workstreams/research.md`), plus a `sys.path` shim in
`services/research/conftest.py`.

## Requested changes

1. Add `services/research/pyproject.toml` as a uv workspace member (package `auspex_research`,
   dependencies: `auspex-contracts`, `pydantic>=2.9`), and add it to the root dev group.
2. Root `pyproject.toml`:
   - `[tool.pytest.ini_options] testpaths` += `services/research/tests`
   - `[tool.mypy] files` += `services/research`; `mypy_path` += `services/research`
   - `[tool.ruff.lint.isort] known-first-party` += `auspex_research` (ruff will then re-sort
     imports in `services/research/tests`; run `pnpm fmt`).
3. Add a production HTTP client dependency for research (`httpx`, per prompt.md §7.1). The root
   dev group currently has `httpx2`, which is dev-only and not the prescribed library. Research
   will add a small `Transport` implementation over it once available; until then the adapter is
   fixture-only by design.

After this lands, research removes the `conftest.py` shim.
