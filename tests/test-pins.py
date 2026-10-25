#!/usr/bin/env python3
"""Pinned runtime downloads must be reachable from HEAD and match their SHA-256.

A commit that is not reachable from any branch can be garbage-collected by
GitHub, which would make fresh installs fail. Needs a full (non-shallow) clone.
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

project = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, check=check)


if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
    print("note: not a git checkout; pinned-commit checks skipped")
    sys.exit(0)
if git("rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
    print("note: shallow clone; pinned-commit checks skipped")
    sys.exit(0)

text = (project / "RTX-3090-Unlock.plg").read_text()
pins = re.findall(r"<URL>" + re.escape(RAW) + r"([0-9a-f]{40})/([^<]+)</URL>\s*<SHA256>([0-9a-f]{64})</SHA256>", text)
assert len(pins) == 3, f"expected 3 pinned runtime files, found {len(pins)}"
for commit, path, digest in pins:
    if git("merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode != 0:
        sys.exit(f"{path}: pinned commit {commit} is not reachable from HEAD")
    blob = git("show", f"{commit}:{path}").stdout
    if hashlib.sha256(blob).hexdigest() != digest:
        sys.exit(f"{path}: SHA256 does not match {commit}")
    if (project / path).read_bytes() != blob:
        print(f"note: {path} changed since {commit[:12]}; run scripts/pin-runtime.py after merging")
print("Pinned runtime downloads verified.")
