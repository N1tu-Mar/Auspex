import sys
from pathlib import Path

# ponytail: services/research is not a uv workspace member yet (root tooling is foundation-owned);
# drop this once foundation adds it (docs/workstreams/requests/research-tooling-registration.md).
sys.path.insert(0, str(Path(__file__).parent))
