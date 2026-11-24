#!/usr/bin/env python3
"""Offline tests for runtime/module-manager.py. No network, no real kernel module."""
import hashlib
import importlib.util
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_bzimage(kernel_release: str) -> bytes:
    """The minimal bytes module_manager.staged_kernel() needs: a real x86
    boot sector layout is much larger, but staged_kernel() only reads the
    'HdrS' signature at 0x202 and the kernel_version string it points to."""
    text = (kernel_release + " ").encode() + b"\x00"
    header = bytearray(0x10000)
    text_offset = 0x300
    header[text_offset:text_offset + len(text)] = text
    header[0x202:0x206] = b"HdrS"
    header[0x20E:0x210] = struct.pack("<H", text_offset - 0x200)
    return bytes(header)


def main() -> int:
    mm = load(PROJECT / "runtime" / "module-manager.py", "module_manager")
    work = Path(tempfile.mkdtemp())
    try:
        # 1. staged_kernel() reads a kernel release out of a synthetic bzImage.
        image = work / "bzimage"
        image.write_bytes(make_bzimage("6.18.58-Unraid"))
        assert mm.staged_kernel(image) == "6.18.58-Unraid"
        print("ok: staged_kernel() parses a bzImage setup header")

        # 2. A bzImage with no HdrS signature is reported as unreadable, not a crash.
        (work / "notabzimage").write_bytes(b"\x00" * 100)
        assert mm.staged_kernel(work / "notabzimage") is None
        print("ok: staged_kernel() returns None for a non-bzImage file")

        # 3. ensure() rejects a kernel name that doesn't look like one.
        try:
            mm.ensure("../../etc/passwd", work, str(work / "modules.json"), 5)
            raise AssertionError("a malicious kernel name was not rejected")
        except mm.ModuleError as error:
            assert error.code == mm.EXIT_ERROR
        print("ok: ensure() rejects a kernel release that fails KERNEL_RE")

        # 4. ensure() reports EXIT_UNSUPPORTED for a kernel absent from the manifest.
        manifest_path = work / "modules.json"
        manifest_path.write_text('{"schema": 1, "modules": {"6.18.58-Unraid": {}}}')
        try:
            mm.ensure("6.19.1-Unraid", work, str(manifest_path), 5)
            raise AssertionError("an unlisted kernel should have failed")
        except mm.ModuleError as error:
            assert error.code == mm.EXIT_UNSUPPORTED, f"expected EXIT_UNSUPPORTED, got {error.code}"
        print("ok: ensure() reports EXIT_UNSUPPORTED for a kernel the manifest doesn't list")

        # 5. A malformed manifest entry (bad hash shape) is rejected clearly.
        manifest_path.write_text(
            '{"schema": 1, "modules": {"6.18.58-Unraid": {"url": "https://example.invalid/x.ko", "sha256": "nothex"}}}')
        try:
            mm.ensure("6.18.58-Unraid", work, str(manifest_path), 5)
            raise AssertionError("a malformed manifest entry was not rejected")
        except mm.ModuleError as error:
            assert error.code == mm.EXIT_ERROR
        print("ok: ensure() rejects a manifest entry with a malformed SHA-256")

        # 6. A manifest that isn't even the right shape is rejected, not crashed on.
        manifest_path.write_text('["not", "a", "manifest"]')
        try:
            mm.load_manifest(str(manifest_path), 5)
            raise AssertionError("a non-dict manifest was not rejected")
        except mm.ModuleError:
            pass
        print("ok: load_manifest() rejects an unsupported manifest shape")

        # 7. quarantine(): a module kernel+digest recorded as quarantined is
        #    reported as such; a different digest for the same kernel is not.
        root = work / "root"
        (root / "quarantine").mkdir(parents=True)
        (root / "quarantine" / "6.18.58-Unraid").write_text("deadbeef" * 8)
        assert mm.quarantined(root, "6.18.58-Unraid", "deadbeef" * 8) is True
        assert mm.quarantined(root, "6.18.58-Unraid", "f" * 64) is False
        assert mm.quarantined(root, "6.19.1-Unraid", "deadbeef" * 8) is False
        print("ok: quarantined() matches by kernel and exact digest only")

        # 8. ensure() refuses a quarantined module instead of silently retrying it.
        digest = hashlib.sha256(b"whatever").hexdigest()
        manifest_path.write_text(
            '{"schema": 1, "modules": {"6.18.58-Unraid": '
            f'{{"url": "https://example.invalid/x.ko", "sha256": "{digest}"}}}}}}')
        (root / "quarantine" / "6.18.58-Unraid").write_text(digest)
        try:
            mm.ensure("6.18.58-Unraid", root, str(manifest_path), 5)
            raise AssertionError("a quarantined module should not have been retried")
        except mm.ModuleError as error:
            assert error.code == mm.EXIT_QUARANTINED
        print("ok: ensure() refuses a module that is quarantined after a failed boot")

        # 9. prefetch() is a no-op (not an error) when no update is pending.
        running = "6.18.58-Unraid"
        image.write_bytes(make_bzimage(running))
        kernel, message = mm.prefetch(running, image, root, str(manifest_path), 5)
        assert kernel == "" and "no Unraid update" in message
        print("ok: prefetch() is a quiet no-op when the staged kernel matches the running one")

        # 10. module_matches_kernel() / vermagic() never raise when modinfo
        #     is missing or the file isn't really a module -- just report "no match".
        fake_bin = work / "nope.ko"
        fake_bin.write_bytes(b"not a module")
        assert mm.vermagic(fake_bin) is None or isinstance(mm.vermagic(fake_bin), str)
        assert mm.module_matches_kernel(fake_bin, "6.18.58-Unraid") is False
        print("ok: module_matches_kernel() degrades to False instead of raising on a bad file")

    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("Module-manager offline tests passed (no network, no real module).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
