#!/usr/bin/env bash
# Local, opt-in build; creates source/payload inside a new directory.
# Does not install anything or interact with Unraid/GPU.
set -euo pipefail

if [[ $# -ne 1 && $# -ne 3 ]]; then
  echo "Usage: $0 ABSOLUTE_NEW_WORK_DIRECTORY [UNRAID_VERSION KERNEL_RELEASE]" >&2
  exit 2
fi
if [[ "$1" != /* || -e "$1" ]]; then
  echo "Work directory must be a new absolute path" >&2
  exit 2
fi
unraid_version=${2:-7.3.4}
kernel_release=${3:-6.18.58-Unraid}
[[ "$unraid_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$kernel_release" =~ ^[0-9]+\.[0-9]+\.[0-9]+-Unraid$ ]] || {
  echo "Invalid Unraid version or kernel release" >&2
  exit 2
}
kernel_source="${kernel_release%-Unraid}"
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
  "$unraid_version" "$kernel_release" "$work_root/kernel"
bash "$project_dir/scripts/build-payload.sh" \
  "$work_root/upstream" "$work_root/kernel/linux-$kernel_source" "$work_root/artifact"
bash "$project_dir/tests/test-payload.sh" "$work_root/artifact" "$kernel_release"

echo "Offline staging tree: $work_root/artifact/flash"
echo "No Unraid host files were changed."
