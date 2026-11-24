#!/usr/bin/env python3
"""Offline tests for runtime/fetch-firmware.py.

No network access: builds a tiny synthetic NVIDIA-style .run installer (and a
tiny synthetic distro package) entirely in memory, against a throwaway set of
pinned hashes, and checks that fetch-firmware.py extracts and verifies the
right bytes from each -- and correctly rejects an HTML placeholder page like
the one archive.cachyos.org now serves for the removed file.

Requires the `zstd` CLI on PATH (present on Unraid and in the project's CI
image). Skips itself with a clear message if it is not installed locally.
"""
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / "runtime"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zstd_compress(data: bytes) -> bytes:
    return subprocess.run(["zstd", "-q", "-c"], input=data, stdout=subprocess.PIPE, check=True).stdout


def make_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def make_run_file(members: dict[str, bytes], header_prefix: str = "#!/bin/sh\n") -> bytes:
    """A minimal makeself-style installer: N header lines, then a zstd tar.

    Matches `tail -n +$skip` semantics exactly (as the real installer and
    payload_offset() both use): line `skip` is the first line of the payload,
    so the header has exactly `skip - 1` complete, newline-terminated lines
    before it.
    """
    header_lines = [header_prefix.rstrip("\n"), "skip=__SKIP__"] + [f"# filler line {i}" for i in range(5)]
    skip = len(header_lines) + 1
    header = ("\n".join(header_lines) + "\n").replace("__SKIP__", str(skip))
    return header.encode() + zstd_compress(make_tar(members))


