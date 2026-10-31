"""Lab results arrive in whatever unit the instrument or lab uses. Each property has
one canonical unit in the database; a value in an unknown unit is rejected rather
than stored and silently compared against values in another unit."""

from __future__ import annotations

CANONICAL = {
    "relative_density": "%",
    "ultimate_tensile_strength": "MPa",
    "yield_strength": "MPa",
    "elongation": "%",
    "surface_roughness_ra": "um",
}

# factor to multiply by to reach the canonical unit
FACTORS = {
    ("relative_density", "%"): 1.0,
    ("relative_density", "fraction"): 100.0,
    ("ultimate_tensile_strength", "MPa"): 1.0,
    ("ultimate_tensile_strength", "N/mm2"): 1.0,
    ("ultimate_tensile_strength", "ksi"): 6.894757,
    ("yield_strength", "MPa"): 1.0,
    ("yield_strength", "N/mm2"): 1.0,
    ("yield_strength", "ksi"): 6.894757,
    ("elongation", "%"): 1.0,
    ("elongation", "fraction"): 100.0,
    ("surface_roughness_ra", "um"): 1.0,
    ("surface_roughness_ra", "mm"): 1000.0,
}


class UnitError(ValueError):
    pass


def to_canonical(prop: str, value: float, unit: str) -> tuple[float, str]:
    if prop not in CANONICAL:
        raise UnitError(f"unknown property {prop!r}")
    factor = FACTORS.get((prop, unit.strip()))
    if factor is None:
        raise UnitError(f"{prop}: unit {unit!r} not supported")
    return value * factor, CANONICAL[prop]
