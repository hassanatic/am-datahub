"""SQLite schema for engineering data from additive manufacturing.

Every table keys on the identifier the source system already uses (lot number, build
id, specimen id), so a re-sent file updates rows instead of duplicating them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS powder_lots (
    lot_id        TEXT PRIMARY KEY,
    material      TEXT NOT NULL,
    supplier      TEXT,
    received_on   TEXT,
    reuse_count   INTEGER NOT NULL DEFAULT 0 CHECK (reuse_count >= 0)
);

-- A blended or sieved-and-reused lot is made from earlier lots.
CREATE TABLE IF NOT EXISTS lot_parents (
    lot_id        TEXT NOT NULL REFERENCES powder_lots(lot_id),
    parent_lot_id TEXT NOT NULL REFERENCES powder_lots(lot_id),
    fraction      REAL NOT NULL CHECK (fraction > 0 AND fraction <= 1),
    PRIMARY KEY (lot_id, parent_lot_id),
    CHECK (lot_id <> parent_lot_id)
);

CREATE TABLE IF NOT EXISTS builds (
    build_id            TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    material            TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    laser_power_w       REAL NOT NULL CHECK (laser_power_w > 0),
    scan_speed_mm_s     REAL NOT NULL CHECK (scan_speed_mm_s > 0),
    hatch_spacing_mm    REAL NOT NULL CHECK (hatch_spacing_mm > 0),
    layer_thickness_mm  REAL NOT NULL CHECK (layer_thickness_mm > 0),
    status              TEXT NOT NULL CHECK (status IN ('completed', 'aborted', 'running'))
);

CREATE TABLE IF NOT EXISTS build_powder (
    build_id  TEXT NOT NULL REFERENCES builds(build_id),
    lot_id    TEXT NOT NULL REFERENCES powder_lots(lot_id),
    PRIMARY KEY (build_id, lot_id)
);

CREATE TABLE IF NOT EXISTS parts (
    part_id   TEXT PRIMARY KEY,
    build_id  TEXT NOT NULL REFERENCES builds(build_id),
    position  TEXT
);

CREATE TABLE IF NOT EXISTS specimens (
    specimen_id TEXT PRIMARY KEY,
    part_id     TEXT NOT NULL REFERENCES parts(part_id)
);

-- Values are stored in one canonical unit per property (see units.py).
CREATE TABLE IF NOT EXISTS test_results (
    specimen_id TEXT NOT NULL REFERENCES specimens(specimen_id),
    property    TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    measured_on TEXT NOT NULL,
    lab         TEXT,
    PRIMARY KEY (specimen_id, property)
);

-- Per-layer machine log, summarised on import.
CREATE TABLE IF NOT EXISTS build_log_summary (
    build_id          TEXT PRIMARY KEY REFERENCES builds(build_id),
    layers            INTEGER NOT NULL,
    max_oxygen_ppm    REAL NOT NULL,
    layers_over_limit INTEGER NOT NULL,
    recoater_events   INTEGER NOT NULL
);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    # FastAPI runs sync endpoints in a thread pool; writes are serialised by SQLite itself
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
