"""python -m am_datahub {sample,serve}"""

from __future__ import annotations

import argparse
from pathlib import Path

from .db import connect
from .sample import load_all, write_all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="am_datahub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="write synthetic data and load it into a database")
    s.add_argument("--dir", default="data")
    s.add_argument("--db", default="am.db")
    v = sub.add_parser("serve")
    v.add_argument("--db", default="am.db")
    v.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    if args.cmd == "sample":
        write_all(Path(args.dir))
        conn = connect(args.db)
        for kind, res in load_all(conn, Path(args.dir)).items():
            print(f"{kind:12} accepted {res.accepted:4}  rejected {len(res.rejected)}")
            for r in res.rejected:
                print(f"             line {r['line']}: {r['reason']}")
        return 0

    import uvicorn
    from .api import create_app
    uvicorn.run(create_app(connect(args.db)), port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
