# Technical reference

## Verified target and provenance

| Component | Version |
| --- | --- |
| Unraid | 7.3.4 |
| Kernel | `6.18.58-Unraid` |
| NVIDIA driver used for successful test | `615.78.08` |
| GPU | RTX 3090 GA102, PCI ID `10de:2204` |
| GPU Unlock source | `Zagitta/gpu-unlock@649b36c27178fdf9fcaafd767d60dfbb78b6caa2` |
| NVIDIA firmware source version | 610.43.03 |

The plugin downloads a prebuilt **GPL** module for this exact kernel.
To avoid distributing NVIDIA blobs, it executes upstream's pinned
firmware download and extraction scripts **on the user's host**.
That installation uses Python 3, zstd, curl and tar. Scripts refuse to
configure boot until the module and firmware have been prepared.

Unraid plugin source: `RTX-3090-Unlock.plg`.
Early loader: `runtime/early-load.sh`.
Offline-tested boot preparation: `runtime/configure-boot.py`.

## Build the module/payload yourself

On Ubuntu 24.04 x86-64 or equivalent:

```bash
sudo apt-get update
sudo apt-get install -y build-essential bc bison flex libelf-dev libssl-dev \
  kmod curl jq unzip squashfs-tools xz-utils zstd ca-certificates \
  git python3 binutils
bash tests/test-static.sh
bash scripts/build-local.sh /tmp/unraid-gpu-unlock-build
```

Use a fresh absolute work directory. Output:
`/tmp/unraid-gpu-unlock-build/artifact/flash`.
The script downloads official Unraid 7.3.4 configuration and Linux 6.18.58
sources, prepares the kernel build tree, builds the upstream module, generates
firmware, and validates the offline payload. It **does not install anything
on the Unraid host**. Bitwise reproducibility is not claimed.

For a benchmark using your own installed CUDA-enabled PyTorch, run
`python3 bench/gemm.py` after GPU Unlock. It uses 8192x8192 GEMM, 15
matmul operations per round, 3 rounds, and explicit FP32 accumulation.

## Build for another Unraid kernel

Use the same Linux x86-64 build dependencies listed above. Determine the
target server's Unraid version and its exact `uname -r`, then run:

```bash
bash scripts/build-local.sh /tmp/gpu-unlock-build UNRAID_VERSION KERNEL_RELEASE
```

For example, use `7.3.4` and `6.18.58-Unraid` for the included build.
The script downloads the matching official Unraid kernel configuration,
prepares the Linux source, builds upstream's module, and validates module
metadata. The kernel sources or build can fail on some Unraid releases;
a successful build does not constitute hardware validation.

Copy only the built `gpu_unlock.ko` from
`/tmp/gpu-unlock-build/artifact/flash/config/plugins/RTX-3090-Unlock/payload/KERNEL_RELEASE/`
into the same `/boot/config/plugins/RTX-3090-Unlock/payload/KERNEL_RELEASE/`
directory on the Unraid flash before installing the plugin. The installer
then generates the required firmware locally and checks the module's
`vermagic`. No kernel build is attempted on the Unraid host.

GPU selection uses `gpu_unlock.targets=all` for fresh installations.
The upstream kernel module checks its own supported device IDs and skips
already bound cards. Existing single-device boot entries remain valid.
Passthrough-bound devices are not reassigned.

## Boot ordering

Unraid installs plugins in ASCII filename order. `RTX-3090-Unlock.plg` sorts before `nvidia-driver.plg`, so a numeric `00-` prefix is unnecessary. This ordering is part of the current compatibility contract.

On Unraid, udev can load NVIDIA before plugins run. For a fresh supported
Syslinux setup, the installer preserves the default `Unraid OS` entry and
other kernel options while adding the target PCI BDF and four NVIDIA aliases
to `modprobe.blacklist=`. It backs up the boot configuration and adds a
non-default `Unraid OS (No GPU Unlock)` entry with the original arguments.
Previously modified boot configurations are not blindly rewritten. A legacy
manual `00-gpu-unlock` setup can be adopted unchanged, but **no recovery entry
or new boot-configuration backup is created** in that case. The loader attempts
GPU Unlock **before** explicitly loading the normal NVIDIA driver.

The loader refuses nonmatching PCI addresses, a bound GPU, missing activation
marker, missing firmware, incompatible module vermagic, or a missing blacklist.
A successful module load alone is not proof of an unlock: check
`gpu_unlock: unlocked` in dmesg.

Changing Unraid kernel versions requires a matching rebuild, release,
and separate validation. There is no guarantee of benefit for quantized
LLM inference, VFIO passthrough, or other GPUs.

## Licensing

The module and Unraid adaptation are GPL-2.0-only.
NVIDIA firmware is generated locally from pinned NVIDIA input archives,
with the full NVIDIA license copied alongside it. The repository and
GitHub releases do not host NVIDIA firmware.
