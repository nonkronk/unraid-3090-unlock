# RTX 3090 Unlock for Unraid

An experimental Unraid plugin based on [Zagitta's GPU Unlock](https://github.com/Zagitta/gpu-unlock). It unlocks FP16/BF16 Tensor Core instruction throughput before the NVIDIA driver initializes, without flashing the GPU VBIOS.

## Compatibility

[Upstream GPU Unlock](https://github.com/Zagitta/gpu-unlock#tested-cards) targets several NVIDIA Ampere GPU families (GA102, GA103, GA104 and GA106), with successful results reported on multiple RTX 30-series cards.

This **Unraid plugin release** currently:

- Automates installation for one host-managed **RTX 3090** (PCI ID `10de:2204`), with the NVIDIA Driver plugin installed.
- Includes a module built for **Unraid kernel `6.18.58-Unraid`** (Unraid 7.3.4). The installer checks for this exact kernel.

Other Unraid kernel versions would need their own matching module builds and validation. **These are limits of the current plugin package, not a claim that upstream GPU Unlock cannot work on other Unraid versions or Ampere GPUs.**

## Install

1. Back up your Unraid boot flash drive.
2. Open **Plugins → Install Plugin** and enter:

   ```text
   https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/main/RTX-3090-Unlock.plg
   ```

3. After installation, restart Unraid when convenient.

The installer downloads the matching module, generates the required firmware locally and prepares the boot options. It does not restart Unraid automatically.

## Verify

After restarting, run in the Unraid terminal:

```bash
dmesg | grep -i gpu_unlock
nvidia-smi
```

Look for `gpu_unlock: unlocked` in the kernel log. `nvidia-smi` confirms that the NVIDIA driver can access the GPU; it does not by itself prove the unlock succeeded.

## Measured RTX 3090 result (350 W)

| PyTorch 2.14.1+cu130 | GEMM throughput |
| --- | ---: |
| FP16 | **110.10 TFLOPS** |
| BF16 | **112.50 TFLOPS** |

Median of three rounds on an RTX 3090 after unlocking. No same-GPU stock baseline or inference speedup is claimed.

## Uninstall and recovery

Remove **RTX 3090 Unlock** from **Plugins → Installed Plugins**, then restart Unraid. The uninstaller attempts to undo the boot options it manages before removal; it refuses to change configurations that have been modified unexpectedly.

For fresh supported Syslinux installations, the plugin adds a separate **Unraid OS (No GPU Unlock)** boot-menu entry. When adopting an existing manual unlock setup, it does **not** create an additional recovery boot entry.

## Disclaimer

**Experimental software. Use at your own risk.** GPU initialization and boot settings are modified; compatibility and stability are not guaranteed. Keep a backup of your boot flash drive. No warranty is provided. This project is not affiliated with Unraid or NVIDIA.

[Technical details](docs/technical.md) · [License](LICENSE)
