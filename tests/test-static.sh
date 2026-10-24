#!/bin/bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd -P)
bash -n "$project_dir/runtime/early-load.sh"
bash -n "$project_dir/scripts/build-payload.sh"
bash -n "$project_dir/scripts/build-local.sh"
bash -n "$project_dir/scripts/prepare-unraid-kernel.sh"
bash -n "$project_dir/tests/test-payload.sh"
python3 - "$project_dir/00-gpu-unlock.plg" <<'PY'
import sys
from xml.etree import ElementTree
root = ElementTree.parse(sys.argv[1]).getroot()
assert root.tag == 'PLUGIN'
assert root.attrib['name'] == '00-gpu-unlock'
files = root.findall('FILE')
assert len(files) == 2
assert files[0].attrib.get('Run') == '/bin/bash'
assert files[1].attrib.get('Method') == 'remove'
loader = files[0].find('INLINE').text or ''
assert 'if [ -f "$loader" ]; then' in loader
assert 'bash "$loader"' in loader
PY
grep -Fq '$CONFIG_ROOT/enabled' "$project_dir/runtime/early-load.sh"
grep -Fq 'gpu_unlock\.targets=' "$project_dir/runtime/early-load.sh"
grep -Fq 'already bound; refusing unlock' "$project_dir/runtime/early-load.sh"
grep -Fq 'REQUIRED_AUTOLOAD_BLACKLIST=(nvidia nvidia_drm nvidia_modeset nvidia_uvm)' "$project_dir/runtime/early-load.sh"
grep -Fq 'has_required_blacklist "$cmdline"' "$project_dir/runtime/early-load.sh"
grep -Fq 'RESUME_NVIDIA=1' "$project_dir/runtime/early-load.sh"
grep -Fq 'modprobe nvidia' "$project_dir/runtime/early-load.sh"
grep -Fq 'exit 0' "$project_dir/runtime/early-load.sh"
grep -Fq '649b36c27178fdf9fcaafd767d60dfbb78b6caa2' "$project_dir/scripts/build-payload.sh"
grep -Fq '7.3.4 6.18.58-Unraid' "$project_dir/scripts/build-local.sh"
test -f "$project_dir/LICENSE"
test -f "$project_dir/bench/gemm.py"
# Source only the parser; the script's main block must never touch a GPU here.
source "$project_dir/runtime/early-load.sh"
has_required_blacklist 'quiet modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm initrd=/bzroot'
has_required_blacklist 'initrd=/bzroot modprobe.blacklist=acpi_cpufreq,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm gpu_unlock.targets=0000:0a:00.0'
has_required_blacklist 'modprobe.blacklist=nvidia_uvm,nvidia,nvidia_modeset,nvidia_drm'
! has_required_blacklist 'modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset'
! has_required_blacklist 'modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm2'
! has_required_blacklist 'modprobe.blacklist=nouveau'
echo 'Static and boot-parameter checks passed (no GPU access).'
