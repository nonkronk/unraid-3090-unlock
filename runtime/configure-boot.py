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
        if not (plugin_root / "enabled").is_file():
            legacy = plugin_root.parent / "00-gpu-unlock"
            if (legacy / "enabled").is_file() and not (legacy / "boot-setup.json").exists():
                # Older manual setup has no reliable original append backup.
                # Adopt exactly its known target/blacklist, but never invent a recovery entry.
                plugin_root.mkdir(parents=True, exist_ok=True)
                (plugin_root / "enabled").touch()
                (plugin_root / "adopted-legacy-boot").write_text(
                    "Boot arguments were adopted from 00-gpu-unlock. "
                    "No recovery entry was created; preserve the original boot USB backup.\n"
                )
                return "Adopted existing GPU Unlock boot arguments; recovery entry NOT created"
            raise SetupError("Existing GPU Unlock boot line is not owned by this plugin; refusing changes")
        return "GPU Unlock boot entry already configured; left unchanged"

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
    write_atomic(cfg, content)
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "boot-setup.json").write_text(json.dumps({
        "backup": str(backup),
        "original_append": options,
        "configured_append": updated,
        "recovery_block": recovery,
    }) + "\n")
    (plugin_root / "enabled").touch(exist_ok=True)
    return f"Prepared GPU Unlock for {card}; recovery added; cold boot required"


def disable(cfg: Path, plugin_root: Path) -> str:
    marker = plugin_root / "enabled"
    if marker.exists():
        marker.rename(plugin_root / "disabled-on-uninstall")
    record = plugin_root / "boot-setup.json"
    if not record.is_file():
        return "Activation disabled; boot options were not created by this installer"
    saved = json.loads(record.read_text())
    lines = cfg.read_text().splitlines(keepends=True)
    start, end = find_entry(lines, "Unraid OS")
    idx = find_append(lines, start, end)
    match = APPEND_RE.match(lines[idx])
    if match is None or match.group(2) != saved["configured_append"]:
        return "Activation disabled; Syslinux was edited since install, restore manually"
    current = "".join(lines)
    recovery = saved["recovery_block"]
    if current.count(recovery) != 1:
        return "Activation disabled; recovery entry changed, restore manually"
    lines[idx] = match.group(1) + saved["original_append"] + (match.group(3) or "\n")
    restored = "".join(lines).replace(recovery, "", 1)
    write_atomic(cfg, restored)
    record.rename(plugin_root / "boot-setup-restored.json")
    return "GPU Unlock disabled; original default boot options restored"


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
