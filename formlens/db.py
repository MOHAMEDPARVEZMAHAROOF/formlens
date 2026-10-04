"""SQLite persistence for FormLens. Standard library only."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    fields TEXT NOT NULL,          -- JSON array of per-field results
    summary TEXT NOT NULL,         -- JSON summary object
    annotated_path TEXT NOT NULL,  -- local PNG path of annotated output
    aws TEXT NOT NULL DEFAULT '{}',-- JSON: S3 upload attempt result
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def now() -> float:
    return time.time()
