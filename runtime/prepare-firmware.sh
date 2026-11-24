#!/bin/bash
# Prepare pinned NVIDIA firmware on the user's Unraid host.
# No NVIDIA firmware is redistributed by this plugin.
set -euo pipefail

readonly VERSION=610.43.03
readonly CONFIG_ROOT=/boot/config/plugins/RTX-3090-Unlock
readonly VENDOR="$CONFIG_ROOT/vendor/zagitta-firmware"
readonly KERNEL_RELEASE="$(uname -r)"
readonly PAYLOAD="$CONFIG_ROOT/payload/$KERNEL_RELEASE"
readonly OUTPUT="$PAYLOAD/firmware/gpu-unlock/$VERSION"
readonly LICENSE="$PAYLOAD/NVIDIA-LICENSE"
readonly NOTICE="$PAYLOAD/FIRMWARE-NOTICE.md"
readonly LOG=/var/log/gpu-unlock-unraid.log
readonly FILENAMES=(
  booter_load_ga102.bin gsp_ga10x.bin gsp_boot_ga102.bin
  gsp_boot_desc_ga102.bin v67-ga102-610.43.03.bin
)

log() {
  local message="RTX-3090-Unlock(firmware): $*"
  echo "$message" >&2
  { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$message" >> "$LOG"; } 2>/dev/null || true
  logger -t RTX-3090-Unlock -- "$*" 2>/dev/null || true
}

fail() {
  log "FAILED: $1"
  echo "$1" >&2
  exit 1
}

ready=1
for name in "${FILENAMES[@]}"; do
  [[ -s "$OUTPUT/$name" ]] || ready=0
done
[[ -s "$LICENSE" && -s "$NOTICE" ]] || ready=0
if (( ready )); then
  log "firmware already prepared at $OUTPUT"
  exit 0
fi

log "preparing firmware for kernel $KERNEL_RELEASE (version $VERSION)"

# --- Preflight: every check failure says exactly what is missing. -----
for command in curl python3 zstd tar; do
  command -v "$command" >/dev/null || fail "missing required command: $command (install it, or use the Nerd Tools plugin, then retry the plugin install)"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' ||
  fail "python3 is older than 3.8: $(python3 --version 2>&1)"
for name in generate_v67.py artifacts-610.43.03.json fetch_artifacts.py extract_boot_assets.py NOTICE.md; do
  [[ -s "$VENDOR/$name" ]] || fail "missing vendored upstream file: $VENDOR/$name (reinstall the plugin)"
done
[[ -s "$PAYLOAD/gpu_unlock.ko" ]] ||
  fail "no gpu_unlock.ko staged for kernel $KERNEL_RELEASE; stage one at $PAYLOAD/gpu_unlock.ko before installing (see docs/technical.md)"
available_kib=$(df -Pk /tmp 2>/dev/null | awk 'NR==2 {print $4}')
if [[ -n "${available_kib:-}" && "$available_kib" -lt 600000 ]]; then
  fail "less than ~600 MB free in /tmp (have ${available_kib} KiB); free up space and retry"
fi
if ! getent hosts download.nvidia.com >/dev/null 2>&1 && ! python3 -c 'import socket; socket.gethostbyname("download.nvidia.com")' >/dev/null 2>&1; then
  fail "cannot resolve download.nvidia.com; check the server's DNS/network and retry"
fi

scratch=$(mktemp -d /tmp/rtx-3090-unlock.XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/upstream" "$scratch/assets"

# --- Booter/GSP boot assets: from NVIDIA's open kernel module source. --
# This source archive is a normal NVIDIA download (not the removed CachyOS
# package) and has no known outage as of this writing; it is still verified
# against the pinned SHA-256 either way.
#
# NOTE: vendor/zagitta-firmware/fetch_artifacts.py's own CLI (main()) always
# fetches BOTH pinned inputs -- this source archive AND the now-dead CachyOS
# nvidia-utils package -- in one loop, and aborts the moment either one
# fails. Calling it directly here would therefore always fail, even though
# this step only needs the source archive. runtime/fetch-firmware.py's
# `source` subcommand calls the same fetch_artifacts.fetch() function but
# only for the source-archive entry (with retries), so use that instead.
log "fetching NVIDIA open kernel module source (~25 MB)"
if ! python3 "$CONFIG_ROOT/runtime/fetch-firmware.py" source \
    --upstream "$VENDOR" --out "$scratch/inputs" 2>>"$LOG"; then
  fail "could not fetch/verify the NVIDIA kernel module source archive; see $LOG for the exact URL and error"
fi
tar -xf "$scratch/inputs/NVIDIA-kernel-module-source-$VERSION.tar.xz" -C "$scratch" ||
  fail "could not extract the NVIDIA kernel module source archive"
log "extracting Booter/GSP boot assets"
if ! python3 "$VENDOR/extract_boot_assets.py" \
    "$scratch/NVIDIA-kernel-module-source-$VERSION" "$scratch/assets" 2>>"$LOG"; then
  fail "could not extract Booter/GSP boot assets from the kernel module source; see $LOG"
fi

# --- GSP firmware + license: multi-source, hash-verified. See
#     runtime/fetch-firmware.py for why this step has more than one source. -
log "fetching/verifying GSP firmware and NVIDIA license (tries several sources)"
if ! python3 "$CONFIG_ROOT/runtime/fetch-firmware.py" firmware \
    --upstream "$VENDOR" --out "$scratch/assets" --work "$scratch" \
    --local "$CONFIG_ROOT/firmware-src" 2>>"$LOG"; then
  fail "no verified firmware source was reachable; see $LOG for every source tried and why each failed. \
You can stage a copy yourself at $CONFIG_ROOT/firmware-src/ (an NVIDIA-Linux-x86_64-$VERSION.run or a matching nvidia-utils package) and retry."
fi

for name in "${FILENAMES[@]}"; do
  [[ -s "$scratch/assets/$name" ]] || fail "missing generated asset after extraction: $name"
done
[[ -s "$scratch/assets/NVIDIA-LICENSE" ]] || fail "missing NVIDIA license after extraction"

mkdir -p "$OUTPUT"
for name in "${FILENAMES[@]}"; do
  cp "$scratch/assets/$name" "$OUTPUT/$name"
done
cp "$scratch/assets/NVIDIA-LICENSE" "$LICENSE"
cp "$VENDOR/NOTICE.md" "$NOTICE"
log "firmware generated locally and staged for next boot"
echo "RTX-3090-Unlock: firmware generated locally and staged for next boot"
