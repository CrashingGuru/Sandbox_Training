#!/usr/bin/env python3
"""Admin tool: add an agent to the catalog and (optionally) push to GitHub.

Mirrors add_notebook.py. Transactional (validate -> regenerate -> commit):
  1. create agents/<slug>/{agent,metadata}/ and copy the definition file(s) in
  2. compute bytes and sha256 for each file
  3. write metadata.yaml (framework, model, tools, dataset/notebook links, guardrails)
  4. validate against schema/agent.metadata.schema.json
  5. regenerate AGENTS.md, agents.json and the per-agent README
  6. git add + commit  (and git push with --push)

Example:
    python scripts/add_agent.py \\
        --slug telecom-rag-agent \\
        --name "Telecom RAG Agent" \\
        --agent ./agent.py \\
        --framework "custom (retrieve/answer/refuse)" \\
        --model "flan-t5-base + all-MiniLM-L6-v2" \\
        --tools retrieve,answer,refuse \\
        --dataset teleqna --notebook telecom-rag-agent \\
        --guardrails "Refuses when retrieval confidence < 0.25; logs every tool call." \\
        --description "..." --tags agentic,rag --license "..." --push
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
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--agent", required=True, nargs="+", type=Path,
                    help="Agent definition file(s) to copy (e.g. agent.py).")
    ap.add_argument("--description", required=True)
    ap.add_argument("--framework", required=True,
                    help="e.g. 'custom (retrieve/answer/refuse)', 'LangChain', 'MCP'.")
    ap.add_argument("--model", default="")
    ap.add_argument("--tools", default="", help="Comma-separated tool names.")
    ap.add_argument("--guardrails", default="")
    ap.add_argument("--dataset", default="", help="Linked dataset slug (optional).")
    ap.add_argument("--notebook", default="", help="Linked notebook slug (optional).")
    ap.add_argument("--tags", default="")
    ap.add_argument("--license", default="")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--added-by", default=None)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    if not SLUG_RE.match(args.slug):
        print(f"Invalid slug '{args.slug}': use lowercase letters, digits, hyphens.",
              file=sys.stderr)
        return 2

    ag_dir = catalog.AGENTS_DIR / args.slug
    if ag_dir.exists():
        print(f"Agent '{args.slug}' already exists.", file=sys.stderr)
        return 2
    for src in args.agent:
        if not src.is_file():
            print(f"Agent file not found: {src}", file=sys.stderr)
            return 2

    # Soft checks on links.
    if args.dataset and not (catalog.DATASETS_DIR / args.dataset).exists():
        print(f"Warning: dataset '{args.dataset}' not found; link recorded anyway.",
              file=sys.stderr)
    if args.notebook and not (catalog.NOTEBOOKS_DIR / args.notebook).exists():
        print(f"Warning: notebook '{args.notebook}' not found; link recorded anyway.",
              file=sys.stderr)

    file_dir = ag_dir / "agent"
    meta_dir = ag_dir / "metadata"
    file_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    files_meta = []
    for src in args.agent:
        dest = file_dir / src.name
        shutil.copy2(src, dest)
        entry = {"path": f"agent/{src.name}", "bytes": dest.stat().st_size,
                 "sha256": sha256_of(dest)}
        if src.suffix:
            entry["format"] = src.suffix.lstrip(".")
        files_meta.append(entry)

    metadata = {
        "slug": args.slug,
        "name": args.name,
        "description": args.description,
        "version": args.version,
        "date_added": date.today().isoformat(),
        "added_by": args.added_by,
        "framework": args.framework,
        "model": args.model,
        "tools": _split(args.tools),
        "guardrails": args.guardrails,
        "dataset": args.dataset,
        "notebook": args.notebook,
        "tags": _split(args.tags),
        "license": args.license,
        "files": files_meta,
    }
    if args.added_by is None:
        metadata.pop("added_by")

    with (meta_dir / "metadata.yaml").open("w") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False, allow_unicode=True)

    try:
        records = catalog.build(validate=True)["agents"]
    except ValueError as exc:
        shutil.rmtree(ag_dir)
        print(exc, file=sys.stderr)
        print("Rolled back: no files committed.", file=sys.stderr)
        return 1

    git("add", "-A")
    git("commit", "-m", f"Add agent: {args.name} ({args.slug})")
    if args.push:
        git("push", "origin", args.branch)
        print("Pushed to GitHub.")
    else:
        print("Committed locally. Re-run with --push (or 'git push') to publish.")

    print(f"Catalog now has {len(records)} agent(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
