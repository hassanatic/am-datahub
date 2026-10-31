from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from am_datahub.api import create_app
from am_datahub.db import connect
from am_datahub.sample import write_all


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    write_all(data)
    c = TestClient(create_app(connect()))
    for kind in ("lots", "lot_parents", "builds", "parts", "tests"):
        r = c.post(f"/import/{kind}", content=(data / f"{kind}.csv").read_bytes(),
                   headers={"content-type": "text/csv"})
        assert r.status_code == 200
    for f in sorted((data / "layer_logs").glob("*.csv")):
        assert c.post(f"/builds/{f.stem}/layer-log", content=f.read_bytes()).status_code == 200
    return c


def test_import_reports_rejections_without_blocking_good_rows(client):
    r = client.post("/import/tests", content=b"specimen_id,property,value,unit,measured_on,lab\n"
                                             b"B001-S1,relative_density,0.996,fraction,2026-04-05,L\n"
                                             b"B001-S2,yield_strength,250,psi,2026-04-05,L\n")
    assert r.json()["accepted"] == 1
    assert "psi" in r.json()["rejected"][0]["reason"]
    assert client.post("/import/nonsense", content=b"a\n").status_code == 404


def test_builds_carry_energy_density_and_the_log_summary(client):
    builds = {b["build_id"]: b for b in client.get("/builds", params={"material": "AlSi10Mg"}).json()}
    assert len(builds) == 24
    assert builds["B001"]["energy_density_j_mm3"] == pytest.approx(49.93, abs=0.01)
    assert builds["B009"]["layers_over_limit"] > 0
    assert builds["B001"]["layers_over_limit"] == 0


def test_trace_and_where_used(client):
    t = client.get("/specimens/B020-S1/trace").json()
    assert [l["lot_id"] for l in t["powder_lots"]] == ["AL-R01", "AL-003", "AL-004"]
    w = client.get("/lots/AL-004/where-used").json()
    assert {b["build_id"] for b in w["builds"]} >= {"B004", "B010", "B015", "B024"}
    assert client.get("/specimens/none/trace").status_code == 404
    assert client.get("/lots/none/where-used").status_code == 404


def test_density_chart_flags_the_builds_after_the_reused_blend(client):
    ch = client.get("/quality/density-chart", params={"material": "AlSi10Mg", "spec_min": 99.5}).json()
    flagged = {p["build_id"] for p in ch["points"] if p["flags"]}
    assert flagged and min(flagged) >= "B015"
    assert all(not p["flags"] for p in ch["points"][:10])
    assert client.get("/quality/density-chart", params={"material": "Ti6Al4V"}).status_code == 422
