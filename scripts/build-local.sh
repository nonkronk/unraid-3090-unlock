#!/usr/bin/env bash
# Local, opt-in build; creates source/payload inside a new directory.
# Does not install anything or interact with Unraid/GPU.
set -euo pipefail

if [[ $# -ne 1 || "$1" != /* || -e "$1" ]]; then
  echo "Usage: $0 ABSOLUTE_NEW_WORK_DIRECTORY" >&2
  exit 2
fi
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo "Run on Linux x86-64; no cross-compiler configured." >&2
  exit 1
}
for tool in git gcc make modinfo readelf curl jq unzip unsquashfs tar; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done

project_dir=$(cd "$(dirname "$0")/.." && pwd -P)
work_root=$1
mkdir -p "$work_root"
bash "$project_dir/tests/test-static.sh"
git clone https://github.com/Zagitta/gpu-unlock.git "$work_root/upstream"
git -C "$work_root/upstream" checkout --detach 649b36c27178fdf9fcaafd767d60dfbb78b6caa2

bash "$project_dir/scripts/prepare-unraid-kernel.sh" \
  7.3.4 6.18.58-Unraid "$work_root/kernel"
bash "$project_dir/scripts/build-payload.sh" \
  "$work_root/upstream" "$work_root/kernel/linux-6.18.58" "$work_root/artifact"
bash "$project_dir/tests/test-payload.sh" "$work_root/artifact" 6.18.58-Unraid

echo "Offline staging tree: $work_root/artifact/flash"
echo "No Unraid host files were changed."
