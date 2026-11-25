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

        # 9. ensure() must also refuse an EXISTING, vermagic-matching module
        #    if it is quarantined -- not just a module it would otherwise
        #    fetch fresh. Before this fix, a module already staged on disk
        #    short-circuited straight to "already present" without ever
        #    consulting the quarantine file, so a quarantined module that
        #    hung one boot would be reloaded (and could hang again) on
        #    every boot after the one that quarantined it.
        root2 = work / "root2"
        module_path = root2 / "payload" / "6.18.58-Unraid" / "gpu_unlock.ko"
        module_path.parent.mkdir(parents=True)
        module_path.write_bytes(b"pretend module bytes; no real modinfo in this sandbox")
        existing_digest = mm.file_sha256(module_path)
        (root2 / "quarantine").mkdir()
        (root2 / "quarantine" / "6.18.58-Unraid").write_text(existing_digest)
        original_matches = mm.module_matches_kernel
        mm.module_matches_kernel = lambda path, kernel: True  # stand in for a real vermagic match
        try:
            try:
                mm.ensure("6.18.58-Unraid", root2, str(manifest_path), 5)
                raise AssertionError("an existing quarantined module should not have been accepted")
            except mm.ModuleError as error:
                assert error.code == mm.EXIT_QUARANTINED, f"expected EXIT_QUARANTINED, got {error.code}"
        finally:
            mm.module_matches_kernel = original_matches
        print("ok: ensure() refuses an existing, vermagic-matching module that is quarantined")

        # 9b. ensure()'s full fetch-and-verify path, against a `modinfo` that
        #     resolves its argument by filename suffix rather than content --
        #     this is how a real Unraid box's modinfo actually behaved, and
        #     it silently failed every download because the pre-rename
        #     candidate was named ".gpu_unlock.ko.new" (does not end in
        #     ".ko"). No offline test exercised this path before: every other
        #     test here either stubs module_matches_kernel() outright or
        #     never reaches the download step, so this bug shipped to a real
        #     box before being caught.
        fake_bin_dir = work / "fakebin"
        fake_bin_dir.mkdir()
        fake_modinfo = fake_bin_dir / "modinfo"
        fake_modinfo.write_text(
            "#!/bin/sh\n"
            "case \"$3\" in\n"
            "  *.ko) echo '6.18.64-Unraid SMP preempt mod_unload ' ;;\n"
            "  *) echo \"modinfo: ERROR: Module $3 not found.\" >&2; exit 1 ;;\n"
            "esac\n")
        fake_modinfo.chmod(0o755)
        module_bytes = b"pretend module bytes; a real modinfo would read the ELF, this fake one only checks the suffix"
        module_digest = hashlib.sha256(module_bytes).hexdigest()
        root3 = work / "root3"
        fetch_manifest_path = work / "fetch-modules.json"
        fetch_manifest_path.write_text(
            '{"schema": 1, "modules": {"6.18.64-Unraid": '
            f'{{"url": "https://example.invalid/gpu_unlock.ko", "sha256": "{module_digest}"}}}}}}')
        original_http_get = mm.http_get
        original_path = __import__("os").environ.get("PATH", "")
        mm.http_get = lambda url, limit, timeout: module_bytes
        __import__("os").environ["PATH"] = f"{fake_bin_dir}:{original_path}"
        try:
            message = mm.ensure("6.18.64-Unraid", root3, str(fetch_manifest_path), 5)
            installed = root3 / "payload" / "6.18.64-Unraid" / "gpu_unlock.ko"
            assert installed.read_bytes() == module_bytes, "downloaded module was not staged at the final .ko path"
            assert "downloaded module for 6.18.64-Unraid" in message
            leftovers = list((root3 / "payload" / "6.18.64-Unraid").glob(".gpu_unlock*"))
            assert not leftovers, f"candidate temp file was not cleaned up: {leftovers}"
        finally:
            mm.http_get = original_http_get
            __import__("os").environ["PATH"] = original_path
        print("ok: ensure() downloads, verifies and stages a module against a suffix-sensitive modinfo")

        # 10. prefetch() is a no-op (not an error) when no update is pending.
        running = "6.18.58-Unraid"
        image.write_bytes(make_bzimage(running))
        kernel, message = mm.prefetch(running, image, root, str(manifest_path), 5)
        assert kernel == "" and "no Unraid update" in message
        print("ok: prefetch() is a quiet no-op when the staged kernel matches the running one")

        # 11. module_matches_kernel() / vermagic() never raise when modinfo
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
