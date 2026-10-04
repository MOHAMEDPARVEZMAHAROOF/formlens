"""Pytest path setup for FormLens: project root importable, isolated data dir."""
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Isolate the SQLite data dir before formlens.app is imported.
DATA_DIR = Path(tempfile.mkdtemp(prefix="formlens-test-"))
os.environ["FORMLENS_DATA"] = str(DATA_DIR)
