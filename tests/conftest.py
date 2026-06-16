import sys
from pathlib import Path

# Repo root: tests/conftest.py -> parents[1]. Put it on sys.path so `agentsec_sdk`
# imports without an editable install. The SDK has no runtime dependencies, so
# there is nothing else to resolve.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