def main() -> int:
    if shutil.which("zstd") is None:
        print("note: zstd not installed; skipping fetch-firmware.py tests")
        return 0

    fetch_firmware = load(RUNTIME / "fetch-firmware.py", "fetch_firmware")

    gsp_bytes = b"fake-gsp-firmware-bytes-for-testing" * 100
    license_bytes = b"FAKE NVIDIA LICENSE TEXT FOR TESTING\n"
    gsp_sha = sha256(gsp_bytes)
    license_sha = sha256(license_bytes)

    work = Path(tempfile.mkdtemp())
    try:
        upstream_dir = work / "upstream"
        upstream_dir.mkdir()
        (upstream_dir / "generate_v67.py").write_text(f'''
GSP_SHA256 = "{gsp_sha}"
PACKAGE_SHA256 = "unused-in-these-tests"
PAYLOAD_SHA256 = ""
FIRMWARE_PREFIX = "usr/lib/firmware/nvidia/610.43.03/"

def build_payload():
    return b""

def extract_member(path, name):
    import tarfile
    with tarfile.open(path, mode="r:*") as archive:
        return archive.extractfile(name).read()
''')
        # PAYLOAD_SHA256 must match build_payload()'s actual (empty) output.
        (upstream_dir / "generate_v67.py").write_text(
            (upstream_dir / "generate_v67.py").read_text().replace(
                'PAYLOAD_SHA256 = ""', f'PAYLOAD_SHA256 = "{sha256(b"")}"'))
        manifest = {
            "source_artifacts": [
                {}, {},
                {"notice": {"path": "usr/share/licenses/nvidia-utils/LICENSE", "sha256": license_sha}},
            ]
        }
        (upstream_dir / "artifacts-610.43.03.json").write_text(json.dumps(manifest))
        upstream = fetch_firmware.load_upstream(upstream_dir)
        notice = manifest["source_artifacts"][2]["notice"]
        license_hashes = {license_sha}

        # 1. A well-formed installer: extraction and verification succeed.
        run_bytes = make_run_file({
            "./firmware/gsp_ga10x.bin": gsp_bytes,
            "./LICENSE": license_bytes,
        })
        reader = io.BytesIO(run_bytes)
        gsp, lic = fetch_firmware.from_run(reader.read, upstream, license_hashes, deadline=1e18)
        assert gsp == gsp_bytes, "from_run returned the wrong GSP bytes"
        assert lic == license_bytes, "from_run returned the wrong license bytes"
        print("ok: from_run extracts and verifies a well-formed installer")

        # 2. The installer's firmware member is tampered with: must be rejected.
        tampered = make_run_file({
            "./firmware/gsp_ga10x.bin": gsp_bytes + b"\x00",
            "./LICENSE": license_bytes,
        })
        reader = io.BytesIO(tampered)
        try:
            fetch_firmware.from_run(reader.read, upstream, license_hashes, deadline=1e18)
            raise AssertionError("tampered GSP firmware was not rejected")
        except fetch_firmware.SourceError:
            pass
        print("ok: from_run rejects a firmware member that doesn't match the pinned hash")

        # 3. An HTML placeholder page (what archive.cachyos.org serves for a
        #    removed file) must never be mistaken for a real installer.
        html = b"<html><head><title>Welcome to our server</title></head></html>"
        reader = io.BytesIO(html)
        try:
            fetch_firmware.from_run(reader.read, upstream, license_hashes, deadline=1e18)
            raise AssertionError("an HTML placeholder page was accepted as an installer")
        except fetch_firmware.SourceError:
            pass
        print("ok: from_run rejects an HTML placeholder page (the actual Nov 2026 failure mode)")

        # 4. A package built for a different arch/distro than the one this
        #    project originally pinned: member hashes still verify (the whole
        #    package hash is deliberately NOT required -- see from_package).
        package_path = work / "other-distro-nvidia-utils.pkg.tar"
        package_path.write_bytes(make_tar({
            "usr/lib/firmware/nvidia/610.43.03/gsp_ga10x.bin": gsp_bytes,
            "usr/share/licenses/nvidia-utils/LICENSE": license_bytes,
            ".PKGINFO": b"pkgver = 610.43.03-1\n",
        }))
        gsp2, lic2 = fetch_firmware.from_package(package_path, upstream, notice)
        assert gsp2 == gsp_bytes and lic2 == license_bytes
        print("ok: from_package verifies a differently-built package by member hash alone")

        # 5. Same package, but the firmware member was swapped: must be rejected.
        bad_package_path = work / "bad.pkg.tar"
        bad_package_path.write_bytes(make_tar({
            "usr/lib/firmware/nvidia/610.43.03/gsp_ga10x.bin": b"not the right firmware at all",
            "usr/share/licenses/nvidia-utils/LICENSE": license_bytes,
        }))
        try:
            fetch_firmware.from_package(bad_package_path, upstream, notice)
            raise AssertionError("a package with the wrong firmware bytes was not rejected")
        except fetch_firmware.SourceError:
            pass
        print("ok: from_package rejects a package whose firmware member doesn't match")

        # 6. obtain() must try every source and report every failure when all
        #    of them fail, without raising anything other than SourceError.
        # No network in this test: point every remote source at nothing.
        fetch_firmware.RUN_URLS = ()
        fetch_firmware.PKG_URLS = ()
        try:
            fetch_firmware.obtain(upstream, notice, license_hashes, None, work, timeout=1, max_seconds=1)
            raise AssertionError("obtain() with zero sources should have raised SourceError")
        except fetch_firmware.SourceError as error:
            assert "no firmware source passed verification" in str(error)
        print("ok: obtain() raises SourceError (not a crash) when nothing is reachable")

        # 7. A staged local file is preferred and used without touching the
        #    network at all.
        local_dir = work / "staged"
        local_dir.mkdir()
        (local_dir / "NVIDIA-Linux-x86_64-610.43.03.run").write_bytes(run_bytes)
        gsp3, lic3, label = fetch_firmware.obtain(
            upstream, notice, license_hashes, local_dir, work, timeout=1, max_seconds=30)
        assert gsp3 == gsp_bytes and lic3 == license_bytes
        assert "staged file" in label
        print("ok: obtain() prefers and uses a staged local file over any remote source")

    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("Firmware-fetch offline tests passed (no network, no privileges).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
