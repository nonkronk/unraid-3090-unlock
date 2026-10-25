#!/usr/bin/env python3
"""Configure the default Unraid OS boot entry and a nondefault recovery entry.

Called only after the exact-kernel payload and firmware have been staged.
Never reboots, unloads a driver, changes a VM, or touches array assignments.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DRIVER_IDS = ("nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm")
RECOVERY_LABEL = "Unraid OS (No GPU Unlock)"
TARGET_RE = re.compile(r"(?<!\S)gpu_unlock\.targets=([^\s]+)")
BLACKLIST_RE = re.compile(r"(?<!\S)modprobe\.blacklist=([^\s]+)")
LABEL_RE = re.compile(r"^\s*label\s+(.+?)\s*$", re.I)
APPEND_RE = re.compile(r"^(\s*append\s+)(.*?)(\r?\n?)$", re.I)


class SetupError(Exception):
    pass


def detect_card(pci_root: Path) -> str:
    found = []
    for slot in sorted(pci_root.iterdir()):
        try:
            if (slot / "vendor").read_text().strip().lower() != "0x10de":
                continue
            if (slot / "device").read_text().strip().lower() == "0x2204":
                driver = slot / "driver"
                if driver.is_symlink() and driver.resolve().name != "nvidia":
                    raise SetupError("RTX 3090 is bound to a non-NVIDIA driver; refusing VM passthrough changes")
                if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", slot.name):
                    raise SetupError("Invalid NVIDIA PCI address")
                found.append(slot.name.lower())
        except (OSError, UnicodeError):
            continue
    if len(found) != 1:
        raise SetupError(f"Expected exactly one RTX 3090 (10de:2204), found {len(found)}")
    return found[0]


def find_entry(lines: list[str], label: str) -> tuple[int, int]:
    found = [i for i, line in enumerate(lines) if
             (match := LABEL_RE.match(line)) and match.group(1) == label]
    if len(found) != 1:
        raise SetupError(f"Expected exactly one Syslinux entry: {label}")
    start = found[0]
    end = next((i for i in range(start + 1, len(lines)) if LABEL_RE.match(lines[i])), len(lines))
    return start, end


def find_append(lines: list[str], start: int, end: int) -> int:
    matches = [i for i in range(start, end) if APPEND_RE.match(lines[i])]
    if len(matches) != 1:
        raise SetupError("Expected exactly one append line in the default boot entry")
    return matches[0]


def merge_options(original: str, card: str) -> str:
    if TARGET_RE.search(original):
        raise SetupError("GPU Unlock target already configured; refusing duplicate modification")
    old = BLACKLIST_RE.findall(original)
    if len(old) > 1:
        raise SetupError("Multiple modprobe.blacklist arguments; edit manually")
    if old:
        names = [name for name in old[0].split(",") if name]
        for name in DRIVER_IDS:
            if name not in names:
                names.append(name)
        updated = BLACKLIST_RE.sub("modprobe.blacklist=" + ",".join(names), original, count=1)
    else:
        updated = original + " modprobe.blacklist=" + ",".join(DRIVER_IDS)
    return updated + " gpu_unlock.targets=" + card


def infer_normal_options(options: str) -> str:
    """Infer rollback for older manually configured GPU Unlock installations."""
    if len(TARGET_RE.findall(options)) != 1:
        raise SetupError("Expected one existing GPU Unlock target")
    result = TARGET_RE.sub("", options, count=1)
    blacklists = BLACKLIST_RE.findall(result)
    if len(blacklists) != 1:
        raise SetupError("Expected one NVIDIA blacklist")
    retained = [n for n in blacklists[0].split(",") if n and n not in DRIVER_IDS]
    result = BLACKLIST_RE.sub(
        "modprobe.blacklist=" + ",".join(retained) if retained else "",
        result, count=1
    )
    return " ".join(result.split())


def write_atomic(destination: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                     prefix=".gpu-unlock-", delete=False) as temp:
        temp.write(content)
        temp.flush()
        os.fsync(temp.fileno())
        temporary = Path(temp.name)
    try:
        try:
            os.chmod(temporary, destination.stat().st_mode & 0o777)
        except OSError:
            # VFAT boot media may impose fixed permissions via mount options.
            pass
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def configure(cfg: Path, pci_root: Path, plugin_root: Path) -> str:
    card = detect_card(pci_root)
    lines = cfg.read_text().splitlines(keepends=True)
    start, end = find_entry(lines, "Unraid OS")
    if not any(re.fullmatch(r"\s*menu\s+default\s*", line, re.I) for line in lines[start:end]):
        raise SetupError("The Unraid OS entry is not the default; refusing to change another entry")
    line_idx = find_append(lines, start, end)
    match = APPEND_RE.match(lines[line_idx])
    if match is None:
        raise SetupError("Missing Syslinux append")
    prefix, options, newline = match.groups()
    target = TARGET_RE.findall(options)
    if target:
        if target != [card]:
            raise SetupError("Existing GPU Unlock target differs from detected RTX 3090")
        names = BLACKLIST_RE.findall(options)
        if len(names) != 1 or not all(n in names[0].split(",") for n in DRIVER_IDS):
            raise SetupError("Existing GPU Unlock boot line lacks NVIDIA blacklist")
        marker = plugin_root / "enabled"
        record_file = plugin_root / "boot-setup.json"
        if record_file.is_file():
            saved = json.loads(record_file.read_text())
            if saved["configured_append"] != options:
                raise SetupError("Current boot options differ from rollback record")
            recovery = saved.get("recovery_block", "")
            if recovery and "".join(lines).count(recovery) != 1:
                raise SetupError("Recorded fallback boot entry changed")
            marker.touch(exist_ok=True)
            return "GPU Unlock boot entry already configured; left unchanged"

        legacy = plugin_root.parent / "00-gpu-unlock"
        legacy_record = legacy / "boot-setup.json"
        if legacy_record.is_file() and (legacy / "enabled").is_file():
            previous = json.loads(legacy_record.read_text())
            if not all(key in previous for key in
                       ("configured_append", "original_append", "recovery_block")):
                raise SetupError("Legacy rollback record is incomplete")
            if previous["configured_append"] != options:
                raise SetupError("Legacy recorded boot options differ; refusing migration")
            if "".join(lines).count(previous["recovery_block"]) != 1:
                raise SetupError("Legacy fallback entry was changed; refusing migration")
            plugin_root.mkdir(parents=True, exist_ok=True)
            write_atomic(record_file, json.dumps(previous) + "\n")
            marker.touch(exist_ok=True)
            try:
                legacy_record.rename(legacy / "boot-setup-transferred.json")
            except OSError:
                marker.unlink(missing_ok=True)
                record_file.unlink(missing_ok=True)
                raise
            return "Migrated existing rollback record; old plugin can now be removed"

        if (legacy / "enabled").is_file() or (plugin_root / "adopted-legacy-boot").is_file():
            # Explicitly record the inferred pre-unlock arguments. Uninstall can
            # now safely restore normal NVIDIA startup instead of leaving it blacklisted.
            plugin_root.mkdir(parents=True, exist_ok=True)
            record = {
                "source": "legacy-manual",
                "original_append": infer_normal_options(options),
                "configured_append": options,
                "recovery_block": "",
            }
            write_atomic(record_file, json.dumps(record) + "\n")
            marker.touch(exist_ok=True)
            return "Adopted manual boot setup with a reversible uninstall plan"
        raise SetupError("Existing GPU Unlock boot line has no recognized owner; refusing changes")

    if any((label := LABEL_RE.match(line)) and label.group(1) == RECOVERY_LABEL for line in lines):
        raise SetupError("Recovery entry already exists unexpectedly")

    kernel_lines = [line for line in lines[start:end]
                    if re.match(r"^\s*kernel\s+", line, re.I)]
    if len(kernel_lines) != 1:
        raise SetupError("Unexpected default kernel syntax")

    updated = merge_options(options, card)
    backup = cfg.with_name("syslinux.cfg.before-gpu-unlock-" +
                           datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    with backup.open("x", encoding="utf-8") as saved:
        saved.writelines(lines)
        saved.flush()
        os.fsync(saved.fileno())

    lines[line_idx] = prefix + updated + (newline or "\n")
    recovery = ("\nlabel " + RECOVERY_LABEL + "\n" +
                kernel_lines[0].rstrip("\r\n") + "\n" +
                prefix + options + "\n")
    content = "".join(lines).rstrip("\r\n") + "\n" + recovery
    plugin_root.mkdir(parents=True, exist_ok=True)
    record_file = plugin_root / "boot-setup.json"
    if record_file.exists():
        raise SetupError("Rollback record already exists; refusing to overwrite")
    # Save the rollback plan BEFORE changing boot arguments.
    write_atomic(record_file, json.dumps({
        "backup": str(backup),
        "original_append": options,
        "configured_append": updated,
        "recovery_block": recovery,
    }) + "\n")
    try:
        write_atomic(cfg, content)
        (plugin_root / "enabled").touch(exist_ok=True)
    except OSError:
        if cfg.read_text() == content:
            write_atomic(cfg, backup.read_text())
        record_file.unlink(missing_ok=True)
        raise
    return f"Prepared GPU Unlock for {card}; recovery added; restart required"


def disable(cfg: Path, plugin_root: Path) -> str:
    """Restore boot settings before disabling. Never silently strand NVIDIA."""
    marker = plugin_root / "enabled"
    record = plugin_root / "boot-setup.json"
    if not record.is_file():
        if marker.exists():
            raise SetupError("Uninstall refused: missing original boot options")
        return "Already disabled; nothing to restore"
    saved = json.loads(record.read_text())
    lines = cfg.read_text().splitlines(keepends=True)
    start, end = find_entry(lines, "Unraid OS")
    idx = find_append(lines, start, end)
    match = APPEND_RE.match(lines[idx])
    if match is None or match.group(2) != saved["configured_append"]:
        raise SetupError("Uninstall refused: Syslinux boot options changed since install")
    current = "".join(lines)
    recovery = saved.get("recovery_block", "")
    if recovery and current.count(recovery) != 1:
        raise SetupError("Uninstall refused: fallback boot entry changed")
    lines[idx] = match.group(1) + saved["original_append"] + (match.group(3) or "\n")
    restored = "".join(lines)
    if recovery:
        restored = restored.replace(recovery, "", 1)
    # No runtime, VM, or GPU action. Restore the boot file first.
    write_atomic(cfg, restored)
    if marker.exists():
        marker.rename(plugin_root / "disabled-on-uninstall")
    record.rename(plugin_root / "boot-setup-restored.json")
    return "GPU Unlock disabled; next boot uses restored NVIDIA boot options"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--syslinux", type=Path, default=Path("/boot/syslinux/syslinux.cfg"))
    parser.add_argument("--pci-root", type=Path, default=Path("/sys/bus/pci/devices"))
    parser.add_argument("--plugin-root", type=Path, default=Path("/boot/config/plugins/RTX-3090-Unlock"))
    args = parser.parse_args()
    try:
        print(disable(args.syslinux, args.plugin_root) if args.disable else
              configure(args.syslinux, args.pci_root, args.plugin_root))
    except (SetupError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"RTX-3090-Unlock: boot setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
