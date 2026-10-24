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

Unraid plugin source: `00-gpu-unlock.plg`.
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

## Boot ordering

On Unraid, udev can load NVIDIA before Plugins run. The installer preserves
the default `Unraid OS` entry and other kernel options, but adds the target
PCI BDF and four NVIDIA aliases to `modprobe.blacklist=`. It creates a
non-default recovery entry containing the original boot arguments, as well
as a full boot configuration backup. The early plugin loader performs the
GPU Unlock attempt **before** explicitly loading normal NVIDIA.

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
