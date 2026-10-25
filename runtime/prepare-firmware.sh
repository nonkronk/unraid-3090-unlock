#!/bin/bash
# Prepare pinned NVIDIA firmware on the user's Unraid host.
# No NVIDIA firmware is redistributed by this plugin.
set -euo pipefail

readonly VERSION=610.43.03
readonly UPSTREAM_COMMIT=649b36c27178fdf9fcaafd767d60dfbb78b6caa2
readonly CONFIG_ROOT=/boot/config/plugins/RTX-3090-Unlock
readonly OUTPUT="$CONFIG_ROOT/payload/6.18.58-Unraid/firmware/gpu-unlock/$VERSION"
readonly LICENSE="$CONFIG_ROOT/payload/6.18.58-Unraid/NVIDIA-LICENSE"
readonly NOTICE="$CONFIG_ROOT/payload/6.18.58-Unraid/FIRMWARE-NOTICE.md"
readonly FILENAMES=(
  booter_load_ga102.bin gsp_ga10x.bin gsp_boot_ga102.bin
  gsp_boot_desc_ga102.bin v67-ga102-610.43.03.bin
)

ready=1
for name in "${FILENAMES[@]}"; do
  [[ -s "$OUTPUT/$name" ]] || ready=0
done
[[ -s "$LICENSE" && -s "$NOTICE" ]] || ready=0
if (( ready )); then
  echo "RTX-3090-Unlock: firmware already prepared"
  exit 0
fi

for command in curl python3 zstd tar; do
  command -v "$command" >/dev/null || {
    echo "RTX-3090-Unlock: missing required command: $command" >&2
    exit 1
  }
done
[[ $(uname -r) == 6.18.58-Unraid ]] || {
  echo "RTX-3090-Unlock: no validated firmware setup for this kernel" >&2
  exit 1
}
[[ -s "$CONFIG_ROOT/payload/6.18.58-Unraid/gpu_unlock.ko" ]] || {
  echo "RTX-3090-Unlock: matching GPL kernel module is not staged" >&2
  exit 1
}
scratch=$(mktemp -d /tmp/rtx-3090-unlock.XXXXXXXX)
trap 'rm -r -- "$scratch"' EXIT
mkdir -p "$scratch/upstream" "$scratch/assets"

base="https://raw.githubusercontent.com/Zagitta/gpu-unlock/$UPSTREAM_COMMIT/firmware"
for name in fetch_artifacts.py generate_v67.py extract_boot_assets.py artifacts-610.43.03.json NOTICE.md; do
  curl --fail --silent --show-error --location --retry 3 \
    --proto '=https' --proto-redir '=https' \
    --output "$scratch/upstream/$name" "$base/$name"
done

python3 "$scratch/upstream/fetch_artifacts.py" "$scratch/inputs"
tar -xf "$scratch/inputs/NVIDIA-kernel-module-source-$VERSION.tar.xz" -C "$scratch"
python3 "$scratch/upstream/generate_v67.py" \
  "$scratch/inputs/nvidia-utils-$VERSION-1-x86_64_v3.pkg.tar.zst" "$scratch/assets"
python3 "$scratch/upstream/extract_boot_assets.py" \
  "$scratch/NVIDIA-kernel-module-source-$VERSION" "$scratch/assets"

for name in "${FILENAMES[@]}"; do
  [[ -s "$scratch/assets/$name" ]] || {
    echo "RTX-3090-Unlock: missing generated asset $name" >&2
    exit 1
  }
done
[[ -s "$scratch/assets/NVIDIA-LICENSE" ]] || {
  echo "RTX-3090-Unlock: missing NVIDIA license" >&2
  exit 1
}

mkdir -p "$OUTPUT"
for name in "${FILENAMES[@]}"; do
  cp "$scratch/assets/$name" "$OUTPUT/$name"
done
cp "$scratch/assets/NVIDIA-LICENSE" "$LICENSE"
cp "$scratch/upstream/NOTICE.md" "$NOTICE"
echo "RTX-3090-Unlock: firmware generated locally and staged for next boot"
