#!/bin/bash
# Experimental Unraid early plugin loader for Zagitta/gpu-unlock.
# Does not change a bound or active GPU.
set -uo pipefail

readonly CONFIG_ROOT=/boot/config/plugins/RTX-3090-Unlock
readonly FIRMWARE_VERSION=610.43.03
readonly REQUIRED_FIRMWARE=(
  booter_load_ga102.bin gsp_ga10x.bin gsp_boot_ga102.bin
  gsp_boot_desc_ga102.bin v67-ga102-610.43.03.bin
)

readonly REQUIRED_AUTOLOAD_BLACKLIST=(nvidia nvidia_drm nvidia_modeset nvidia_uvm)
RESUME_NVIDIA=0

log() {
  local message="RTX-3090-Unlock: $*"
  printf '%s\n' "$message"
  { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$message" >> /var/log/gpu-unlock-unraid.log; } 2>/dev/null || true
  logger -t RTX-3090-Unlock -- "$*" 2>/dev/null || true
}

has_required_blacklist() {
  local cmdline="$1" option driver modules
  local -a boot_words=()
  read -r -a boot_words <<< "$cmdline"
  for option in "${boot_words[@]}"; do
    [[ "$option" == modprobe.blacklist=* ]] || continue
    modules=",${option#modprobe.blacklist=},"
    for driver in "${REQUIRED_AUTOLOAD_BLACKLIST[@]}"; do
      [[ "$modules" == *",$driver,"* ]] || return 1
    done
    return 0
  done
  return 1
}

attempt_unlock() {
  local cmdline parameter pci kernel payload module firmware_dir file vendor vermagic
  cmdline=$(< /proc/cmdline) || { log "cannot read kernel command line"; return 1; }
  if [[ ! " $cmdline " =~ [[:space:]]gpu_unlock\.targets=([^[:space:]]+) ]]; then
    log "disabled (no gpu_unlock.targets= boot parameter)"
    return 0
  fi
  parameter="${BASH_REMATCH[1]}"

  # eudev binds NVIDIA before Unraid installs plugins. The configured boot
  # entry must suppress automatic NVIDIA aliases, then we resume NVIDIA.
  if ! has_required_blacklist "$cmdline"; then
    log "missing modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm; refusing late unlock"
    return 0
  fi
  RESUME_NVIDIA=1
  if [[ ! -f "$CONFIG_ROOT/enabled" ]]; then
    log "disabled (no activation marker); normal NVIDIA initialization will resume"
    return 0
  fi
  local bdf_re='^[[:xdigit:]]{4}:[[:xdigit:]]{2}:[[:xdigit:]]{2}\.[0-7](,[[:xdigit:]]{4}:[[:xdigit:]]{2}:[[:xdigit:]]{2}\.[0-7])*$'
  if [[ "$parameter" != all && ! "$parameter" =~ $bdf_re ]]; then
    log "invalid targets; use all or full comma-separated PCI addresses"
    return 0
  fi

  kernel=$(uname -r) || return 1
  payload="$CONFIG_ROOT/payload/$kernel"
  module="$payload/gpu_unlock.ko"
  firmware_dir="$payload/firmware/gpu-unlock/$FIRMWARE_VERSION"

  if [[ ! -f "$module" ]]; then
    log "no module for running kernel $kernel; normal NVIDIA boot continues"
    return 0
  fi
  # NVIDIA/GPU Unlock must not have initialized before the early hook.
  # The upstream module checks chip IDs and skips cards already bound.
  if [[ -d /sys/module/nvidia || -d /sys/module/gpu_unlock ]]; then
    log "NVIDIA or gpu_unlock already loaded; refusing repeat"
    return 0
  fi
  for file in "${REQUIRED_FIRMWARE[@]}"; do
    if [[ ! -f "$firmware_dir/$file" ]]; then
      log "missing staged firmware $file; refusing unlock"
      return 0
    fi
  done
  if ! command -v modinfo >/dev/null 2>&1; then
    log "modinfo unavailable; refusing unverifiable module"
    return 0
  fi
  vermagic=$(modinfo -F vermagic "$module" 2>/dev/null) || return 1
  if [[ "$vermagic" != "$kernel "* ]]; then
    log "module vermagic mismatch for $kernel; refusing unlock"
    return 0
  fi

  # All safeguards satisfied: stage only this kernel's prebuilt module/firmware.
  mkdir -p "/lib/modules/$kernel/extra" "/lib/firmware/gpu-unlock/$FIRMWARE_VERSION" || return 1
  install -m 0644 "$module" "/lib/modules/$kernel/extra/gpu_unlock.ko" || return 1
  for file in "${REQUIRED_FIRMWARE[@]}"; do
    install -m 0644 "$firmware_dir/$file" "/lib/firmware/gpu-unlock/$FIRMWARE_VERSION/$file" || return 1
  done
  depmod -a "$kernel" || return 1
  log "loading gpu_unlock for upstream-eligible targets $parameter before NVIDIA"
  modprobe gpu_unlock "targets=$parameter" || return 1
  log "module loaded; check dmesg to determine whether unlock succeeded"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if ! attempt_unlock; then
    log "GPU Unlock preload failed; attempting normal NVIDIA initialization"
  fi

  # The configured boot entry blacklists eudev aliases. Restore the normal
  # driver even when the marker, payload, target, or unlock attempt is invalid.
  # A named modprobe does not apply alias blacklists unless -b is supplied.
  if (( RESUME_NVIDIA )) && [[ ! -d /sys/module/nvidia ]]; then
    if modprobe nvidia; then
      log "normal NVIDIA module initialized after GPU Unlock phase"
    else
      log "WARNING: NVIDIA module failed to initialize; restart with the original Syslinux boot entry to roll back"
    fi
  fi
  exit 0
fi
