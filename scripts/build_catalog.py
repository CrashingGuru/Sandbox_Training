#!/usr/bin/env python3
"""Regenerate DATASETS.md and datasets.json from all dataset metadata.

Usage:
    python scripts/build_catalog.py           # regenerate
    python scripts/build_catalog.py --check    # CI: fail if out of sync (no writes)
"""
from __future__ import annotations

import argparse
import sys

import catalog


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="Verify indexes are in sync without writing; exit 1 if not.")
    args = ap.parse_args()

    if args.check:
        try:
            problems = catalog.check_in_sync()
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        if problems:
            print("Catalog out of sync:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("Catalog is in sync.")
        return 0

    try:
        records = catalog.build(validate=True)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Regenerated DATASETS.md and datasets.json ({len(records)} dataset(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
