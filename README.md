<img src="icon.svg" alt="" width="96" align="right">

# GPU Unlock for Unraid

An Unraid plugin for [Zagitta's GPU Unlock](https://github.com/Zagitta/gpu-unlock), which restores full-rate FP16/BF16 Tensor Core instruction issue on eligible NVIDIA Ampere GPUs. It runs before the NVIDIA driver.

> **Tested configuration:** NVIDIA RTX 3090 on Unraid 7.3.4 (kernel `6.18.58-Unraid`). Other GPUs and Unraid versions are experimental and have not been tested with this plugin.

## Requirements

- An NVIDIA GA102 or GA104 GPU. The included module is built from upstream commit `649b36c`, which recognizes only those two chips. [Current upstream](https://github.com/Zagitta/gpu-unlock#tested-cards) adds GA103 and GA106, but this plugin does not ship that build yet.
- Unraid with the NVIDIA Driver plugin and a GPU available to the host.
- The **Python 3 for UNRAID** plugin (Apps), used when installing and uninstalling. It is not needed during boot.
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

## RTX 3090 benchmark (350 W, median of 3 runs)

| PyTorch 2.14.1+cu130 | Stock | Unlocked | Gain |
| --- | ---: | ---: | ---: |
| FP16 | 67.63 TFLOPS | **110.10 TFLOPS** | +63% |
| BF16 | 68.31 TFLOPS | **112.50 TFLOPS** | +65% |

Run it yourself, on Linux or Windows (including a VM with the GPU passed through):

```bash
python -m pip install -r bench/requirements.txt
python bench/gemm.py
```

The requirements file pulls the CUDA build of PyTorch; plain `pip install torch` on Windows is CPU-only. Compare with the stock column above: about 68 TFLOPS means the GPU is still locked.

## Limitations

- **Sleep/suspend:** the included module does not re-unlock after suspend to RAM (for example with the S3 Sleep plugin). After resume the GPU runs at the normal locked rate until the next reboot.
- **Unraid OS updates:** a new kernel needs a new module. Until one is staged, the plugin stays installed, loads the normal NVIDIA driver and shows a *GPU Unlock not active* notification.

## Uninstall

Remove the plugin under **Plugins → Installed Plugins**, then restart. The uninstaller restores the boot options it manages or refuses removal if the configuration changed unexpectedly. Fresh Syslinux installations receive a separate **Unraid OS (No GPU Unlock)** boot entry; adopted manual setups do not.

## Disclaimer

**Experimental; use at your own risk.** Kernel modules and boot settings are modified. Compatibility and stability are not guaranteed. Back up the boot flash. No warranty. Not affiliated with Unraid or NVIDIA.

[Technical details](docs/technical.md) · [License](LICENSE)
