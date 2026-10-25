# RTX 3090 Unlock for Unraid

An experimental Unraid plugin that runs [GPU Unlock](https://github.com/Zagitta/gpu-unlock) on an NVIDIA RTX 3090 before the NVIDIA driver initializes.

## Compatibility

- Unraid **7.3.4** (kernel `6.18.58-Unraid`)
- One **RTX 3090** (PCI ID `10de:2204`) available to the Unraid host, not assigned to a VM
- NVIDIA Driver plugin

Other GPUs and Unraid kernel versions are not supported by this release.

## Install

1. Back up your Unraid boot flash drive.
2. Open **Plugins → Install Plugin** and enter:

   ```text
   https://raw.githubusercontent.com/nonkronk/unraid-3090-unlock/main/RTX-3090-Unlock.plg
   ```

3. Once installed, **restart Unraid**.

The installer downloads the matching GPU Unlock module, prepares the required firmware locally, and configures boot options. It does not restart Unraid automatically.

## Verify

After restarting, run in the Unraid terminal:

```bash
dmesg | grep -i gpu_unlock
nvidia-smi
```

Look for `gpu_unlock: unlocked` in the kernel log. `nvidia-smi` should also detect the GPU.

## Uninstall

Remove **RTX 3090 Unlock** from **Plugins → Installed Plugins**, then restart Unraid. The uninstaller restores the saved boot options if they have not been changed since installation. If they were changed manually, removal is refused to avoid altering an unknown configuration.

Fresh installations also provide an **Unraid OS (No GPU Unlock)** boot-menu entry for recovery.

## Disclaimer

**Experimental software. Use at your own risk.** GPU initialization and boot settings are modified; compatibility and stability are not guaranteed. Keep a backup of your boot flash drive. No warranty is provided. This project is not affiliated with Unraid or NVIDIA.

[Technical details](docs/technical.md) · [License](LICENSE)
