#!/usr/bin/env bash
# Regenerate cross-language contracts from the single source of truth:
#   auspex_contracts (Pydantic) -> FastAPI OpenAPI JSON -> TypeScript types.
# --check regenerates into a temp dir and fails if committed output drifted.
set -euo pipefail
cd "$(dirname "$0")/.."

dest=packages/contracts
if [[ "${1:-}" == "--check" ]]; then
  dest=$(mktemp -d)
  trap 'rm -rf "$dest"' EXIT
fi
mkdir -p "$dest/openapi" "$dest/generated"

uv run --quiet python -m app.openapi > "$dest/openapi/openapi.json"
pnpm exec openapi-typescript "$dest/openapi/openapi.json" -o "$dest/generated/api.d.ts"

if [[ "${1:-}" == "--check" ]]; then
  for f in openapi/openapi.json generated/api.d.ts; do
    diff -u "packages/contracts/$f" "$dest/$f" \
      || { echo "Contract drift in $f. Run: pnpm contracts" >&2; exit 1; }
  done
  echo "Contracts up to date."
fi
