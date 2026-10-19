#!/usr/bin/env python3
"""Admin tool for datasets. Two modes, both transactional (validate -> regenerate
indexes -> commit, with --push to publish):

ADD (default): add a hosted or external dataset.
    # hosted (copies files, computes checksums, auto-LFS for large files)
    python scripts/add_dataset.py --slug crop-recommendation \\
        --name "Crop Recommendation Dataset" --data ./Crop_recommendation.csv \\
        --description "N-P-K, temperature, humidity, pH, rainfall -> crop." \\
        --license CC-BY-4.0 --tags agriculture,classification --push

    # external (pointer only, nothing copied; files auto-discovered from GitHub)
    python scripts/add_dataset.py --external --slug packet-flows \\
        --name "..." --description "..." --license "..." \\
        --source https://github.com/OWNER/REPO \\
        --from-github OWNER/REPO --github-path dataset --push

REFRESH (--refresh-external): re-check / re-sync external datasets whose upstream
files may have changed.
    python scripts/add_dataset.py --refresh-external --all --check-only
    python scripts/add_dataset.py --refresh-external --slug packet-flows --push
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

import catalog

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def discover_github_files(owner: str, repo: str, ref: str, subpath: str,
                          exts: list[str]) -> list[dict]:
    """List blobs under subpath in a public GitHub repo as external file pointers.

    Uses the git trees API (no auth, no download). Returns {name, url, bytes},
    where name is the path relative to subpath.
    """
    api = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
    req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "sandbox-catalog"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https host)
        tree = json.load(resp).get("tree", [])

    prefix = subpath.strip("/")
    prefix_slash = (prefix + "/") if prefix else ""
    out = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        p = node["path"]
        if prefix and not p.startswith(prefix_slash):
            continue
        if exts and not p.lower().endswith(tuple(exts)):
            continue
        out.append({
            "name": p[len(prefix_slash):] if prefix_slash else p,
            "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{p}",
            "bytes": node.get("size"),
        })
    out.sort(key=lambda f: f["name"])
    return out

# Files at or above this size go to Git LFS automatically.
DEFAULT_LFS_THRESHOLD_MB = 50
# Formats that are large/binary by nature -> always LFS, regardless of size.
LFS_EXTENSIONS = {
    ".parquet", ".zip", ".gz", ".tgz", ".tar", ".7z", ".h5", ".hdf5",
    ".npz", ".npy", ".feather", ".arrow", ".pkl", ".pickle", ".db",
    ".sqlite", ".xlsx", ".mp4", ".wav", ".pt", ".pth", ".bin", ".nc",
}


def lfs_available() -> bool:
    return shutil.which("git-lfs") is not None


def ensure_lfs_tracked(rel_path: str) -> None:
    """Make Git LFS track a specific path (idempotent). rel_path is repo-relative."""
    git("lfs", "install", "--local")
    git("lfs", "track", rel_path)


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


# --------------------------------------------------------------------------- #
# Refresh mode: re-check / re-sync external dataset pointers
# --------------------------------------------------------------------------- #
def http_status(url: str) -> tuple[int | None, str | None]:
    """(status_code, content_length) for a URL via HEAD; code is None on network error."""
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "sandbox-catalog"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (https)
            return resp.status, resp.headers.get("Content-Length")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # DNS, timeout, etc.
        return None, str(exc)


def derive_source(r: dict) -> dict | None:
    """Reconstruct discovery params from a dataset's file URLs, for datasets added
    before the external_source block existed."""
    if not r.get("files"):
        return None
    f0 = r["files"][0]
    url, name = f0.get("url", ""), f0.get("name", "")
    marker = "raw.githubusercontent.com/"
    if marker not in url:
        return None
    parts = url.split(marker, 1)[1].split("/")
    if len(parts) < 4:
        return None
    owner, repo, ref = parts[0], parts[1], parts[2]
    full = "/".join(parts[3:])
    path = full[:-len(name)].rstrip("/") if name and full.endswith(name) else ""
    exts = sorted({"." + fn["name"].rsplit(".", 1)[1]
                   for fn in r["files"] if "." in fn.get("name", "")})
    return {"github": f"{owner}/{repo}", "path": path, "ref": ref, "include_ext": exts}


def refresh_external(args) -> int:
    records = [r for r in catalog.load_all(validate=False)
               if r.get("source_type") == "external"]
    if not args.all:
        if not args.slug:
            print("Refresh needs --slug SLUG or --all.", file=sys.stderr)
            return 2
        records = [r for r in records if r["slug"] == args.slug]
    if not records:
        print("No matching external dataset(s).", file=sys.stderr)
        return 2

    if args.check_only:
        problems = 0
        for r in records:
            print(f"\n== {r['slug']} ({len(r['files'])} file(s)) ==")
            for f in r["files"]:
                code, info = http_status(f["url"])
                name = f.get("name") or f["url"].split("/")[-1]
                if code == 200:
                    drift = (f"  SIZE CHANGED {f['bytes']} -> {info}"
                             if info and f.get("bytes") and int(info) != f["bytes"] else "")
                    if drift:
                        problems += 1
                    print(f"  OK   {name}{drift}")
                else:
                    problems += 1
                    print(f"  FAIL {name}  (status={code}{', ' + info if info else ''})")
        print(f"\n{problems} problem(s) found." if problems else "\nAll external files OK.")
        return 1 if problems else 0

    changed = False
    for r in records:
        slug = r["slug"]
        es = r.get("external_source") or derive_source(r)
        if not es or not es.get("github"):
            print(f"{slug}: cannot determine source; skipping.", file=sys.stderr)
            return 2
        owner, repo = es["github"].split("/", 1)
        try:
            new_files = discover_github_files(owner, repo, es.get("ref", "main"),
                                              es.get("path", ""), es.get("include_ext", []))
        except Exception as exc:
            print(f"{slug}: discovery failed: {exc}", file=sys.stderr)
            return 1
        if not new_files:
            print(f"{slug}: source now lists no files; skipping to avoid wiping pointers.",
                  file=sys.stderr)
            return 1

        old = {f["name"]: f.get("bytes") for f in r["files"]}
        new = {f["name"]: f.get("bytes") for f in new_files}
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        resized = sorted(n for n in set(old) & set(new) if old[n] != new[n])
        wrote_block = "external_source" not in r

        print(f"\n== {slug} ==  files: {len(r['files'])} -> {len(new_files)}")
        for n in added:   print(f"  + {n}")
        for n in removed: print(f"  - {n}")
        for n in resized: print(f"  ~ {n} ({old[n]} -> {new[n]} bytes)")
        if not (added or removed or resized):
            print("  pointers unchanged" + (" (recording external_source block)"
                                            if wrote_block else ""))

        meta_path = catalog.DATASETS_DIR / slug / "metadata" / "metadata.yaml"
        data = yaml.safe_load(meta_path.read_text())
        data["external_source"] = es
        data["files"] = new_files
        with meta_path.open("w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        if added or removed or resized or wrote_block:
            changed = True

    if not changed:
        print("\nNothing changed; no commit.")
        return 0

    try:
        catalog.build(validate=True)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        print("Metadata invalid after refresh; NOT committing.", file=sys.stderr)
        return 1

    slugs = ", ".join(r["slug"] for r in records)
    git("add", "-A")
    git("commit", "-m", f"Refresh external dataset pointers: {slugs}")
    if args.push:
        git("push", "origin", args.branch)
        print("Pushed to GitHub.")
    else:
        print("Committed locally. Re-run with --push (or 'git push') to publish.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Mode selector.
    ap.add_argument("--refresh-external", action="store_true",
                    help="REFRESH mode: re-check/re-sync external dataset pointers.")
    ap.add_argument("--check-only", action="store_true",
                    help="Refresh mode: only HTTP-check pointers and report drift; no changes.")
    ap.add_argument("--all", action="store_true",
                    help="Refresh mode: target every external dataset.")

    ap.add_argument("--slug", help="URL-safe id; becomes the folder name (or the target to refresh).")
    ap.add_argument("--name", help="Human-readable name (add mode).")
    ap.add_argument("--data", nargs="+", type=Path,
                    help="Hosted: one or more data files to copy into the dataset.")
    ap.add_argument("--description", help="(add mode)")
    ap.add_argument("--source", default=None, help="Origin URL (required for --external).")
    ap.add_argument("--license", help="(add mode)")
    ap.add_argument("--tags", default="", help="Comma-separated tags.")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--added-by", default=None, help="Email or handle of the admin.")
    ap.add_argument("--push", action="store_true", help="git push after committing.")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--lfs", action="store_true",
                    help="Hosted: force all data files into Git LFS.")
    ap.add_argument("--lfs-threshold-mb", type=float, default=DEFAULT_LFS_THRESHOLD_MB,
                    help=f"Auto-LFS files >= this many MB (default {DEFAULT_LFS_THRESHOLD_MB}).")
    # External (pointer-only) dataset options.
    ap.add_argument("--external", action="store_true",
                    help="Register a pointer to data hosted elsewhere (nothing copied).")
    ap.add_argument("--from-github", metavar="OWNER/REPO",
                    help="External: auto-discover files from this public GitHub repo.")
    ap.add_argument("--github-path", default="",
                    help="External: subpath within the repo to list (default: whole repo).")
    ap.add_argument("--github-ref", default="main", help="External: branch/tag (default main).")
    ap.add_argument("--include-ext", default=".csv,.tsv,.json",
                    help="External: only include files with these extensions (comma-separated; "
                         "empty string = all).")
    args = ap.parse_args()

    if args.refresh_external:
        return refresh_external(args)

    for flag in ("slug", "name", "description", "license"):
        if not getattr(args, flag):
            print(f"Add mode requires --{flag}.", file=sys.stderr)
            return 2

    if not SLUG_RE.match(args.slug):
        print(f"Invalid slug '{args.slug}': use lowercase letters, digits, hyphens.",
              file=sys.stderr)
        return 2

    ds_dir = catalog.DATASETS_DIR / args.slug
    if ds_dir.exists():
        print(f"Dataset '{args.slug}' already exists at {ds_dir.relative_to(catalog.REPO_ROOT)}.",
              file=sys.stderr)
        return 2

    if args.external:
        return add_external(args, ds_dir)

    if not args.data:
        print("Hosted datasets need --data (or pass --external for a pointer).",
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

    threshold_bytes = int(args.lfs_threshold_mb * 1024 * 1024)
    files_meta = []
    for src in args.data:
        dest = data_dir / src.name
        shutil.copy2(src, dest)
        size = dest.stat().st_size
        rows, cols = csv_shape(dest)

        use_lfs = (args.lfs or size >= threshold_bytes
                   or src.suffix.lower() in LFS_EXTENSIONS)
        if use_lfs:
            if not lfs_available():
                shutil.rmtree(ds_dir)
                print(f"'{src.name}' ({size} bytes) needs Git LFS, but git-lfs is not "
                      "installed. Install it (e.g. `brew install git-lfs`) and retry.",
                      file=sys.stderr)
                return 2
            rel = f"datasets/{args.slug}/data/{src.name}"
            ensure_lfs_tracked(rel)

        entry = {"path": f"data/{src.name}", "bytes": size, "sha256": sha256_of(dest)}
        if rows is not None:
            entry["rows"] = rows
            entry["columns"] = cols
        if use_lfs:
            entry["lfs"] = True
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

    return finalize(args, ds_dir)


def add_external(args, ds_dir: Path) -> int:
    """Register an external (pointer-only) dataset. Nothing is copied."""
    if not args.source:
        print("--external requires --source (the repo/page the data lives in).",
              file=sys.stderr)
        return 2

    exts = [e.strip() for e in args.include_ext.split(",") if e.strip()]
    files_meta: list[dict] = []
    if args.from_github:
        try:
            owner, repo = args.from_github.split("/", 1)
        except ValueError:
            print("--from-github must be OWNER/REPO.", file=sys.stderr)
            return 2
        try:
            files_meta = discover_github_files(owner, repo, args.github_ref,
                                               args.github_path, exts)
        except Exception as exc:  # network / API errors
            print(f"GitHub discovery failed: {exc}", file=sys.stderr)
            return 1
        if not files_meta:
            print("No matching files found in the source repo path.", file=sys.stderr)
            return 1
    else:
        print("--external currently requires --from-github OWNER/REPO for discovery.",
              file=sys.stderr)
        return 2

    meta_dir = ds_dir / "metadata"
    meta_dir.mkdir(parents=True)

    metadata = {
        "slug": args.slug,
        "name": args.name,
        "description": args.description,
        "version": args.version,
        "date_added": date.today().isoformat(),
        "added_by": args.added_by,
        "source_type": "external",
        "source": args.source,
        "external_source": {
            "github": args.from_github,
            "path": args.github_path,
            "ref": args.github_ref,
            "include_ext": exts,
        },
        "license": args.license,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "files": files_meta,
    }
    metadata = {k: v for k, v in metadata.items() if v is not None}

    with (meta_dir / "metadata.yaml").open("w") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False, allow_unicode=True)

    print(f"Discovered {len(files_meta)} external file(s) from {args.from_github}.")
    return finalize(args, ds_dir)


def finalize(args, ds_dir: Path) -> int:
    """Validate, regenerate indexes, commit and optionally push. Rolls back on error."""
    try:
        records = catalog.build(validate=True)["datasets"]
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
