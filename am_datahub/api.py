"""REST API over the engineering data store."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query, Request

from . import importers
from .genealogy import trace_specimen, where_used
from .quality import build_density, energy_density, imr_chart

IMPORTERS = {
    "lots": importers.import_lots,
    "lot_parents": importers.import_lot_parents,
    "builds": importers.import_builds,
    "parts": importers.import_parts,
    "tests": importers.import_tests,
}


def create_app(conn: sqlite3.Connection) -> FastAPI:
    app = FastAPI(title="am-datahub", version="0.1.0")

    @app.post("/import/{kind}")
    async def import_csv(kind: str, request: Request):
        if kind not in IMPORTERS:
            raise HTTPException(404, f"unknown import kind {kind!r}")
        res = IMPORTERS[kind](conn, (await request.body()).decode("utf-8-sig"))
        return {"kind": res.kind, "accepted": res.accepted, "rejected": res.rejected}

    @app.post("/builds/{build_id}/layer-log")
    async def layer_log(build_id: str, request: Request):
        res = importers.import_layer_log(conn, build_id, (await request.body()).decode("utf-8-sig"))
        return {"accepted": res.accepted, "rejected": res.rejected}

    @app.get("/builds")
    def builds(material: str | None = None):
        rows = conn.execute(
            """SELECT b.*, s.max_oxygen_ppm, s.layers_over_limit, s.recoater_events
               FROM builds b LEFT JOIN build_log_summary s USING (build_id)
               WHERE (? IS NULL OR material = ?) ORDER BY started_at""", (material, material)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["energy_density_j_mm3"] = round(energy_density(
                r["laser_power_w"], r["scan_speed_mm_s"], r["hatch_spacing_mm"], r["layer_thickness_mm"]), 2)
            out.append(d)
        return out

    @app.get("/specimens/{specimen_id}/trace")
    def trace(specimen_id: str):
        t = trace_specimen(conn, specimen_id)
        if t is None:
            raise HTTPException(404, "no such specimen")
        return t

    @app.get("/lots/{lot_id}/where-used")
    def lot_where_used(lot_id: str):
        if conn.execute("SELECT 1 FROM powder_lots WHERE lot_id = ?", (lot_id,)).fetchone() is None:
            raise HTTPException(404, "no such lot")
        return where_used(conn, lot_id)

    @app.get("/quality/density-chart")
    def density_chart(material: str, baseline: int = Query(10, ge=3), spec_min: float | None = None):
        series = build_density(conn, material)
        try:
            return asdict(imr_chart(series, baseline, spec_min, material))
        except ValueError as e:
            raise HTTPException(422, str(e))

    return app
