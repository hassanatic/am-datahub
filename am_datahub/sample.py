"""Deterministic synthetic data: two materials, blended and reused powder lots, 24
builds with a parameter change part-way through, lab results in mixed units, and
per-layer machine logs. Planted problems: a drift in density after a reused-powder
blend, an oxygen excursion in one build, and a handful of bad rows in the exports."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path


def write_all(directory: Path, seed: int = 11) -> None:
    rng = random.Random(seed)
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)

    lots = ["lot_id,material,supplier,received_on,reuse_count"]
    for i in range(1, 7):
        lots.append(f"AL-{i:03d},AlSi10Mg,Supplier {'A' if i % 2 else 'B'},2026-0{1 + i // 3}-1{i},0")
    lots.append("AL-R01,AlSi10Mg,,2026-04-02,3")       # sieved, reused blend
    lots.append("TI-001,Ti6Al4V,Supplier C,2026-02-20,0")
    lots.append("TI-002,Ti6Al4V,Supplier C,2026-03-28,0")
    lots.append("BAD-001,,Supplier A,2026-03-01,0")       # missing material
    (d / "lots.csv").write_text("\n".join(lots) + "\n")

    (d / "lot_parents.csv").write_text(
        "lot_id,parent_lot_id,fraction\nAL-R01,AL-003,0.6\nAL-R01,AL-004,0.4\n")

    builds = ["build_id,machine_id,material,started_at,laser_power_w,scan_speed_mm_s,"
              "hatch_spacing_mm,layer_thickness_mm,status,lots"]
    parts = ["part_id,build_id,position,specimen_id"]
    tests = ["specimen_id,property,value,unit,measured_on,lab"]
    start = datetime(2026, 4, 1, 8)
    for i in range(24):
        bid = f"B{i + 1:03d}"
        t = start + timedelta(days=i * 2)
        if i < 14:
            lot, density = f"AL-00{1 + i % 6}", rng.gauss(99.62, 0.06)
        else:
            lot, density = "AL-R01", rng.gauss(99.42, 0.06)  # drift after the reused blend
        builds.append(f"{bid},M-{1 + i % 2},AlSi10Mg,{t.isoformat()},370,1300,0.19,0.03,completed,{lot}")
        for k in range(2):
            pid, sid = f"{bid}-P{k + 1}", f"{bid}-S{k + 1}"
            parts.append(f"{pid},{bid},plate {k + 1},{sid}")
            v = density + rng.gauss(0, 0.03)
            if i % 5 == 0:
                tests.append(f"{sid},relative_density,{v / 100:.5f},fraction,{(t + timedelta(days=3)).date()},Lab 1")
            else:
                tests.append(f"{sid},relative_density,{v:.3f},%,{(t + timedelta(days=3)).date()},Lab 1")
            uts = rng.gauss(440 if i < 14 else 425, 8)
            if i % 4 == 0:
                tests.append(f"{sid},ultimate_tensile_strength,{uts / 6.894757:.2f},ksi,{(t + timedelta(days=4)).date()},Lab 2")
            else:
                tests.append(f"{sid},ultimate_tensile_strength,{uts:.1f},MPa,{(t + timedelta(days=4)).date()},Lab 2")
    builds.append("B100,M-1,Ti6Al4V,2026-05-01T09:00:00,280,1200,0.14,0.03,completed,AL-001")  # wrong material
    builds.append("B101,M-2,Ti6Al4V,2026-05-03T09:00:00,280,1200,0.14,0.03,completed,TI-001")
    tests.append("B001-S1,hardness,120,HV,2026-04-05,Lab 3")             # property not handled
    tests.append("B002-S1,relative_density,101.2,%,2026-04-06,Lab 1")    # not physical
    tests.append("B003-S1,yield_strength,250,psi,2026-04-07,Lab 2")      # unsupported unit

    (d / "builds.csv").write_text("\n".join(builds) + "\n")
    (d / "parts.csv").write_text("\n".join(parts) + "\n")
    (d / "tests.csv").write_text("\n".join(tests) + "\n")

    logs = d / "layer_logs"
    logs.mkdir(exist_ok=True)
    for i in range(24):
        bid = f"B{i + 1:03d}"
        rows = ["layer,oxygen_ppm,recoater_event"]
        for layer in range(1, 401):
            o2 = rng.gauss(600, 60)
            if bid == "B009" and 120 <= layer < 160:
                o2 = rng.gauss(1400, 80)                                 # inert gas problem
            event = 1 if rng.random() < 0.004 else 0
            rows.append(f"{layer},{o2:.0f},{event}")
        (logs / f"{bid}.csv").write_text("\n".join(rows) + "\n")


def load_all(conn, directory: Path) -> dict:
    from . import importers
    d = Path(directory)
    out = {}
    for kind, fn in [("lots", importers.import_lots), ("lot_parents", importers.import_lot_parents),
                     ("builds", importers.import_builds), ("parts", importers.import_parts),
                     ("tests", importers.import_tests)]:
        out[kind] = fn(conn, (d / f"{kind}.csv").read_text())
    for f in sorted((d / "layer_logs").glob("*.csv")):
        importers.import_layer_log(conn, f.stem, f.read_text())
    return out
