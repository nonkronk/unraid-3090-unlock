#!/usr/bin/env bash
# Runs the .plg install script against a fake flash, /proc/cmdline and stubbed
# system commands. Never touches /boot, a kernel module or a GPU.
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd -P)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

python3 - "$project_dir/RTX-3090-Unlock.plg" "$work/install.sh" <<'PY'
import sys
from xml.etree import ElementTree
root = ElementTree.parse(sys.argv[1]).getroot()
script = next(f for f in root.findall("FILE") if f.get("Method") == "install").findtext("INLINE")
open(sys.argv[2], "w").write(script)
PY

# Point the script at the sandbox instead of the real system.
sed -i \
  -e "s#/boot/config/plugins/RTX-3090-Unlock#$work/flash#g" \
  -e "s#/proc/cmdline#$work/cmdline#g" \
  -e "s#/sys/module/nvidia#$work/sys-nvidia#g" \
  -e "s#/usr/local/emhttp/webGui/scripts/notify#$work/bin/notify#g" \
  "$work/install.sh"
grep -q '/boot\|/proc/' "$work/install.sh" && { echo "install script still references host paths" >&2; exit 1; }

mkdir -p "$work/bin"
for command in modprobe logger notify python3 uname modinfo; do
  printf '#!/bin/bash\necho "%s $*" >> "%s/calls"\n' "$command" "$work" > "$work/bin/$command"
done
cat >> "$work/bin/uname" <<'SH'
echo 6.18.58-Unraid
SH
cat >> "$work/bin/modinfo" <<'SH'
echo "6.18.58-Unraid SMP preempt mod_unload"
SH
printf 'exit "${PYTHON_EXIT:-0}"\n' >> "$work/bin/python3"
chmod +x "$work/bin/"*

run() {  # run CMDLINE [module present: 1/0]
  rm -rf "$work/flash" "$work/calls"
  touch "$work/calls"
  printf '%s\n' "$1" > "$work/cmdline"
  mkdir -p "$work/flash/runtime"
  printf 'exit 0\n' > "$work/flash/runtime/prepare-firmware.sh"
  printf 'echo early-load >> "%s/calls"\n' "$work" > "$work/flash/runtime/early-load.sh"
  : > "$work/flash/runtime/configure-boot.py"
  if [[ "$2" == 1 ]]; then
    mkdir -p "$work/flash/payload/6.18.58-Unraid"
    echo ko > "$work/flash/payload/6.18.58-Unraid/gpu_unlock.ko"
  fi
  set +e
  PATH="$work/bin:$PATH" bash "$work/install.sh" 2>/dev/null
  status=$?
  set -e
}
configured='initrd=/bzroot modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm gpu_unlock.targets=all'

# Fresh install, no module for this kernel: refuse, do not touch NVIDIA.
run 'initrd=/bzroot' 0
[[ $status -ne 0 ]]
! grep -q '^modprobe' "$work/calls"

# Configured boot after a kernel change: keep the plugin, load NVIDIA, notify.
run "$configured" 0
[[ $status -eq 0 ]]
grep -qx 'modprobe nvidia' "$work/calls"
grep -q '^notify ' "$work/calls"
! grep -q early-load "$work/calls"

# Configured boot, boot options edited by hand: still run the loader.
PYTHON_EXIT=1 run "$configured" 1
[[ $status -eq 0 ]]
grep -q early-load "$work/calls"
grep -q '^notify ' "$work/calls"

# Fresh install, boot validation fails: refuse.
PYTHON_EXIT=1 run 'initrd=/bzroot' 1
[[ $status -ne 0 ]]
! grep -q early-load "$work/calls"

# Normal configured boot: loader runs, no warnings.
run "$configured" 1
[[ $status -eq 0 ]]
grep -q early-load "$work/calls"
! grep -q '^notify ' "$work/calls"

echo 'Plugin install fail-safe checks passed (sandboxed).'
