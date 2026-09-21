"""Deterministic fixture support: a Transport that serves recorded or synthetic responses."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from auspex_research.transport import RawResponse

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def json_fixture(relative_path: str, status_code: int = 200) -> RawResponse:
    return RawResponse(status_code, (FIXTURE_DIR / relative_path).read_bytes())


class FixtureTransport:
    """Serves each URL's responses in order, repeating the last one. Unknown URLs get 404."""

    def __init__(self, routes: Mapping[str, RawResponse | Sequence[RawResponse]]) -> None:
        self._routes = {
            url: [r] if isinstance(r, RawResponse) else list(r) for url, r in routes.items()
        }
        self.calls: list[str] = []

    async def __call__(self, url: str) -> RawResponse:
        self.calls.append(url)
        queue = self._routes.get(url)
        if not queue:
            return RawResponse(404, b'{"message": "no fixture"}')
        return queue.pop(0) if len(queue) > 1 else queue[0]
