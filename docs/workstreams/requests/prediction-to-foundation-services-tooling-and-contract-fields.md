# Request: prediction → foundation

**From:** prediction (`work/prediction`)
**To:** foundation (owns root tooling and `packages/contracts/**`)
**Blocking:** no. Prediction tests and type checks run through explicit paths until this lands.

## 1. Wire services into root tooling

`services/prediction` (`auspex-prediction`) and `services/sports` (`auspex-sports`) have their own `pyproject.toml`, but root tooling does not include them yet:

- `pyproject.toml` `[tool.uv.workspace].members`: add `services/prediction` and `services/sports`. Add both to the `dev` group and `[tool.uv.sources]` as `{ workspace = true }`, then refresh `uv.lock`.
- `[tool.mypy]`: add both service directories to `files`, and `services/prediction:services/sports` to `mypy_path`.
- `[tool.pytest.ini_options].testpaths`: add `services/prediction/tests` and `services/sports/tests`.
- `[tool.ruff.lint.isort].known-first-party`: add `auspex_prediction` and `auspex_sports`. Then run `pnpm fmt`, because import grouping in `services/**` will change. Prediction can make that commit instead if you'd rather.

Until this lands, run the checks this way:

```bash
PYTHONPATH=services/prediction:services/sports uv run pytest services/prediction/tests services/sports/tests
MYPYPATH=services/prediction:services/sports:packages/contracts uv run mypy services/prediction services/sports
```

## 2. Contract fields (future; needed before the first real model)

- `BetLeg` has no **period/scope** field (full game vs first half vs MLB first five innings). The MLB and NFL adapters currently require `settlement_rule_ref` to confirm full-game scope.
- `BetLeg` has no **player-prop stat type** (passing yards, strikeouts). Player props stay outside coverage until it does.
- There are no **venue/roof** fields. Weather correlation is only flagged for legs in the same game.
- Result and API shapes for `InsufficientData`, `CorrelationWarning`, `ComboAssessment`, and `LegEstimate` currently live as internal dataclasses in `services/**`. Promote them to Pydantic contracts once backend needs to serialize them.
