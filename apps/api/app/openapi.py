"""Print the OpenAPI document: `python -m app.openapi > packages/contracts/openapi/openapi.json`."""

import json

from app.main import app


def render() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


if __name__ == "__main__":
    print(render(), end="")
