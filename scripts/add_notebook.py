#!/usr/bin/env python3
"""Admin tool: add a notebook to the catalog and (optionally) push to GitHub.

Mirrors add_dataset.py. Transactional, so the repo is never half-updated:
  1. create notebooks/<slug>/{notebook,metadata}/ and copy the .ipynb in
  2. compute bytes and sha256 for each file
  3. write metadata.yaml (provided fields filled, the rest left empty as a template)
  4. validate every notebook metadata file against schema/notebook.metadata.schema.json
  5. regenerate NOTEBOOKS.md, notebooks.json and the per-notebook README
  6. git add + commit  (and git push with --push)

Example:
    python scripts/add_notebook.py \\
        --slug crop-recommendation-reference \\
        --name "Crop Recommendation - Reference Solution" \\
        --notebook ./Crop_Recommendation_Reference.ipynb \\
        --dataset crop-recommendation \\
        --description "Reference LogReg + Decision Tree solution." \\
        --language Python \\
        --libraries pandas,scikit-learn,matplotlib \\
        --tags reference-solution,classification \\
        --license CC0-1.0 \\
        --push
"""
from __future__ import annotations

import argparse
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

# Optional fields always written to metadata.yaml (empty = fill-in-later template).
TEMPLATE_EMPTY = {"authors": [], "source": "", "doi": "", "results": "", "notes": ""}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> None:
    subprocess.run(["git", "-C", str(catalog.REPO_ROOT), *args], check=True)


def _split(csv: str) -> list[str]:
    return [x.strip() for x in csv.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="URL-safe id; becomes the folder name.")
    ap.add_argument("--name", required=True, help="Human-readable title.")
    ap.add_argument("--notebook", required=True, nargs="+", type=Path,
                    help="One or more .ipynb files to copy into the notebook folder.")
    ap.add_argument("--description", required=True)
    ap.add_argument("--dataset", default="", help="Slug of the related dataset (optional).")
    ap.add_argument("--language", default="Python")
    ap.add_argument("--libraries", default="", help="Comma-separated libraries.")
    ap.add_argument("--tags", default="", help="Comma-separated tags.")
    ap.add_argument("--authors", default="", help="Comma-separated authors (optional).")
    ap.add_argument("--license", default="")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--added-by", default=None)
    ap.add_argument("--push", action="store_true", help="git push after committing.")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    if not SLUG_RE.match(args.slug):
        print(f"Invalid slug '{args.slug}': use lowercase letters, digits, hyphens.",
              file=sys.stderr)
        return 2

    nb_dir = catalog.NOTEBOOKS_DIR / args.slug
    if nb_dir.exists():
        print(f"Notebook '{args.slug}' already exists.", file=sys.stderr)
        return 2

    for src in args.notebook:
        if not src.is_file():
            print(f"Notebook file not found: {src}", file=sys.stderr)
            return 2

    # Soft check: warn (don't fail) if the linked dataset is not in the repo.
    if args.dataset and not (catalog.DATASETS_DIR / args.dataset).exists():
        print(f"Warning: dataset '{args.dataset}' not found under datasets/. "
              "Link recorded anyway.", file=sys.stderr)

    file_dir = nb_dir / "notebook"
    meta_dir = nb_dir / "metadata"
    file_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    files_meta = []
    for src in args.notebook:
        dest = file_dir / src.name
        shutil.copy2(src, dest)
        entry = {"path": f"notebook/{src.name}", "bytes": dest.stat().st_size,
                 "sha256": sha256_of(dest)}
        if src.suffix.lower() == ".ipynb":
            entry["format"] = "ipynb"
        files_meta.append(entry)

    # Provided fields first, then template-empty fields for anything not given.
    metadata = {
        "slug": args.slug,
        "name": args.name,
        "description": args.description,
        "version": args.version,
        "date_added": date.today().isoformat(),
        "added_by": args.added_by,
        "dataset": args.dataset,
        "language": args.language,
        "libraries": _split(args.libraries),
        "tags": _split(args.tags),
        "license": args.license,
    }
    if args.added_by is None:
        metadata.pop("added_by")
    # Fill template-empty optional fields (authors/source/doi/results/notes).
    provided_authors = _split(args.authors)
    for key, empty in TEMPLATE_EMPTY.items():
        metadata[key] = provided_authors if key == "authors" and provided_authors else empty
    metadata["files"] = files_meta

    with (meta_dir / "metadata.yaml").open("w") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False, allow_unicode=True)

    try:
        records = catalog.build(validate=True)["notebooks"]
    except ValueError as exc:
        shutil.rmtree(nb_dir)
        print(exc, file=sys.stderr)
        print("Rolled back: no files committed.", file=sys.stderr)
        return 1

    git("add", "-A")
    git("commit", "-m", f"Add notebook: {args.name} ({args.slug})")
    if args.push:
        git("push", "origin", args.branch)
        print("Pushed to GitHub.")
    else:
        print("Committed locally. Re-run with --push (or 'git push') to publish.")

    print(f"Catalog now has {len(records)} notebook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
