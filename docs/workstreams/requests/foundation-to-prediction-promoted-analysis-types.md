# Request: prediction and sports to use promoted analysis contracts

- From: foundation (`work/foundation`)
- To: prediction (`services/prediction/**`), sports (`services/sports/**`)
- Blocking: no.

## Change

`auspex_contracts` now defines Pydantic versions of the internal dataclasses:

| was | now | difference |
|---|---|---|
| `core.InsufficientData` | `InsufficientData` | frozen model; `reasons` is a tuple with min length 1 |
| `correlation.CorrelationWarning`, `DependencyKind` | same names | `magnitude` is `Literal["UNQUANTIFIED"]`; `leg_indices` must be non-empty |
| `combo.NaiveIndependentBaseline`, `ComboAssessment` | same names | none |
| `ev.PositionCosts`, `ev.ExpectedValue` | same names | `ExpectedValue` now embeds `costs` |
| `sports.LegEstimate` | `LegEstimate` | flat `probability_low`/`probability_high` became `interval: UncertaintyInterval` |

Range and ordering checks moved into the models. Your `require_*` guards still cover raw inputs.

## Ask

Replace the dataclasses with imports and adapt call sites. Keep `pregame_blockers` and the math where they are. Period/scope, player-prop stat type, and venue/roof fields (§2 of the earlier request) remain deferred.
