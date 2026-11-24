#!/usr/bin/env python3
"""Fetch the pinned NVIDIA 610.43.03 inputs from any source that passes verification.

Two subcommands, both stdlib-only:

  firmware  Get gsp_ga10x.bin and the NVIDIA license, check them against the
            SHA-256 values pinned by the upstream manifest, then build the V67
            image with upstream's generator. Sources are tried in order:
              1. a file you staged in <plugin>/firmware-src/
              2. NVIDIA's own installer (.run), streamed and never executed
              3. the CachyOS package (kept as a last resort; the file may be gone)
  source    Download the NVIDIA open kernel module source archive (hash-checked).

Trust comes from the SHA-256 of the extracted bytes, never from an HTTP status.
A mirror that answers 200 with an HTML page (as archive.cachyos.org does for a
removed file) simply fails verification and the next source is tried.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "610.43.03"
RUN_NAME = f"NVIDIA-Linux-x86_64-{VERSION}.run"
RUN_URLS = (
    f"https://download.nvidia.com/XFree86/Linux-x86_64/{VERSION}/{RUN_NAME}",
    f"https://us.download.nvidia.com/XFree86/Linux-x86_64/{VERSION}/{RUN_NAME}",
)
PKG_NAME = f"nvidia-utils-{VERSION}-1-x86_64_v3.pkg.tar.zst"
PKG_URLS = (f"https://archive.cachyos.org/archive/cachyos-v3/{PKG_NAME}",)
RUN_GSP_MEMBER = "firmware/gsp_ga10x.bin"
RUN_LICENSE_MEMBER = "LICENSE"
MAX_MEMBER_BYTES = 128 * 1024 * 1024
USER_AGENT = "RTX-3090-Unlock/firmware-fetch"


class SourceError(Exception):
    """One source could not provide verified firmware."""


def log(message: str) -> None:
    print(f"RTX-3090-Unlock: {message}", file=sys.stderr, flush=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_upstream(directory: Path):
    """Import upstream's generate_v67.py (pinned commit, hash-checked by the caller)."""
    spec = importlib.util.spec_from_file_location("generate_v67", directory / "generate_v67.py")
    if spec is None or spec.loader is None:
        raise SourceError("cannot load upstream generate_v67.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- NVIDIA .run installer -------------------------------------------------

def payload_offset(buffer: bytes) -> int | None:
    """Byte offset of the compressed tar inside a makeself-style NVIDIA .run file.

    The header names the payload start as a line number (skip=N). Returns None
    when the buffer does not yet contain that many lines.
    """
    if not buffer.startswith(b"#!/bin/sh"):
        raise SourceError("not an NVIDIA .run installer (unexpected first line)")
    match = re.search(rb"^skip=(\d+)$", buffer[:8192], re.M)
    if not match:
        raise SourceError("installer header has no skip= line")
    position = 0
    for _ in range(int(match.group(1)) - 1):
        newline = buffer.find(b"\n", position)
        if newline < 0:
            return None
        position = newline + 1
    return position


def members_from_run(read, wanted: set[str], deadline: float, progress=None) -> dict[str, bytes]:
    """Stream-decode an NVIDIA .run payload (zstd tar) and return the wanted members.

    `read(n)` returns bytes. The installer is never executed or written to disk.
    """
    buffer = b""
    offset = None
    while offset is None:
        chunk = read(1 << 20)
        if not chunk:
            raise SourceError("installer ended inside its header")
        buffer += chunk
        offset = payload_offset(buffer)
        if offset is None and len(buffer) > 8 * 1024 * 1024:
            raise SourceError("installer header is unexpectedly large")

    try:
        decoder = subprocess.Popen(
            ["zstd", "-dc", "--long=31"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise SourceError(f"cannot run zstd: {error}") from error
    failures: list[Exception] = []

    def feed() -> None:
        try:
            data, total = buffer[offset:], len(buffer)
            while True:
                if data:
                    decoder.stdin.write(data)
                if time.monotonic() > deadline:
                    raise SourceError("download time limit reached")
                data = read(1 << 20)
                if not data:
                    break
                total += len(data)
                if progress:
                    progress(total)
        except (BrokenPipeError, ValueError):
            pass  # the reader stopped early because it found everything it needs
        except Exception as error:  # noqa: BLE001 - reported to the caller below
            failures.append(error)
        finally:
            try:
                decoder.stdin.close()
            except OSError:
                pass

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    found: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=decoder.stdout, mode="r|") as archive:
            for member in archive:
                name = member.name[2:] if member.name.startswith("./") else member.name
                if name not in wanted or not member.isfile():
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    raise SourceError(f"installer member too large: {name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise SourceError(f"cannot read installer member: {name}")
                found[name] = stream.read()
                if len(found) == len(wanted):
                    break
    except (tarfile.TarError, OSError, EOFError) as error:
        if failures:
            raise failures[0] from error
        raise SourceError(f"installer payload unreadable: {error}") from error
    finally:
        if decoder.poll() is None:
            decoder.kill()
        decoder.wait()
        feeder.join(timeout=10)
    if failures:
        raise failures[0]
    missing = wanted - set(found)
    if missing:
        raise SourceError("installer does not contain: " + ", ".join(sorted(missing)))
    return found


def open_url(url: str, timeout: int):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https only, see below
    if not response.url.startswith("https://"):
        response.close()
        raise SourceError("refusing a non-HTTPS redirect")
    return response


def from_run(read, upstream, license_hashes: set[str], deadline: float, progress=None):
    members = members_from_run(read, {RUN_GSP_MEMBER, RUN_LICENSE_MEMBER}, deadline, progress)
    gsp, license_text = members[RUN_GSP_MEMBER], members[RUN_LICENSE_MEMBER]
    if sha256(gsp) != upstream.GSP_SHA256:
        raise SourceError("GSP firmware in the installer does not match the pinned SHA-256")
    if sha256(license_text) not in license_hashes:
        raise SourceError("license in the installer does not match a pinned SHA-256")
    return gsp, license_text


# --- CachyOS package (legacy) ---------------------------------------------

def from_package(path: Path, upstream, manifest_notice: dict):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != upstream.PACKAGE_SHA256:
        raise SourceError("package does not match the pinned SHA-256 (the mirror may no longer host it)")
    gsp = upstream.extract_member(path, upstream.FIRMWARE_PREFIX + "gsp_ga10x.bin")
    if sha256(gsp) != upstream.GSP_SHA256:
        raise SourceError("GSP firmware in the package does not match the pinned SHA-256")
    license_text = upstream.extract_member(path, manifest_notice["path"])
    if sha256(license_text) != manifest_notice["sha256"]:
        raise SourceError("license in the package does not match the pinned SHA-256")
    return gsp, license_text


def download_to(url: str, destination: Path, timeout: int, deadline: float, limit: int) -> None:
    response = open_url(url, timeout)
    try:
        total = 0
        with destination.open("wb") as out:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise SourceError("download exceeds the size limit")
                if time.monotonic() > deadline:
                    raise SourceError("download time limit reached")
                out.write(block)
    finally:
        response.close()


# --- Orchestration ---------------------------------------------------------

def obtain(upstream, notice: dict, license_hashes: set[str], local_dir: Path | None,
           work_dir: Path, timeout: int, max_seconds: int):
    """Return (gsp, license, description of the source used). Raises SourceError listing every failure."""
    deadline = time.monotonic() + max_seconds
    problems: list[str] = []
    attempts = []

    def progress_factory():
        state = {"next": 50 * 1024 * 1024}

        def progress(total: int) -> None:
            if total >= state["next"]:
                log(f"downloaded {total // (1024 * 1024)} MiB of the NVIDIA installer")
                state["next"] += 50 * 1024 * 1024
        return progress

    if local_dir and local_dir.is_dir():
        for path in sorted(local_dir.glob("NVIDIA-Linux-x86_64-*.run")):
            def run_local(path=path):
                with path.open("rb") as stream:
                    return from_run(stream.read, upstream, license_hashes, deadline)
            attempts.append((f"staged file {path.name}", run_local))
        for path in sorted(local_dir.glob("nvidia-utils-*.pkg.tar.zst")):
            attempts.append((f"staged file {path.name}",
                             lambda path=path: from_package(path, upstream, notice)))

    for url in RUN_URLS:
        def run_remote(url=url):
            response = open_url(url, timeout)
            try:
                return from_run(response.read, upstream, license_hashes, deadline, progress_factory())
            finally:
                response.close()
        attempts.append((url, run_remote))

    for url in PKG_URLS:
        def package_remote(url=url):
            target = work_dir / PKG_NAME
            download_to(url, target, timeout, deadline, 1024 * 1024 * 1024)
            try:
                return from_package(target, upstream, notice)
            finally:
                target.unlink(missing_ok=True)
        attempts.append((url, package_remote))

    for label, attempt in attempts:
        log(f"trying {label}")
        try:
            gsp, license_text = attempt()
        except (SourceError, OSError, ValueError) as error:
            problems.append(f"{label}: {error}")
            log(f"failed: {error}")
            continue
        return gsp, license_text, label
    raise SourceError("no firmware source passed verification:\n  " + "\n  ".join(problems))


def command_firmware(args: argparse.Namespace) -> int:
    upstream = load_upstream(args.upstream)
    import json
    manifest = json.loads((args.upstream / "artifacts-610.43.03.json").read_text())
    notice = manifest["source_artifacts"][2]["notice"]
    license_hashes = {notice["sha256"], *args.extra_license_sha256}
    args.work.mkdir(parents=True, exist_ok=True)
    try:
        gsp, license_text, label = obtain(
            upstream, notice, license_hashes, args.local, args.work, args.timeout, args.max_seconds)
        payload = upstream.build_payload()
        if sha256(payload) != upstream.PAYLOAD_SHA256:
            raise SourceError("generated V67 image differs from its pinned SHA-256")
    except SourceError as error:
        print(f"RTX-3090-Unlock: firmware unavailable: {error}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gsp_ga10x.bin").write_bytes(gsp)
    (args.out / "v67-ga102-610.43.03.bin").write_bytes(payload)
    (args.out / "NVIDIA-LICENSE").write_bytes(license_text)
    log(f"firmware verified from {label}")
    return 0


def command_source(args: argparse.Namespace) -> int:
    spec = importlib.util.spec_from_file_location("fetch_artifacts", args.upstream / "fetch_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import json
    manifest = json.loads((args.upstream / "artifacts-610.43.03.json").read_text())
    entry = module.inputs(manifest)[0]
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            print(module.fetch(entry, args.out))
            return 0
        except (OSError, ValueError) as error:
            last = error
            log(f"source archive attempt {attempt} failed: {error}")
            time.sleep(2 ** attempt)
    print(f"RTX-3090-Unlock: NVIDIA source archive unavailable: {last}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    firmware = sub.add_parser("firmware")
    firmware.add_argument("--upstream", type=Path, required=True, help="directory with the pinned upstream scripts")
    firmware.add_argument("--out", type=Path, required=True)
    firmware.add_argument("--work", type=Path, required=True)
    firmware.add_argument("--local", type=Path, help="directory with a staged .run or package")
    firmware.add_argument("--timeout", type=int, default=60, help="seconds per network read")
    firmware.add_argument("--max-seconds", type=int, default=1800, help="overall download limit")
    firmware.add_argument("--extra-license-sha256", action="append", default=[],
                          help="additional accepted SHA-256 of the NVIDIA license text")
    firmware.set_defaults(handler=command_firmware)
    source = sub.add_parser("source")
    source.add_argument("--upstream", type=Path, required=True)
    source.add_argument("--out", type=Path, required=True)
    source.set_defaults(handler=command_source)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
