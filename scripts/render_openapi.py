"""Print the OpenAPI document with the analysis contracts that no route references yet.

FastAPI only emits schemas reachable from routes. Foundation contracts (analysis runs, evidence,
snapshots) must reach TypeScript before backend exposes endpoints, so they are merged in here.
Once a route returns one, FastAPI emits it and the identical schema is simply kept.
"""

import json

from pydantic.json_schema import models_json_schema

from app.main import app
from auspex_contracts import (
    AnalysisRef,
    AnalysisRun,
    Event,
    EventSnapshot,
    EvidenceSnapshot,
    FeatureSnapshot,
    Market,
    MarketSnapshot,
)

ROOTS = (
    AnalysisRef,
    AnalysisRun,
    Event,
    EventSnapshot,
    EvidenceSnapshot,
    FeatureSnapshot,
    Market,
    MarketSnapshot,
)


def render() -> str:
    doc = app.openapi()
    schemas = doc.setdefault("components", {}).setdefault("schemas", {})
    _, extra = models_json_schema(
        [(m, "validation") for m in ROOTS], ref_template="#/components/schemas/{model}"
    )
    for name, schema in extra["$defs"].items():
        # FastAPI's copy wins: same class, differs only by `default: null` and key order.
        schemas.setdefault(name, schema)
    return json.dumps(doc, indent=2) + "\n"


if __name__ == "__main__":
    print(render(), end="")
