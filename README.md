# GPU Unlock for Unraid (RTX 3090)

Experimental integration of [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)
for **Unraid 7.3.4 / kernel 6.18.58-Unraid / RTX 3090**.

## Install

On your Unraid WebUI, open **Plugins → Install Plugin** and paste:

```text
https://raw.githubusercontent.com/nonkronk/unraid-gpu-unlock/main/00-gpu-unlock.plg
```

The plugin automatically:

1. Downloads the compatible GPL-licensed kernel module.
2. Downloads NVIDIA's pinned source inputs and **generates firmware locally**;
   no NVIDIA firmware is hosted in this repository or release.
3. Detects exactly one RTX 3090, creates a **non-default recovery boot entry**,
   and configures the existing default Unraid OS entry for the next startup.

**It does not reboot, unload your GPU, or stop the array.** Once installation
succeeds, perform a **full shutdown and power-on** when convenient. A warm
restart might not initialize the GPU in the required state.

**Supported/tested:** one RTX 3090 assigned to the Unraid NVIDIA driver.
Other GPUs, multiple RTX 3090s, GPU passthrough, and kernel versions outside
`6.18.58-Unraid` are not supported by this packaged installer.

## Check that it worked

On the next boot:

```bash
dmesg | grep -i 'gpu_unlock'
nvidia-smi
```

Look for `gpu_unlock: unlocked` and a working NVIDIA driver.

## Recovery / uninstall

If boot fails, select **Unraid OS GPU Unlock Recovery** at the boot menu.
The installer also saves your original Syslinux configuration on the boot USB.
Uninstalling the plugin disables it and restores the original default
boot arguments **provided that entry has not been edited in the meantime**.

## Measured result (RTX 3090, 350 W)

| PyTorch 2.14.1+cu130 | Throughput |
| --- | ---: |
| FP16 | **110.10 TFLOPS** |
| BF16 | **112.50 TFLOPS** |

Median of three matrix-multiplication rounds after GPU Unlock.
No same-card stock baseline is claimed; results depend on GPU clocks and load.

Details for maintainers: [source build and limitations](docs/technical.md).
Source license: [GPL-2.0-only](LICENSE). NVIDIA firmware retains its
own license and is generated on each user's machine.
