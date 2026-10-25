#!/bin/bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd -P)
for script in "$project_dir"/runtime/*.sh "$project_dir"/scripts/*.sh "$project_dir"/tests/*.sh; do
  bash -n "$script"
done
python3 - "$project_dir/RTX-3090-Unlock.plg" <<'PY'
import re
import sys
from xml.etree import ElementTree
root = ElementTree.parse(sys.argv[1]).getroot()
assert root.tag == "PLUGIN"
assert root.attrib["name"] == "RTX-3090-Unlock"
assert root.attrib["author"] == "nonkronk"
# Unraid compares versions with strcmp: keep YYYY.MM.DD[letter].
assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}[a-z]?", root.attrib["version"])
assert root.attrib["icon"] == "microchip"
# Unraid sorts .plg filenames at boot: unlock must precede nvidia-driver.plg.
assert "RTX-3090-Unlock.plg" < "nvidia-driver.plg"
assert root.attrib["pluginURL"].endswith("/RTX-3090-Unlock.plg")
files = root.findall("FILE")
downloads = [f for f in files if "Name" in f.attrib]
actions = [f for f in files if "Run" in f.attrib]
assert len(downloads) == 4
assert all(f.findtext("URL", "").startswith("https://") for f in downloads)
# Unraid only replaces an existing flash file when its SHA256 no longer matches.
assert all(re.fullmatch(r"[0-9a-f]{64}", f.findtext("SHA256", "")) for f in downloads)
assert len(actions) == 2
assert actions[0].attrib.get("Method") == "install"
assert actions[1].attrib.get("Method") == "remove"
loader = actions[0].findtext("INLINE") or ""
assert "prepare-firmware.sh" in loader
assert "configure-boot.py" in loader
assert 'if [ ! -f "$root/enabled" ]' not in loader
assert "bash \"$root/runtime/early-load.sh\"" in loader
removal = actions[1].findtext("INLINE") or ""
assert 'python3 "$root/runtime/configure-boot.py" --disable' in removal
assert "exit 1" in removal
PY
grep -Fq '$CONFIG_ROOT/enabled' "$project_dir/runtime/early-load.sh"
grep -Fq 'gpu_unlock\.targets=' "$project_dir/runtime/early-load.sh"
grep -Fq 'The upstream module checks chip IDs and skips cards already bound.' "$project_dir/runtime/early-load.sh"
grep -Fq 'REQUIRED_AUTOLOAD_BLACKLIST=(nvidia nvidia_drm nvidia_modeset nvidia_uvm)' "$project_dir/runtime/early-load.sh"
grep -Fq 'has_required_blacklist "$cmdline"' "$project_dir/runtime/early-load.sh"
grep -Fq 'RESUME_NVIDIA=1' "$project_dir/runtime/early-load.sh"
grep -Fq 'modprobe nvidia' "$project_dir/runtime/early-load.sh"
grep -Fq '649b36c27178fdf9fcaafd767d60dfbb78b6caa2' "$project_dir/scripts/build-payload.sh"
grep -Fq 'kernel_release=${3:-6.18.58-Unraid}' "$project_dir/scripts/build-local.sh"
test -f "$project_dir/LICENSE"
test -f "$project_dir/bench/gemm.py"
grep -qx -- "--index-url https://download.pytorch.org/whl/cu[0-9]*" "$project_dir/bench/requirements.txt"
grep -qx "torch" "$project_dir/bench/requirements.txt"
python3 "$project_dir/tests/test-boot-config.py"
bash "$project_dir/tests/test-install.sh"
python3 "$project_dir/tests/test-pins.py"
source "$project_dir/runtime/early-load.sh"
has_required_blacklist 'quiet modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm initrd=/bzroot'
has_required_blacklist 'initrd=/bzroot modprobe.blacklist=acpi_cpufreq,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm gpu_unlock.targets=0000:0a:00.0'
! has_required_blacklist 'modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset'
! has_required_blacklist 'modprobe.blacklist=nouveau'
echo 'Static, plugin, and offline boot-recovery checks passed (no GPU access).'
