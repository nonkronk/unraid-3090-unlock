#!/usr/bin/env python3
"""Pin RTX-3090-Unlock.plg runtime downloads to a commit and record SHA-256s.

Unraid's plugin manager never replaces a file that already exists on the flash
unless the <FILE> carries a SHA256 that no longer matches. Without hashes, a
plugin update silently keeps running the old runtime scripts, and nothing
verifies what was downloaded. Run this after any runtime/ change is merged:

    python3 scripts/pin-runtime.py COMMIT [--module PATH_TO_RELEASED_KO]

COMMIT must be reachable from main (tests/test-static.sh enforces this), so
GitHub never garbage-collects the pinned objects.
"""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PLG = PROJECT / "RTX-3090-Unlock.plg"
RAW = "https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/"
FILE_RE = re.compile(r'(<FILE Name="[^"]+">\s*)(<URL>([^<]+)</URL>)(\s*<SHA256>[0-9a-f]{64}</SHA256>)?(\s*</FILE>)')


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(PROJECT), *args], check=True, capture_output=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit")
    parser.add_argument("--module", type=Path, help="released gpu_unlock .ko whose hash to record")
    args = parser.parse_args()
    commit = git("rev-parse", "--verify", args.commit + "^{commit}").decode().strip()

    def pin(match: re.Match) -> str:
        head, url, tail = match.group(1), match.group(3), match.group(5)
        if url.startswith(RAW):
            path = url.split("/", 6)[6]
            url = RAW + commit + "/" + path
            digest = hashlib.sha256(git("show", f"{commit}:{path}")).hexdigest()
        elif url.endswith(".ko"):
            if args.module:
                digest = hashlib.sha256(args.module.read_bytes()).hexdigest()
            elif match.group(4):
                return match.group(0)
            else:
                raise SystemExit(f"--module is required to hash {url}")
        else:
            raise SystemExit(f"unrecognised download: {url}")
        return f"{head}<URL>{url}</URL>\n    <SHA256>{digest}</SHA256>{tail}"

    text = PLG.read_text()
    updated, count = FILE_RE.subn(pin, text)
    if count != 4:
        print(f"expected 4 downloads, found {count}", file=sys.stderr)
        return 1
    PLG.write_text(updated)
    print(f"Pinned runtime downloads to {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
