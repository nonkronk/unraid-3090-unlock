#!/usr/bin/env bash
# Metadata-only validation of the offline output; does not touch a GPU.
set -euo pipefail
[[ $# -eq 2 ]] || { echo "Usage: $0 OUTPUT_DIR KERNEL_RELEASE" >&2; exit 2; }
output=$1
kernel=$2
payload="$output/flash/config/plugins/00-gpu-unlock/payload/$kernel"
plugin="$output/flash/config/plugins/00-gpu-unlock.plg"
loader="$output/flash/config/plugins/00-gpu-unlock/runtime/early-load.sh"
[[ -s "$plugin" && -x "$loader" && -s "$payload/gpu_unlock.ko" ]]
for file in \
  booter_load_ga102.bin gsp_ga10x.bin gsp_boot_ga102.bin \
  gsp_boot_desc_ga102.bin v67-ga102-610.43.03.bin; do
  [[ -s "$payload/firmware/gpu-unlock/610.43.03/$file" ]]
done
[[ -s "$payload/NVIDIA-LICENSE" && -s "$payload/FIRMWARE-NOTICE.md" ]]
grep -qx "unraid_kernel=$kernel" "$output/build-info.txt"
grep -qx "upstream_commit=649b36c27178fdf9fcaafd767d60dfbb78b6caa2" "$output/build-info.txt"
modinfo -F vermagic "$payload/gpu_unlock.ko" | grep -q "^$kernel "
readelf -h "$payload/gpu_unlock.ko" | grep -Fq "Advanced Micro Devices X86-64"
echo "Offline payload metadata and x86-64 ELF validated (not hardware-tested)."
