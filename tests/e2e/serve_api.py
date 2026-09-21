"""API for the browser suite: the real app with an empty, offline event catalog.

Provider-backed paste calls the live Polymarket gateway, which is nondeterministic and needs
network. Pinning the catalog to [] restores the documented EVENT_NOT_FOUND behavior without
touching application code. Run: uv run python tests/e2e/serve_api.py
"""

import uvicorn

from app.intake import CatalogEvent, get_event_catalog
from app.main import app


async def _empty_catalog() -> list[CatalogEvent]:
    return []


app.dependency_overrides[get_event_catalog] = lambda: _empty_catalog

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
