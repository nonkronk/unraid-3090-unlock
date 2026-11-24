#!/usr/bin/env python3
"""Find, download and verify the gpu_unlock module for an Unraid kernel.

  ensure   Make sure payload/<kernel>/gpu_unlock.ko exists for a kernel
           (default: the running one). A staged or bundled module is kept; a
           missing one is fetched from the release manifest and verified.
  staged   Print the kernel release of the Unraid image on the flash
           (/boot/bzimage). After an Unraid update this differs from `uname -r`
           until the next reboot.
  prefetch Run `ensure` for the staged kernel when an update is waiting for a
           reboot, so the first boot on the new kernel already has its module.

Exit codes: 0 ready, 3 kernel not in the manifest, 4 network or verification
failure, 5 module quarantined after a failed boot, 1 other error.
Only the standard library is used. Every module must match the SHA-256 listed
in the manifest and report the exact kernel in its vermagic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_ROOT = Path("/boot/config/plugins/RTX-3090-Unlock")
DEFAULT_MANIFEST = "https://github.com/nonkronk/unraid-3090-unlock/releases/download/modules/modules.json"
KERNEL_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?-Unraid$")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MODULE_BYTES = 8 * 1024 * 1024
USER_AGENT = "RTX-3090-Unlock/module-manager"

EXIT_OK, EXIT_ERROR, EXIT_UNSUPPORTED, EXIT_NETWORK, EXIT_QUARANTINED = 0, 1, 3, 4, 5


class ModuleError(Exception):
    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


def log(message: str) -> None:
    print(f"RTX-3090-Unlock: {message}", file=sys.stderr, flush=True)


def running_kernel() -> str:
    return os.uname().release


def staged_kernel(image: Path) -> str | None:
    """Kernel release of an x86 bzImage, read from its setup header (no external tools)."""
    try:
        with image.open("rb") as stream:
            head = stream.read(0x10000)
    except OSError:
        return None
    if len(head) < 0x210 or head[0x202:0x206] != b"HdrS":
        return None
    offset = int.from_bytes(head[0x20E:0x210], "little") + 0x200
    if offset >= len(head):
        return None
    text = head[offset:offset + 256].split(b"\0", 1)[0].decode("ascii", "replace")
    release = text.split(" ", 1)[0]
    return release if KERNEL_RE.match(release) else None


def http_get(url: str, limit: int, timeout: int) -> bytes:
    if not url.startswith("https://"):
        raise ModuleError("refusing a non-HTTPS URL", EXIT_NETWORK)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced
            if not response.url.startswith("https://"):
                raise ModuleError("refusing a non-HTTPS redirect", EXIT_NETWORK)
            data = response.read(limit + 1)
    except (OSError, ValueError) as error:
        raise ModuleError(f"cannot download {url}: {error}", EXIT_NETWORK) from error
    if len(data) > limit:
        raise ModuleError(f"{url} exceeds the {limit} byte limit", EXIT_NETWORK)
    return data


def load_manifest(location: str, timeout: int) -> dict:
    if location.startswith("https://"):
        raw = http_get(location, MAX_MANIFEST_BYTES, timeout)
    else:
        path = Path(location)
        try:
            raw = path.read_bytes()[:MAX_MANIFEST_BYTES + 1]
        except OSError as error:
            raise ModuleError(f"cannot read manifest {location}: {error}", EXIT_NETWORK) from error
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ModuleError("manifest is too large", EXIT_ERROR)
    try:
        manifest = json.loads(raw)
    except ValueError as error:
        raise ModuleError(f"manifest is not valid JSON: {error}", EXIT_NETWORK) from error
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or not isinstance(manifest.get("modules"), dict):
        raise ModuleError("manifest has an unsupported format", EXIT_ERROR)
    return manifest


def vermagic(module: Path) -> str | None:
    try:
        result = subprocess.run(["modinfo", "-F", "vermagic", str(module)],
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def module_matches_kernel(module: Path, kernel: str) -> bool:
    found = vermagic(module)
    return bool(found) and found.split(" ", 1)[0] == kernel


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def quarantined(root: Path, kernel: str, digest: str) -> bool:
    marker = root / "quarantine" / kernel
    try:
        return marker.read_text().strip() == digest
    except OSError:
        return False


def write_atomic(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".gpu-unlock-", delete=False) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        name = Path(temp.name)
    try:
        os.replace(name, destination)
    finally:
        name.unlink(missing_ok=True)


def ensure(kernel: str, root: Path, manifest_location: str, timeout: int) -> str:
    """Return a short status string, or raise ModuleError."""
    if not KERNEL_RE.match(kernel):
        raise ModuleError(f"unsupported kernel name: {kernel}")
    module = root / "payload" / kernel / "gpu_unlock.ko"
    if module.is_file() and module.stat().st_size > 0:
        if module_matches_kernel(module, kernel):
            digest = file_sha256(module)
            if quarantined(root, kernel, digest):
                raise ModuleError(
                    f"the {kernel} module was disabled after a boot that did not finish; "
                    f"delete {root}/quarantine/{kernel} to try it again", EXIT_QUARANTINED)
            return f"module for {kernel} already present"
        log(f"module for {kernel} is present but its vermagic does not match; looking for a replacement")
    manifest = load_manifest(manifest_location, timeout)
    entry = manifest["modules"].get(kernel)
    if not isinstance(entry, dict):
        known = ", ".join(sorted(manifest["modules"])) or "none"
        raise ModuleError(f"no module is published for kernel {kernel} yet (published: {known})", EXIT_UNSUPPORTED)
    url, digest = entry.get("url"), entry.get("sha256")
    if not isinstance(url, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ModuleError(f"manifest entry for {kernel} is malformed")
    if quarantined(root, kernel, digest):
        raise ModuleError(
            f"the {kernel} module was disabled after a boot that did not finish; "
            f"delete {root}/quarantine/{kernel} to try it again", EXIT_QUARANTINED)
    data = http_get(url, MAX_MODULE_BYTES, timeout)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ModuleError(f"downloaded module for {kernel} does not match the manifest SHA-256", EXIT_NETWORK)
    staging = root / "payload" / kernel
    staging.mkdir(parents=True, exist_ok=True)
    candidate = staging / ".gpu_unlock.ko.new"
    try:
        write_atomic(candidate, data)
        if not module_matches_kernel(candidate, kernel):
            raise ModuleError(f"downloaded module does not report kernel {kernel} in its vermagic")
        os.replace(candidate, module)
    finally:
        candidate.unlink(missing_ok=True)
    return f"downloaded module for {kernel} ({entry.get('status', 'unknown')})"


def prefetch(running: str, image: Path, root: Path, manifest_location: str, timeout: int) -> tuple[str, str]:
    """Return (kernel_or_empty, message). Raises ModuleError when an update is pending but unusable."""
    staged = staged_kernel(image)
    if staged is None:
        return "", "no staged Unraid kernel found"
    if staged == running:
        return "", f"no Unraid update is waiting for a reboot (kernel {running})"
    return staged, ensure(staged, root, manifest_location, timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", default=os.environ.get("GPU_UNLOCK_MANIFEST", DEFAULT_MANIFEST),
                        help="https URL or local path of modules.json")
    parser.add_argument("--timeout", type=int, default=30)
    sub = parser.add_subparsers(dest="command", required=True)
    ensure_parser = sub.add_parser("ensure")
    ensure_parser.add_argument("--kernel", default=None)
    staged_parser = sub.add_parser("staged")
    staged_parser.add_argument("--image", type=Path, default=Path("/boot/bzimage"))
    prefetch_parser = sub.add_parser("prefetch")
    prefetch_parser.add_argument("--image", type=Path, default=Path("/boot/bzimage"))
    prefetch_parser.add_argument("--running", default=None)
    args = parser.parse_args()
    try:
        if args.command == "ensure":
            print(ensure(args.kernel or running_kernel(), args.root, args.manifest, args.timeout))
        elif args.command == "staged":
            kernel = staged_kernel(args.image)
            if kernel is None:
                raise ModuleError(f"cannot read a kernel release from {args.image}")
            print(kernel)
        else:
            kernel, message = prefetch(args.running or running_kernel(), args.image, args.root,
                                       args.manifest, args.timeout)
            print(f"{kernel or '-'}\t{message}")
    except ModuleError as error:
        print(f"RTX-3090-Unlock: {error}", file=sys.stderr)
        return error.code
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
