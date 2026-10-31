"""Traceability in both directions.

Backwards: a specimen failed a test; which build made it, which powder lots fed that
build, and which lots were those blended from? Forwards: a powder lot is suspect;
which builds and parts used it, directly or through a blend?
"""

from __future__ import annotations

import sqlite3


def trace_specimen(conn: sqlite3.Connection, specimen_id: str) -> dict | None:
    head = conn.execute(
        """SELECT s.specimen_id, p.part_id, b.build_id, b.machine_id, b.material, b.started_at
           FROM specimens s JOIN parts p USING (part_id) JOIN builds b USING (build_id)
           WHERE s.specimen_id = ?""", (specimen_id,)).fetchone()
    if head is None:
        return None
    lots = conn.execute(
        """WITH RECURSIVE lineage(lot_id, depth, share) AS (
             SELECT lot_id, 0, 1.0 FROM build_powder WHERE build_id = ?
             UNION ALL
             SELECT lp.parent_lot_id, l.depth + 1, l.share * lp.fraction
             FROM lot_parents lp JOIN lineage l ON lp.lot_id = l.lot_id)
           SELECT l.lot_id, MIN(l.depth) AS depth, pl.supplier, pl.reuse_count
           FROM lineage l JOIN powder_lots pl USING (lot_id)
           GROUP BY l.lot_id ORDER BY depth, l.lot_id""", (head["build_id"],)).fetchall()
    tests = conn.execute(
        "SELECT property, value, unit, measured_on FROM test_results WHERE specimen_id = ? ORDER BY property",
        (specimen_id,)).fetchall()
    return {**dict(head), "powder_lots": [dict(r) for r in lots], "tests": [dict(r) for r in tests]}


def where_used(conn: sqlite3.Connection, lot_id: str) -> dict:
    rows = conn.execute(
        """WITH RECURSIVE descendants(lot_id) AS (
             SELECT ?
             UNION SELECT lp.lot_id FROM lot_parents lp JOIN descendants d ON lp.parent_lot_id = d.lot_id)
           SELECT DISTINCT b.build_id, bp.lot_id AS via_lot, p.part_id
           FROM descendants d
           JOIN build_powder bp ON bp.lot_id = d.lot_id
           JOIN builds b ON b.build_id = bp.build_id
           LEFT JOIN parts p ON p.build_id = b.build_id
           ORDER BY b.build_id, p.part_id""", (lot_id,)).fetchall()
    builds: dict[str, dict] = {}
    for r in rows:
        b = builds.setdefault(r["build_id"], {"build_id": r["build_id"], "via_lots": set(), "parts": []})
        b["via_lots"].add(r["via_lot"])
        if r["part_id"] and r["part_id"] not in b["parts"]:
            b["parts"].append(r["part_id"])
    return {"lot_id": lot_id,
            "builds": [{**b, "via_lots": sorted(b["via_lots"])} for b in builds.values()]}
