"""CSV importers. Each one validates every row, upserts the good ones on the source's
own key and returns the rejected rows with a reason, so one bad line in a lab export
does not block the other hundred."""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from .units import UnitError, to_canonical

O2_LIMIT_PPM = 1000.0


@dataclass
class ImportResult:
    kind: str
    accepted: int = 0
    rejected: list[dict] = field(default_factory=list)

    def reject(self, line: int, reason: str) -> None:
        self.rejected.append({"line": line, "reason": reason})


def _rows(text: str):
    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader, start=2):  # line 1 is the header
        yield i, {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def _need(row: dict, *cols: str) -> None:
    missing = [c for c in cols if not row.get(c)]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")


def _date(s: str) -> str:
    return date.fromisoformat(s).isoformat()


def import_lots(conn: sqlite3.Connection, text: str) -> ImportResult:
    res = ImportResult("lots")
    for line, r in _rows(text):
        try:
            _need(r, "lot_id", "material")
            reuse = int(r.get("reuse_count") or 0)
            if reuse < 0:
                raise ValueError("reuse_count cannot be negative")
            conn.execute(
                """INSERT INTO powder_lots (lot_id, material, supplier, received_on, reuse_count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (lot_id) DO UPDATE SET material = excluded.material,
                     supplier = excluded.supplier, received_on = excluded.received_on,
                     reuse_count = excluded.reuse_count""",
                (r["lot_id"], r["material"], r.get("supplier") or None,
                 _date(r["received_on"]) if r.get("received_on") else None, reuse))
            res.accepted += 1
        except (ValueError, sqlite3.Error) as e:
            res.reject(line, str(e))
    conn.commit()
    return res


def import_lot_parents(conn: sqlite3.Connection, text: str) -> ImportResult:
    """Blends: which earlier lots a lot was made from, and in what share."""
    res = ImportResult("lot_parents")
    rows = list(_rows(text))
    totals: dict[str, float] = {}
    for line, r in rows:
        try:
            _need(r, "lot_id", "parent_lot_id", "fraction")
            totals[r["lot_id"]] = totals.get(r["lot_id"], 0) + float(r["fraction"])
        except ValueError:
            pass
    for line, r in rows:
        try:
            _need(r, "lot_id", "parent_lot_id", "fraction")
            if totals[r["lot_id"]] > 1.0001:
                raise ValueError(f"fractions for {r['lot_id']} add up to {totals[r['lot_id']]:.2f}")
            _check_no_cycle(conn, r["lot_id"], r["parent_lot_id"])
            conn.execute(
                """INSERT INTO lot_parents (lot_id, parent_lot_id, fraction) VALUES (?, ?, ?)
                   ON CONFLICT (lot_id, parent_lot_id) DO UPDATE SET fraction = excluded.fraction""",
                (r["lot_id"], r["parent_lot_id"], float(r["fraction"])))
            res.accepted += 1
        except (ValueError, sqlite3.Error) as e:
            res.reject(line, str(e))
    conn.commit()
    return res


def _check_no_cycle(conn: sqlite3.Connection, lot: str, parent: str) -> None:
    # adding lot <- parent makes a cycle if lot is already an ancestor of parent
    hit = conn.execute(
        """WITH RECURSIVE anc(id) AS (
             SELECT parent_lot_id FROM lot_parents WHERE lot_id = ?
             UNION SELECT lp.parent_lot_id FROM lot_parents lp JOIN anc ON lp.lot_id = anc.id)
           SELECT 1 FROM anc WHERE id = ?""", (parent, lot)).fetchone()
    if hit or lot == parent:
        raise ValueError(f"{lot} <- {parent} would make a cycle in the lot genealogy")


def import_builds(conn: sqlite3.Connection, text: str) -> ImportResult:
    res = ImportResult("builds")
    cols = ("build_id", "machine_id", "material", "started_at", "laser_power_w", "scan_speed_mm_s",
            "hatch_spacing_mm", "layer_thickness_mm", "status", "lots")
    for line, r in _rows(text):
        try:
            _need(r, *cols)
            datetime.fromisoformat(r["started_at"])
            nums = [float(r[c]) for c in cols[4:8]]
            if any(n <= 0 for n in nums):
                raise ValueError("process parameters must be positive")
            lots = [x for x in r["lots"].split(";") if x]
            for lot in lots:
                row = conn.execute("SELECT material FROM powder_lots WHERE lot_id = ?", (lot,)).fetchone()
                if row is None:
                    raise ValueError(f"unknown powder lot {lot}")
                if row["material"] != r["material"]:
                    raise ValueError(f"lot {lot} is {row['material']}, build is {r['material']}")
            conn.execute(
                """INSERT INTO builds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (build_id) DO UPDATE SET machine_id = excluded.machine_id,
                     material = excluded.material, started_at = excluded.started_at,
                     laser_power_w = excluded.laser_power_w, scan_speed_mm_s = excluded.scan_speed_mm_s,
                     hatch_spacing_mm = excluded.hatch_spacing_mm,
                     layer_thickness_mm = excluded.layer_thickness_mm, status = excluded.status""",
                (r["build_id"], r["machine_id"], r["material"], r["started_at"], *nums, r["status"]))
            conn.execute("DELETE FROM build_powder WHERE build_id = ?", (r["build_id"],))
            conn.executemany("INSERT INTO build_powder VALUES (?, ?)", [(r["build_id"], lot) for lot in lots])
            res.accepted += 1
        except (ValueError, sqlite3.Error) as e:
            res.reject(line, str(e))
    conn.commit()
    return res


def import_parts(conn: sqlite3.Connection, text: str) -> ImportResult:
    res = ImportResult("parts")
    for line, r in _rows(text):
        try:
            _need(r, "part_id", "build_id")
            conn.execute(
                """INSERT INTO parts VALUES (?, ?, ?) ON CONFLICT (part_id) DO UPDATE SET
                   build_id = excluded.build_id, position = excluded.position""",
                (r["part_id"], r["build_id"], r.get("position") or None))
            if r.get("specimen_id"):
                conn.execute("INSERT OR IGNORE INTO specimens VALUES (?, ?)", (r["specimen_id"], r["part_id"]))
            res.accepted += 1
        except (ValueError, sqlite3.Error) as e:
            res.reject(line, str(e))
    conn.commit()
    return res


def import_tests(conn: sqlite3.Connection, text: str) -> ImportResult:
    res = ImportResult("tests")
    for line, r in _rows(text):
        try:
            _need(r, "specimen_id", "property", "value", "unit", "measured_on")
            value, unit = to_canonical(r["property"], float(r["value"]), r["unit"])
            if r["property"] == "relative_density" and not 0 < value <= 100:
                raise ValueError(f"relative density {value:g} % is not physical")
            conn.execute(
                """INSERT INTO test_results VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (specimen_id, property) DO UPDATE SET value = excluded.value,
                     unit = excluded.unit, measured_on = excluded.measured_on, lab = excluded.lab""",
                (r["specimen_id"], r["property"], value, unit, _date(r["measured_on"]), r.get("lab") or None))
            res.accepted += 1
        except (ValueError, UnitError, sqlite3.Error) as e:
            res.reject(line, str(e))
    conn.commit()
    return res


def import_layer_log(conn: sqlite3.Connection, build_id: str, text: str) -> ImportResult:
    """Summarise a per-layer machine log: oxygen level and recoater events."""
    res = ImportResult("layer_log")
    layers, max_o2, over, recoater = 0, 0.0, 0, 0
    seen: set[int] = set()
    for line, r in _rows(text):
        try:
            _need(r, "layer", "oxygen_ppm")
            layer = int(r["layer"])
            if layer in seen:
                raise ValueError(f"layer {layer} repeated")
            seen.add(layer)
            o2 = float(r["oxygen_ppm"])
            layers += 1
            max_o2 = max(max_o2, o2)
            over += o2 > O2_LIMIT_PPM
            recoater += (r.get("recoater_event") or "").lower() in ("1", "true", "yes")
            res.accepted += 1
        except ValueError as e:
            res.reject(line, str(e))
    try:
        conn.execute(
            """INSERT INTO build_log_summary VALUES (?, ?, ?, ?, ?) ON CONFLICT (build_id) DO UPDATE SET
               layers = excluded.layers, max_oxygen_ppm = excluded.max_oxygen_ppm,
               layers_over_limit = excluded.layers_over_limit, recoater_events = excluded.recoater_events""",
            (build_id, layers, max_o2, over, recoater))
        conn.commit()
    except sqlite3.Error as e:
        res.reject(0, str(e))
    return res
