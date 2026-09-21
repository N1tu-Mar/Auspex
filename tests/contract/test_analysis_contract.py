"""Analysis API surface the web app and e2e fixtures depend on. No database needed."""

from app.main import app


def test_openapi_exposes_analysis_and_intake_retrieval_routes() -> None:
    paths = app.openapi()["paths"]
    assert {"post"} <= paths["/api/v1/analyses"].keys()
    assert {"get"} <= paths["/api/v1/analyses/{analysis_id}"].keys()
    assert {"get"} <= paths["/api/v1/bet-slips/intake/{trace_id}"].keys()


def test_analysis_record_declares_every_provenance_collection() -> None:
    schemas = app.openapi()["components"]["schemas"]
    props = schemas["AnalysisRecord"]["properties"]
    assert {
        "analysis",
        "market_snapshots",
        "evidence_snapshots",
        "feature_snapshots",
        "provider_failures",
    } <= props.keys()
