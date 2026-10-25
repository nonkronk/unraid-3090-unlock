# GPU Unlock for Unraid

An Unraid plugin for [Zagitta's GPU Unlock](https://github.com/Zagitta/gpu-unlock), which restores full-rate FP16/BF16 Tensor Core instruction issue on eligible NVIDIA Ampere GPUs. It runs before the NVIDIA driver; no VBIOS flash is required.

> **Tested configuration:** NVIDIA RTX 3090 on Unraid 7.3.4 (kernel `6.18.58-Unraid`). Other GPUs and Unraid versions are experimental and have not been tested with this plugin.

## Requirements

- An NVIDIA Ampere GPU. [Upstream GPU Unlock](https://github.com/Zagitta/gpu-unlock#tested-cards) currently recognizes GA102, GA103, GA104 and GA106; other chips may be skipped.
- Unraid with the NVIDIA Driver plugin and a GPU available to the host.
- A `gpu_unlock.ko` module built for the **running Unraid kernel**.

The plugin includes a prebuilt module for `6.18.58-Unraid` (Unraid 7.3.4). Other Unraid kernels can be tried with a matching source-built module.

## Install

1. Back up the Unraid boot flash.
2. Open **Plugins → Install Plugin** and paste:

   ```text
   https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/main/RTX-3090-Unlock.plg
   ```

3. Restart Unraid when convenient. The installer does not restart the server.

For a different kernel, first [build a matching module](docs/technical.md#build-for-another-unraid-kernel) and stage it at `/boot/config/plugins/RTX-3090-Unlock/payload/<kernel-release>/gpu_unlock.ko` before installation.

## Verify

```bash
dmesg | grep -i gpu_unlock
nvidia-smi
```

Look for `gpu_unlock: unlocked`; `nvidia-smi` alone does not confirm the unlock.

## RTX 3090 benchmark (350 W)

| PyTorch 2.14.1+cu130 | GEMM throughput |
| --- | ---: |
| FP16 | **110.10 TFLOPS** |
| BF16 | **112.50 TFLOPS** |

Median of three rounds. No same-GPU stock baseline or inference speedup is claimed.

## Uninstall

Remove the plugin under **Plugins → Installed Plugins**, then restart. The uninstaller restores the boot options it manages or refuses removal if the configuration changed unexpectedly. Fresh Syslinux installations receive a separate **Unraid OS (No GPU Unlock)** boot entry; adopted manual setups do not.

## Disclaimer

**Experimental; use at your own risk.** Kernel modules and boot settings are modified. Compatibility and stability are not guaranteed. Back up the boot flash. No warranty. Not affiliated with Unraid or NVIDIA.

[Technical details](docs/technical.md) · [License](LICENSE)
