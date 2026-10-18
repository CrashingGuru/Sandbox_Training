#!/usr/bin/env python3
"""Admin tool: add a dataset to the catalog and (optionally) push to GitHub.

Does the whole update as one transaction so the repo is never half-updated:
  1. create datasets/<slug>/{data,metadata}/ and copy the data file(s) in
  2. compute rows/columns (CSV), bytes and sha256 for each file
  3. write metadata.yaml
  4. validate every metadata file against schema/metadata.schema.json
  5. regenerate DATASETS.md and datasets.json
  6. git add + commit  (and git push with --push)

Example:
    python scripts/add_dataset.py \\
        --slug crop-recommendation \\
        --name "Crop Recommendation Dataset" \\
        --data ./Crop_recommendation.csv \\
        --description "N-P-K, temperature, humidity, pH, rainfall -> crop." \\
        --source "https://www.kaggle.com/..." \\
        --license CC-BY-4.0 \\
        --tags agriculture,classification \\
        --push
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

import catalog

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def csv_shape(path: Path) -> tuple[int, int] | tuple[None, None]:
    """(data_rows, columns) for a CSV, else (None, None)."""
    if path.suffix.lower() not in {".csv", ".tsv"}:
        return None, None
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=delim)
        try:
            header = next(reader)
        except StopIteration:
            return 0, 0
        cols = len(header)
        rows = sum(1 for _ in reader)
    return rows, cols


def git(*args: str) -> None:
    subprocess.run(["git", "-C", str(catalog.REPO_ROOT), *args], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="URL-safe id; becomes the folder name.")
    ap.add_argument("--name", required=True, help="Human-readable name.")
    ap.add_argument("--data", required=True, nargs="+", type=Path,
                    help="One or more data files to copy into the dataset.")
    ap.add_argument("--description", required=True)
    ap.add_argument("--source", default=None, help="Origin URL.")
    ap.add_argument("--license", required=True)
    ap.add_argument("--tags", default="", help="Comma-separated tags.")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--added-by", default=None, help="Email or handle of the admin.")
    ap.add_argument("--push", action="store_true", help="git push after committing.")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    if not SLUG_RE.match(args.slug):
        print(f"Invalid slug '{args.slug}': use lowercase letters, digits, hyphens.",
              file=sys.stderr)
        return 2

    ds_dir = catalog.DATASETS_DIR / args.slug
    if ds_dir.exists():
        print(f"Dataset '{args.slug}' already exists at {ds_dir.relative_to(catalog.REPO_ROOT)}.",
              file=sys.stderr)
        return 2

    for src in args.data:
        if not src.is_file():
            print(f"Data file not found: {src}", file=sys.stderr)
            return 2

    data_dir = ds_dir / "data"
    meta_dir = ds_dir / "metadata"
    data_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    files_meta = []
    for src in args.data:
        dest = data_dir / src.name
        shutil.copy2(src, dest)
        rows, cols = csv_shape(dest)
        entry = {"path": f"data/{src.name}", "bytes": dest.stat().st_size,
                 "sha256": sha256_of(dest)}
        if rows is not None:
            entry["rows"] = rows
            entry["columns"] = cols
        files_meta.append(entry)

    metadata = {
        "slug": args.slug,
        "name": args.name,
        "description": args.description,
        "version": args.version,
        "date_added": date.today().isoformat(),
        "added_by": args.added_by,
        "source": args.source,
        "license": args.license,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "files": files_meta,
    }
    # Drop optional keys that are None so they don't fail the 'uri'/'string' checks.
    metadata = {k: v for k, v in metadata.items() if v is not None}

    with (meta_dir / "metadata.yaml").open("w") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False, allow_unicode=True)

    # Validate everything and regenerate the indexes. If this raises, we roll back.
    try:
        records = catalog.build(validate=True)
    except ValueError as exc:
        shutil.rmtree(ds_dir)
        print(exc, file=sys.stderr)
        print("Rolled back: no files committed.", file=sys.stderr)
        return 1

    git("add", "-A")
    git("commit", "-m", f"Add dataset: {args.name} ({args.slug})")
    if args.push:
        git("push", "origin", args.branch)
        print("Pushed to GitHub.")
    else:
        print("Committed locally. Re-run with --push (or 'git push') to publish.")

    print(f"Catalog now has {len(records)} dataset(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
