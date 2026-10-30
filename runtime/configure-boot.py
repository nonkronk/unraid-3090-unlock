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


def host_gpu_addresses(pci_root: Path) -> list[str]:
    """Find host-managed NVIDIA display adapters; upstream decides chip support."""
    found = []
    for slot in sorted(pci_root.iterdir()):
        try:
            if (slot / "vendor").read_text().strip().lower() != "0x10de":
                continue
            class_file = slot / "class"
            if class_file.exists() and not class_file.read_text().strip().lower().startswith("0x03"):
                continue
            if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", slot.name):
                continue
            driver = slot / "driver"
            if driver.is_symlink() and driver.resolve().name != "nvidia":
                # Never change devices reserved for VFIO or another driver.
                continue
            found.append(slot.name.lower())
        except (OSError, UnicodeError):
            continue
    if not found:
        raise SetupError("No host-managed NVIDIA display GPU found")
    return found


def configured_target_valid(value: str, cards: list[str]) -> bool:
    if value == "all":
        return True
    addresses = value.lower().split(",")
    return bool(addresses) and len(set(addresses)) == len(addresses) and all(
        address in cards for address in addresses
    )


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


def blacklisted(options: str) -> list[str]:
    """Every module named by any modprobe.blacklist= argument (modprobe combines them)."""
    return [name for value in BLACKLIST_RE.findall(options) for name in value.split(",") if name]


def strip_plugin_options(options: str, original: str) -> str:
    """Remove only what the plugin added; keep every other argument as it is now."""
    keep = set(blacklisted(original))
    result = TARGET_RE.sub("", options)

    def clean(match: re.Match) -> str:
        names = [n for n in match.group(1).split(",")
                 if n and (n not in DRIVER_IDS or n in keep)]
        return "modprobe.blacklist=" + ",".join(names) if names else ""

    return " ".join(BLACKLIST_RE.sub(clean, result).split())


def remove_recovery(text: str, recovery: str) -> str:
    """Remove the plugin's fallback entry, even if it was edited since install."""
    if recovery and text.count(recovery) == 1:
        return text.replace(recovery, "", 1)
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines)
              if (m := LABEL_RE.match(line)) and m.group(1) == RECOVERY_LABEL]
    if not starts:
        return text
    if len(starts) > 1:
        raise SetupError(f"More than one '{RECOVERY_LABEL}' entry; remove the extras manually")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if LABEL_RE.match(lines[i])), len(lines))
    if start and not lines[start - 1].strip():
        start -= 1
    return "".join(lines[:start] + lines[end:])


def merge_options(original: str, card: str) -> str:
    if TARGET_RE.search(original):
        raise SetupError("GPU Unlock target already configured; refusing duplicate modification")
    old = BLACKLIST_RE.findall(original)
    if old:
        present = set(blacklisted(original))
        names = [name for name in old[0].split(",") if name]
        names += [name for name in DRIVER_IDS if name not in present]
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
    cards = host_gpu_addresses(pci_root)
    card = "all"
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
        if len(target) != 1 or not configured_target_valid(target[0], cards):
            raise SetupError("Existing GPU Unlock target does not match host-managed NVIDIA GPUs")
        if not all(n in blacklisted(options) for n in DRIVER_IDS):
            raise SetupError("modprobe.blacklist must include " + ",".join(DRIVER_IDS))
        marker = plugin_root / "enabled"
        record_file = plugin_root / "boot-setup.json"
        if record_file.is_file():
            # Other boot parameters may change freely; only the plugin's own
            # arguments (checked above) matter. Uninstall removes just those.
            if "original_append" not in json.loads(record_file.read_text()):
                raise SetupError("Rollback record is incomplete")
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
    if match is None:
        raise SetupError("Missing Syslinux append")
    options = match.group(2)
    if options == saved.get("configured_append"):
        normal = saved["original_append"]
    else:
        # Edited since install: keep the user's changes, drop only ours.
        normal = strip_plugin_options(options, saved["original_append"])
    lines[idx] = match.group(1) + normal + (match.group(3) or "\n")
    restored = remove_recovery("".join(lines), saved.get("recovery_block", ""))
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
