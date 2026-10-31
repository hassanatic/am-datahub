import pytest

from am_datahub import importers
from am_datahub.db import connect
from am_datahub.genealogy import trace_specimen, where_used
from am_datahub.quality import energy_density, imr_chart
from am_datahub.units import UnitError, to_canonical


@pytest.fixture
def conn():
    c = connect()
    importers.import_lots(c, "lot_id,material,supplier,received_on,reuse_count\n"
                             "A1,AlSi10Mg,S,2026-01-10,0\nA2,AlSi10Mg,S,2026-01-11,0\n"
                             "R1,AlSi10Mg,,2026-02-01,2\nR2,AlSi10Mg,,2026-03-01,4\nT1,Ti6Al4V,S,2026-01-12,0\n")
    importers.import_lot_parents(c, "lot_id,parent_lot_id,fraction\nR1,A1,0.5\nR1,A2,0.5\nR2,R1,1.0\n")
    return c


def test_units_convert_to_one_canonical_unit_and_refuse_the_rest():
    assert to_canonical("relative_density", 0.995, "fraction") == (99.5, "%")
    assert to_canonical("ultimate_tensile_strength", 60, "ksi")[0] == pytest.approx(413.69, abs=0.01)
    with pytest.raises(UnitError):
        to_canonical("yield_strength", 1, "psi")
    with pytest.raises(UnitError):
        to_canonical("hardness", 1, "HV")


def test_bad_rows_are_rejected_with_a_reason_and_good_rows_still_load():
    c = connect()
    res = importers.import_lots(c, "lot_id,material,reuse_count\nX1,AlSi10Mg,0\nX2,,0\nX3,AlSi10Mg,-1\n")
    assert res.accepted == 1
    assert [r["line"] for r in res.rejected] == [3, 4]
    assert "missing material" in res.rejected[0]["reason"]


def test_reimport_updates_instead_of_duplicating(conn):
    importers.import_lots(conn, "lot_id,material,reuse_count\nA1,AlSi10Mg,5\n")
    rows = conn.execute("SELECT reuse_count FROM powder_lots WHERE lot_id = 'A1'").fetchall()
    assert [r[0] for r in rows] == [5]


def test_blend_fractions_and_cycles_are_checked(conn):
    res = importers.import_lot_parents(conn, "lot_id,parent_lot_id,fraction\nA1,R2,0.5\n")
    assert res.accepted == 0 and "cycle" in res.rejected[0]["reason"]
    res = importers.import_lot_parents(conn, "lot_id,parent_lot_id,fraction\nT1,A1,0.7\nT1,A2,0.6\n")
    assert res.accepted == 0 and "add up to" in res.rejected[0]["reason"]


def test_build_must_use_lots_of_its_own_material(conn):
    head = ("build_id,machine_id,material,started_at,laser_power_w,scan_speed_mm_s,"
            "hatch_spacing_mm,layer_thickness_mm,status,lots\n")
    res = importers.import_builds(conn, head + "B1,M,Ti6Al4V,2026-04-01T08:00:00,280,1200,0.14,0.03,completed,A1\n")
    assert res.accepted == 0 and "is AlSi10Mg" in res.rejected[0]["reason"]
    res = importers.import_builds(conn, head + "B2,M,AlSi10Mg,2026-04-01T08:00:00,370,1300,0.19,0.03,completed,ZZ\n")
    assert "unknown powder lot" in res.rejected[0]["reason"]


def _build(conn, bid, lot, density):
    head = ("build_id,machine_id,material,started_at,laser_power_w,scan_speed_mm_s,"
            "hatch_spacing_mm,layer_thickness_mm,status,lots\n")
    importers.import_builds(conn, head + f"{bid},M,AlSi10Mg,2026-04-{int(bid[1:]):02d}T08:00:00,370,1300,0.19,0.03,completed,{lot}\n")
    importers.import_parts(conn, f"part_id,build_id,position,specimen_id\n{bid}-P,{bid},a,{bid}-S\n")
    importers.import_tests(conn, f"specimen_id,property,value,unit,measured_on,lab\n{bid}-S,relative_density,{density},%,2026-05-01,L\n")


def test_trace_walks_from_specimen_back_through_blends(conn):
    _build(conn, "B1", "R2", 99.4)
    t = trace_specimen(conn, "B1-S")
    assert t["build_id"] == "B1"
    assert [(l["lot_id"], l["depth"]) for l in t["powder_lots"]] == [("R2", 0), ("R1", 1), ("A1", 2), ("A2", 2)]
    assert t["tests"][0]["value"] == 99.4
    assert trace_specimen(conn, "nope") is None


def test_where_used_finds_builds_through_blends(conn):
    _build(conn, "B1", "A1", 99.6)
    _build(conn, "B2", "R2", 99.4)
    _build(conn, "B3", "A2", 99.6)
    w = where_used(conn, "A1")
    assert [(b["build_id"], b["via_lots"]) for b in w["builds"]] == [("B1", ["A1"]), ("B2", ["R2"])]


def test_energy_density():
    # 370 W / (1300 mm/s * 0.19 mm * 0.03 mm) = 49.93 J/mm3
    assert energy_density(370, 1300, 0.19, 0.03) == pytest.approx(49.93, abs=0.01)


def test_control_chart_limits_come_from_the_baseline_and_flag_a_drift():
    stable = [99.60, 99.62, 99.58, 99.61, 99.63, 99.59, 99.60, 99.62, 99.61, 99.60]
    # baseline LCL is 99.547 (centre 99.606, sigma 0.0197), so 99.52 is outside it
    drift = [99.52, 99.54, 99.53, 99.52, 99.53, 99.54, 99.52, 99.53]
    series = [(f"B{i}", f"2026-04-{i + 1:02d}", v) for i, v in enumerate(stable + drift)]
    ch = imr_chart(series, baseline=10, spec_min=99.5)
    mr = [abs(b - a) for a, b in zip(stable, stable[1:])]
    assert ch.center == pytest.approx(sum(stable) / 10, abs=1e-4)
    assert ch.sigma == pytest.approx(sum(mr) / len(mr) / 1.128, abs=1e-5)
    assert all(not p.flags for p in ch.points[:10])
    assert "outside control limits" in ch.points[10].flags
    assert "8 in a row on one side of the centre line" in ch.points[-1].flags
    assert not any("specification" in f for p in ch.points for f in p.flags)


def test_chart_needs_enough_points():
    with pytest.raises(ValueError):
        imr_chart([("B1", "x", 99.0), ("B2", "y", 99.1)])
