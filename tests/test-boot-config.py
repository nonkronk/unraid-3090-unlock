#!/usr/bin/env python3
"""Offline Syslinux transformation tests; never accesses /boot or a GPU."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "runtime" / "configure-boot.py"
spec = importlib.util.spec_from_file_location("gpu_unlock_boot", script)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)

ORIGINAL = """default menu.c32
menu title Unraid
timeout 50
label Unraid OS
  menu default
  kernel /bzimage
  append initrd=/bzroot modprobe.blacklist=acpi_cpufreq mitigations=auto
label Unraid OS Safe Mode
  kernel /bzimage
  append initrd=/bzroot unraidsafemode
"""


class BootConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = root / "syslinux.cfg"
        self.cfg.write_text(ORIGINAL)
        self.sysfs = root / "pci"
        self.sysfs.mkdir()
        self.plugin = root / "plugin"
        self.plugin.mkdir()
        card = self.sysfs / "0000:0a:00.0"
        card.mkdir()
        (card / "vendor").write_text("0x10de\n")
        (card / "device").write_text("0x2204\n")

    def test_configure_recovery_idempotence_and_disable(self):
        result = boot.configure(self.cfg, self.sysfs, self.plugin)
        self.assertIn("cold boot required", result)
        text = self.cfg.read_text()
        self.assertIn("gpu_unlock.targets=0000:0a:00.0", text)
        self.assertIn("modprobe.blacklist=acpi_cpufreq,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm", text)
        self.assertIn("label Unraid OS (No GPU Unlock)", text)
        self.assertIn("append initrd=/bzroot modprobe.blacklist=acpi_cpufreq mitigations=auto\n", text)
        self.assertTrue((self.plugin / "enabled").is_file())
        self.assertEqual(boot.configure(self.cfg, self.sysfs, self.plugin),
                         "GPU Unlock boot entry already configured; left unchanged")
        self.assertEqual(self.cfg.read_text(), text)
        self.assertIn("restored", boot.disable(self.cfg, self.plugin))
        self.assertNotIn("gpu_unlock.targets=", self.cfg.read_text())
        self.assertNotIn("Unraid OS (No GPU Unlock)", self.cfg.read_text())
        self.assertEqual(self.cfg.read_text(), ORIGINAL)

    def test_adopts_legacy_manual_setup_without_inventing_recovery(self):
        original = ORIGINAL.replace(
            "modprobe.blacklist=acpi_cpufreq mitigations=auto",
            "modprobe.blacklist=acpi_cpufreq,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm "
            "mitigations=auto gpu_unlock.targets=0000:0a:00.0",
        )
        self.cfg.write_text(original)
        legacy = self.plugin.parent / "00-gpu-unlock"
        legacy.mkdir()
        (legacy / "enabled").touch()
        self.assertIn("Adopted", boot.configure(self.cfg, self.sysfs, self.plugin))
        self.assertEqual(self.cfg.read_text(), original)
        self.assertTrue((self.plugin / "enabled").is_file())
        self.assertTrue((self.plugin / "adopted-legacy-boot").is_file())
        self.assertNotIn("No GPU Unlock", self.cfg.read_text())
        self.assertIn("not created", boot.disable(self.cfg, self.plugin))
        self.assertEqual(self.cfg.read_text(), original)

    def test_refuses_legacy_installer_owned_boot_record(self):
        original = ORIGINAL.replace(
            "modprobe.blacklist=acpi_cpufreq mitigations=auto",
            "modprobe.blacklist=acpi_cpufreq,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm "
            "mitigations=auto gpu_unlock.targets=0000:0a:00.0",
        )
        self.cfg.write_text(original)
        legacy = self.plugin.parent / "00-gpu-unlock"
        legacy.mkdir()
        (legacy / "enabled").touch()
        (legacy / "boot-setup.json").write_text("{}")
        with self.assertRaises(boot.SetupError):
            boot.configure(self.cfg, self.sysfs, self.plugin)
        self.assertFalse((self.plugin / "enabled").exists())
        self.assertEqual(self.cfg.read_text(), original)

    def test_multiple_cards_rejected_without_modification(self):
        card = self.sysfs / "0000:0b:00.0"
        card.mkdir()
        (card / "vendor").write_text("0x10de")
        (card / "device").write_text("0x2204")
        with self.assertRaises(boot.SetupError):
            boot.configure(self.cfg, self.sysfs, self.plugin)
        self.assertEqual(self.cfg.read_text(), ORIGINAL)
        self.assertFalse((self.plugin / "enabled").exists())

    def test_vfio_owned_card_rejected(self):
        driver = Path(self.temp.name) / "vfio-pci"
        driver.mkdir()
        (self.sysfs / "0000:0a:00.0" / "driver").symlink_to(driver)
        with self.assertRaises(boot.SetupError):
            boot.configure(self.cfg, self.sysfs, self.plugin)
        self.assertEqual(self.cfg.read_text(), ORIGINAL)

    def test_default_boot_entry_required(self):
        self.cfg.write_text(ORIGINAL.replace("  menu default\n", ""))
        with self.assertRaises(boot.SetupError):
            boot.configure(self.cfg, self.sysfs, self.plugin)


if __name__ == "__main__":
    unittest.main()
