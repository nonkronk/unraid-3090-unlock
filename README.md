# GPU Unlock for Unraid (RTX 3090, experimental)

Source-only Unraid boot integration for [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
The module runs **before NVIDIA binds the GPU**, then the normal NVIDIA driver loads.
This is not a replacement NVIDIA driver, a VRAM unlock, or a vGPU feature.

**Verified on one system:** Unraid 7.3.4, kernel `6.18.58-Unraid`,
RTX 3090 (GA102), NVIDIA driver `615.78.08`. Cold boot logged
`gpu_unlock: unlocked` and NVIDIA initialized afterward. Other hardware,
kernels, and driver combinations remain untested. Low-level firmware modification
can prevent GPU initialization; prepare recovery **before** enabling.

## Tested results

At a **350 W** GPU power limit, PyTorch `2.14.1+cu130` reported:

| Operation | Measured throughput |
| --- | ---: |
| FP16 matrix multiplication | **110.10 TFLOPS** |
| BF16 matrix multiplication | **112.50 TFLOPS** |

Median of three benchmark rounds. These are **post-unlock measurements**,
not a same-card stock-versus-unlocked comparison. Results vary by clocks,
thermals and benchmarking environment. Run `bench/gemm.py` with CUDA-enabled
PyTorch for a comparable workload.

## Compatibility and safeguards

- Targets an **exactly specified NVIDIA PCI BDF**; never scans/unlocks all cards.
- Refuses an already-bound GPU, incorrect target, missing activation marker,
  missing firmware/module, wrong kernel vermagic, or missing NVIDIA blacklist.
- Explicitly loads the normal NVIDIA driver after the attempt, including skips.
- The source tree includes **no NVIDIA firmware or prebuilt kernel modules**.
  Build the payload locally; a built payload is kernel-specific.
- Do not enable when another driver, VM, or process owns the GPU.

| Build input | Tested value |
| --- | --- |
| Unraid | 7.3.4 |
| Kernel | `6.18.58-Unraid` |
| GPU | NVIDIA RTX 3090 / GA102 |
| Upstream revision | `649b36c27178fdf9fcaafd767d60dfbb78b6caa2` |
| Upstream firmware input | NVIDIA 610.43.03 |

## Build from source (Linux x86-64)

Requires Ubuntu 24.04 or comparable Linux x86-64, ample temporary disk space,
network access, and these packages:

```bash
sudo apt-get update
sudo apt-get install -y build-essential bc bison flex libelf-dev libssl-dev \
  kmod curl jq unzip squashfs-tools xz-utils zstd ca-certificates \
  git python3 binutils
```

Clone **this repository**, then use a **new, nonexistent absolute work directory**:

```bash
bash tests/test-static.sh
bash scripts/build-local.sh /tmp/unraid-gpu-unlock-build
```

This prepares official Unraid 7.3.4 kernel configuration with Linux 6.18.58
sources, checks out the pinned upstream revision, builds the x86-64 module,
extracts upstream-pinned firmware and validates the staged payload.
Output: `/tmp/unraid-gpu-unlock-build/artifact/flash/`.

The generated firmware is subject to NVIDIA's own terms; inspect the generated
`NVIDIA-LICENSE` and `FIRMWARE-NOTICE.md` before any distribution.
**Do not publicly redistribute the generated firmware/binary bundle without
independently establishing redistribution rights.** The public CI validates
source only; it does not publish generated binaries.

The source build is repeatable, but **bit-for-bit reproducibility is not claimed**
because external release packages, compilers, and build dependencies can vary.

## Install (manual, on Unraid)

**Back up the boot USB and original Syslinux configuration off-server first.**
Never use another computer's boot parameters verbatim.

1. On the target, confirm `uname -r` is `6.18.58-Unraid`. Use
   `lspci -Dnnk` to identify **your** RTX 3090's exact PCI address and confirm
   it is not in use by a VM. Other kernels require a matching rebuild.
2. Stage the **contents** of the locally built `artifact/flash/` directory
   under `/boot/`; it includes
   `/boot/config/plugins/00-gpu-unlock.plg` and
   `/boot/config/plugins/00-gpu-unlock/{runtime,payload}`.
   Review destination paths before copying so unrelated files are preserved.
3. Install the staged plugin descriptor from Unraid's Plugins interface
   or with `installplg /boot/config/plugins/00-gpu-unlock.plg`.
4. In the **existing default Unraid OS** Syslinux entry, preserve every
   original kernel argument, then append
   `gpu_unlock.targets=0000:BB:DD.F` using the GPU's **actual** PCI BDF.
   Add `nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm` to
   `modprobe.blacklist=` (merge with any existing values; use one option).
   Leave `initrd=`, the existing default entry and all unrelated settings intact.
5. Configure a separate **Unraid OS Recovery** menu entry containing the
   original, unmodified kernel arguments, **without** the target or added
   NVIDIA blacklist. Make sure the recovery entry is **not default**.
6. Create `/boot/config/plugins/00-gpu-unlock/enabled` to opt in.
   Cold power-off/power-on may be necessary for an uninitialized GPU;
   arrange maintenance access before doing so.

The early Unraid udev phase can autoload NVIDIA ahead of plugins, hence the
boot-time NVIDIA blacklist. This integration explicitly resumes NVIDIA with
`modprobe nvidia` after the unlock phase. Do not rely on the plugin
filename alone for execution order.

## Verify

After a cold boot, inspect:

```bash
uname -r
cat /proc/cmdline
tail -n 40 /var/log/gpu-unlock-unraid.log
dmesg | grep -i gpu_unlock
nvidia-smi
```

Require an explicit successful `gpu_unlock: unlocked` kernel message,
normal NVIDIA initialization, and a passing GPU workload. A loaded module
without the unlock message is **not** proof of success.

Run a disposable PyTorch benchmark using a suitable CUDA-enabled PyTorch
environment, e.g. `uv run --no-project --no-cache --no-python-downloads --with torch python bench/gemm.py`.
The benchmark changes no persistent Unraid packages; match the power limit,
CUDA/PyTorch versions, and benchmark settings for comparisons.

## Recovery

If boot or NVIDIA initialization fails, choose **Unraid OS Recovery** from
the boot menu. It uses original parameters and bypasses GPU Unlock.
If the menu is unreachable, restore the *saved original*
`/boot/syslinux/syslinux.cfg` using a second computer; do not format
the boot USB.

When booted normally, remove the `gpu_unlock.targets=` opt-in and the
four *added* NVIDIA blacklist entries from the original boot line,
then disable `/boot/config/plugins/00-gpu-unlock/enabled`.
Retain preexisting boot options. Uninstalling the plugin does not unload
an active GPU module or automatically revert Syslinux options.

## Scope

A successful RTX 3090 BF16/FP16 GEMM benchmark does not demonstrate
a benefit for quantized inference, VM passthrough, or other GPUs.
Kernel updates require a rebuilt module and revalidation.

## License and provenance

Unraid adaptation: **GPL-2.0-only**, see [LICENSE](LICENSE).
Based on [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)
(GPL-2.0-only; pinned revision above). NVIDIA firmware is independently
licensed; it is **not** included in this source repository.
