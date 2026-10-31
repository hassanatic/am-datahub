"""Process quality views.

Volumetric energy density E = P / (v * h * t) in J/mm3 is the usual first number for
comparing laser powder bed fusion parameter sets. Part density per build is tracked on
an individuals and moving range (I-MR) chart: control limits come from the process's
own variation, so a drift is flagged before it crosses a specification limit.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

D2 = 1.128  # bias constant for moving ranges of two consecutive points


def energy_density(power_w: float, speed_mm_s: float, hatch_mm: float, layer_mm: float) -> float:
    return power_w / (speed_mm_s * hatch_mm * layer_mm)


@dataclass
class ChartPoint:
    build_id: str
    started_at: str
    value: float
    flags: list[str]


@dataclass
class Chart:
    material: str
    center: float
    lcl: float
    ucl: float
    sigma: float
    points: list[ChartPoint]
    baseline_builds: int


def build_density(conn: sqlite3.Connection, material: str) -> list[tuple[str, str, float]]:
    """Mean relative density per completed build, oldest first."""
    rows = conn.execute(
        """SELECT b.build_id, b.started_at, AVG(t.value) AS density
           FROM builds b JOIN parts p USING (build_id) JOIN specimens s USING (part_id)
           JOIN test_results t ON t.specimen_id = s.specimen_id AND t.property = 'relative_density'
           WHERE b.material = ? AND b.status = 'completed'
           GROUP BY b.build_id ORDER BY b.started_at""", (material,)).fetchall()
    return [(r["build_id"], r["started_at"], r["density"]) for r in rows]


def imr_chart(series: list[tuple[str, str, float]], baseline: int = 10, spec_min: float | None = None,
              material: str = "") -> Chart:
    """Limits from the first `baseline` points; every point is then checked against
    rule 1 (outside 3 sigma) and a run rule (8 in a row on one side of the centre)."""
    if len(series) < 3:
        raise ValueError("need at least three builds to chart")
    base = [v for _, _, v in series[:baseline]]
    center = sum(base) / len(base)
    mr = [abs(b - a) for a, b in zip(base, base[1:])]
    sigma = (sum(mr) / len(mr)) / D2
    lcl, ucl = center - 3 * sigma, center + 3 * sigma

    points, side_run, last_side = [], 0, 0
    for build_id, started, v in series:
        flags = []
        if v < lcl or v > ucl:
            flags.append("outside control limits")
        side = (v > center) - (v < center)
        side_run = side_run + 1 if side and side == last_side else (1 if side else 0)
        last_side = side
        if side_run >= 8:
            flags.append("8 in a row on one side of the centre line")
        if spec_min is not None and v < spec_min:
            flags.append(f"below specification ({spec_min:g})")
        points.append(ChartPoint(build_id, started, round(v, 4), flags))
    return Chart(material, round(center, 4), round(lcl, 4), round(ucl, 4), round(sigma, 5), points,
                 min(baseline, len(series)))
