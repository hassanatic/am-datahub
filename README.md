# am-datahub

Engineering data for additive manufacturing in one place: powder lots and how they were
blended and reused, build parameters, per-layer machine logs and lab results, joined so
that a question like *"this tensile bar failed, which powder did it come from?"* is one
API call.

I built it to learn how a central engineering data platform for powder bed fusion could
be organised. It is a practice project on synthetic data, not a production system.

## What it does

- **Imports with validation.** CSV importers for lots, blends, builds, parts and lab
  results check every row, upsert the good ones on the source's own key (a re-sent file
  updates rather than duplicates) and return the rejected rows with a reason. A build
  that uses a powder lot of a different material, a blend whose fractions add to more
  than 1, a circular blend or a relative density over 100 % is refused.
- **One unit per property.** Lab results arrive as fractions or percentages, MPa or ksi;
  they are stored in one canonical unit, and a value in an unsupported unit is rejected
  instead of being compared with values in another unit.
- **Genealogy, both directions.** From a specimen back to its part, build and powder lots,
  including the lots a blend was made from (recursive SQL). From a powder lot forward to
  every build and part that used it, directly or through a blend, for a recall or a
  supplier question.
- **Machine logs.** Per-layer logs are summarised per build: layers, peak oxygen, layers
  over the limit, recoater events.
- **Process quality.** Volumetric energy density (P / (v h t)) per build, and an
  individuals and moving-range control chart of part density per material. Limits come
  from a baseline of earlier builds, so a drift is flagged (outside 3 sigma, or 8 in a
  row on one side of the centre) before it crosses the specification limit.

The demo data plants the problems it should catch: a density drift after builds switch to
a sieved, reused powder blend, an oxygen excursion in one build, and bad rows in the lab
export.

## API

```
POST /import/{lots|lot_parents|builds|parts|tests}   CSV body, returns accepted and rejected rows
POST /builds/{build_id}/layer-log                    CSV body
GET  /builds?material=AlSi10Mg                       with energy density and log summary
GET  /specimens/{specimen_id}/trace                  part, build, powder lots, test results
GET  /lots/{lot_id}/where-used                       builds and parts, including through blends
GET  /quality/density-chart?material=...&spec_min=99.5
```

FastAPI serves the OpenAPI description at `/docs`.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
python -m am_datahub sample --dir data --db am.db   # synthetic data, prints rejected rows
python -m am_datahub serve --db am.db                # http://localhost:8000/docs
pytest -q
```

## Limits

- SQLite and a single process; a real platform would sit on a server database and pull
  from machines and LIMS rather than CSV uploads.
- The process numbers are illustrative, not qualified parameters for any material or
  machine.
- No authentication, no front end beyond the generated API docs.

## Licence

MIT
