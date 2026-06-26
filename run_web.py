"""Launch the Bank Ledger Dashboard web app (FastAPI + Tabulator).

Usage:
    python run_web.py            # serves on http://127.0.0.1:8000
    python run_web.py --port 9000

All processing is local. Source statements under all_bank_statements/ are never
modified; manual edits live in data/cache/decisions.sqlite.
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Bank Ledger Dashboard web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = parser.parse_args()

    print(f"\n  Bank Ledger Dashboard  ->  http://{args.host}:{args.port}\n")
    uvicorn.run("web.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
