#!/usr/bin/env bash
# Recover the official Unraid kernel .config and prepare vanilla matching sources.
# The resulting tree is a *build candidate* until its module is tested on Unraid.
set -euo pipefail

usage() {
  echo "Usage: $0 UNRAID_VERSION EXPECTED_KERNEL_RELEASE ABSOLUTE_NEW_DIRECTORY" >&2
  echo "Example: $0 7.3.4 6.18.58-Unraid /tmp/gpu-unlock-kernel" >&2
  exit 2
}

[[ $# -eq 3 ]] || usage
unraid_version=$1
expected_release=$2
destination=$3
[[ "$unraid_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage
[[ "$expected_release" =~ ^[0-9]+\.[0-9]+\.[0-9]+-Unraid$ ]] || usage
[[ "$destination" = /* && ! -e "$destination" ]] || usage
for command in curl jq unzip unsquashfs tar make; do
  command -v "$command" >/dev/null || { echo "Missing build dependency: $command" >&2; exit 1; }
done

base_version=${expected_release%-Unraid}
major_version=${base_version%%.*}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

feed=$(curl -fsSL --retry 3 https://releases.unraid.net/json)
release_url=$(jq -r --arg v "$unraid_version" '.[] | select(.version == $v) | .url' <<< "$feed" | head -n 1)
[[ "$release_url" == https://* ]] || { echo "Official release feed has no HTTPS URL for $unraid_version" >&2; exit 1; }
echo "Downloading official Unraid $unraid_version release bundle..."
curl -fL --retry 3 -o "$work/unraid.zip" "$release_url"
unzip -p "$work/unraid.zip" bzmodules > "$work/bzmodules"
unsquashfs -f -d "$work/squashfs" "$work/bzmodules" "src/linux-$expected_release/config" >/dev/null
config="$work/squashfs/src/linux-$expected_release/config"
[[ -s "$config" ]] || { echo "Matching Unraid kernel config was not found" >&2; exit 1; }

echo "Downloading Linux $base_version sources..."
curl -fL --retry 3 -o "$work/kernel.tar.xz" "https://cdn.kernel.org/pub/linux/kernel/v$major_version.x/linux-$base_version.tar.xz"
mkdir -p "$destination"
tar -xf "$work/kernel.tar.xz" -C "$destination"
kernel_dir="$destination/linux-$base_version"
install -m 0644 "$config" "$kernel_dir/.config"
touch "$kernel_dir/.scmversion"
(
  cd "$kernel_dir"
  ./scripts/config --file .config --disable LOCALVERSION_AUTO --set-str LOCALVERSION "-Unraid"
  make -j"$(nproc)" olddefconfig
  make -j"$(nproc)" modules_prepare
)
actual_release=$(make -s -C "$kernel_dir" kernelrelease)
[[ "$actual_release" == "$expected_release" ]] || {
  echo "Kernel release mismatch: expected $expected_release; produced $actual_release" >&2
  exit 1
}
echo "Prepared matching build candidate at $kernel_dir"
