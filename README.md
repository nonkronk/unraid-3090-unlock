# RTX 3090 Unlock for Unraid

An experimental, installable Unraid plugin based on [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
**Currently packaged for Unraid 7.3.4 (kernel 6.18.58-Unraid) and one RTX 3090 (10de:2204).**

> **Experimental — use at your own risk.** This changes kernel-level GPU initialization and boot parameters. It may cause GPU/driver failure, instability, or boot problems. Back up your Unraid flash drive and make sure you can access its boot menu or USB before installing. There is **no warranty**. Not affiliated with or endorsed by Unraid or NVIDIA.

## Install

Unraid **Plugins → Install Plugin**, then paste:

```text
https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/main/RTX-3090-Unlock.plg
```

After a successful installation, perform a **complete shutdown and power-on** when convenient.
A normal warm reboot might not fully reset the GPU. The plugin does **not** restart Unraid itself.

## Exactly what the plugin does

**At installation:**

1. Downloads the GPL-licensed `gpu_unlock.ko` compiled for the **exact** Unraid kernel.
2. On your Unraid host, downloads pinned NVIDIA input archives and generates the necessary GPU firmware locally. No NVIDIA firmware blobs are shipped with the plugin.
3. Finds exactly one RTX 3090 and rejects GPU passthrough/VFIO assignments or unsupported kernels.
4. **For a fresh, supported Syslinux configuration:** backs up `/boot/syslinux/syslinux.cfg`, adds a GPU-specific boot target and NVIDIA auto-loading blacklist to the default `Unraid OS` entry, and creates a **non-default** `Unraid OS (No GPU Unlock)` entry with its original options.
5. Stores the kernel module, generated firmware, and activation marker under `/boot/config/plugins/RTX-3090-Unlock/` on the Unraid flash drive.

**At subsequent boots:**

1. Unraid processes `RTX-3090-Unlock.plg` **before** `nvidia-driver.plg` (Unraid sorts plugin filenames).
2. The loader verifies that the target GPU is **unbound**, checks the kernel module/firmware, and attempts `gpu_unlock`.
3. It then explicitly loads the normal NVIDIA driver, including when it safely skips or fails to unlock.

The plugin does **not** flash the GPU VBIOS, change GPU clocks/power limits, stop the array, start/stop VMs, or automatically reboot.

## Verify

After the next cold power-on:

```bash
dmesg | grep -i gpu_unlock
nvidia-smi
```

A successfully loaded module does not prove the unlock worked; look for `gpu_unlock: unlocked` in the kernel messages.

## Recovery and existing installations

- **New supported installations:** the installer adds a separate `Unraid OS (No GPU Unlock)` boot option. Select it **if the boot menu remains accessible** and the GPU Unlock boot option fails. It preserves the original kernel arguments.
- **Existing manually configured installations:** the plugin can adopt a compatible existing setup **without changing Syslinux**. In this case, **no new recovery boot entry is created**. This includes the original `00-gpu-unlock` setup where no installer backup record exists.
- Other boot layouts are rejected rather than rewritten blindly. If the boot menu is inaccessible, restore the backed-up Syslinux configuration from the boot USB using another computer.

Uninstalling disables the plugin. It restores the original boot arguments and removes the extra entry **only if this installer created them and they remain unmodified**. Adopted manual configurations require manual boot-argument restoration.

**Upgrading from `00-gpu-unlock`:** install this new plugin first. Once the new plugin reports success, uninstall the old one; do not leave both installed across the next boot. If the old plugin has its own boot-setup record, the new installer will refuse automatic adoption.

## Measured RTX 3090 result (350 W)

| PyTorch 2.14.1+cu130 | GEMM throughput |
| --- | ---: |
| FP16 | **110.10 TFLOPS** |
| BF16 | **112.50 TFLOPS** |

Median of three rounds. No same-GPU stock baseline or inference speedup is claimed.

[Technical details](docs/technical.md) · [GPL-2.0-only source license](LICENSE)
