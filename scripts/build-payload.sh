#!/bin/bash
# Creates an offline flash-staging tree; never deploys to Unraid.
set -euo pipefail

usage() {
  echo "Usage: $0 ABSOLUTE_UPSTREAM_SOURCE ABSOLUTE_UNRAID_KERNEL_BUILD ABSOLUTE_NEW_OUTPUT" >&2
  exit 2
}
readonly UPSTREAM_COMMIT=649b36c27178fdf9fcaafd767d60dfbb78b6caa2
[[ $# -eq 3 ]] || usage
source_dir=$1
kernel_build=$2
output_dir=$3
[[ "$source_dir" = /* && "$kernel_build" = /* && "$output_dir" = /* ]] || usage
[[ -f "$source_dir/Makefile" && -f "$source_dir/kernel/gpu_unlock/Kbuild" ]] || { echo "Not a gpu-unlock checkout" >&2; exit 1; }
upstream_commit=$(git -C "$source_dir" rev-parse --verify HEAD 2>/dev/null) || { echo "Upstream checkout must be a Git repository" >&2; exit 1; }
[[ "$upstream_commit" == "$UPSTREAM_COMMIT" ]] || { echo "Unexpected upstream commit $upstream_commit (expected $UPSTREAM_COMMIT)" >&2; exit 1; }
[[ -d "$kernel_build" ]] || { echo "Missing prepared Unraid kernel build tree" >&2; exit 1; }
[[ ! -e "$output_dir" ]] || { echo "Output must be a fresh nonexistent directory" >&2; exit 1; }

project_dir=$(cd "$(dirname "$0")/.." && pwd -P)
kernel=$(make -s -C "$kernel_build" kernelrelease)
[[ "$kernel" == *-Unraid ]] || { echo "Refusing non-Unraid kernel: $kernel" >&2; exit 1; }
if [[ ! -s "$kernel_build/Module.symvers" ]]; then
  # Official Unraid builds disable CONFIG_MODVERSIONS. A prepared vanilla source
  # tree then needs KBUILD_MODPOST_WARN=1, with runtime symbol checks deferred
  # to modprobe. Do not accept this shortcut for a MODVERSIONS-enabled kernel.
  grep -qx '# CONFIG_MODVERSIONS is not set' "$kernel_build/.config" || {
    echo "Module.symvers missing on a kernel whose MODVERSIONS setting cannot be verified" >&2
    exit 1
  }
  export KBUILD_MODPOST_WARN=1
fi

mkdir -p "$output_dir"
cache="$output_dir/cache"
make -C "$source_dir" assets CACHE="$cache"
make -C "$source_dir/kernel/gpu_unlock" KDIR="$kernel_build" all

flash="$output_dir/flash"
config="$flash/config/plugins/00-gpu-unlock"
payload="$config/payload/$kernel"
firmware="$payload/firmware/gpu-unlock/610.43.03"
mkdir -p "$firmware" "$config/runtime"
install -m 0644 "$source_dir/kernel/gpu_unlock/gpu_unlock.ko" "$payload/gpu_unlock.ko"
for file in \
  booter_load_ga102.bin gsp_ga10x.bin gsp_boot_ga102.bin \
  gsp_boot_desc_ga102.bin v67-ga102-610.43.03.bin; do
  install -m 0644 "$cache/assets/$file" "$firmware/$file"
done
install -m 0755 "$project_dir/runtime/early-load.sh" "$config/runtime/early-load.sh"
install -m 0644 "$project_dir/00-gpu-unlock.plg" "$flash/config/plugins/00-gpu-unlock.plg"
install -m 0644 "$cache/assets/NVIDIA-LICENSE" "$payload/NVIDIA-LICENSE"
install -m 0644 "$source_dir/firmware/NOTICE.md" "$payload/FIRMWARE-NOTICE.md"

command -v modinfo >/dev/null 2>&1 || { echo "modinfo is required for build validation" >&2; exit 1; }
vermagic=$(modinfo -F vermagic "$payload/gpu_unlock.ko")
[[ "$vermagic" == "$kernel "* ]] || { echo "Incorrect module vermagic: $vermagic" >&2; exit 1; }
printf 'upstream_commit=%s\nunraid_kernel=%s\nfirmware_version=610.43.03\n' "$upstream_commit" "$kernel" > "$output_dir/build-info.txt"
echo "Offline flash-staging tree: $flash"
echo "Do not deploy or cold-boot without separate approval."
