# Vendored upstream firmware scripts

The five files in this directory are an unmodified, byte-for-byte copy of
`firmware/` from Zagitta/gpu-unlock at the commit this project already pins
elsewhere in the codebase:

    https://github.com/Zagitta/gpu-unlock/tree/649b36c27178fdf9fcaafd767d60dfbb78b6caa2/firmware

SPDX-License-Identifier: GPL-2.0-only (as marked in each file).

They are vendored, instead of downloaded at install or boot time, so that:

- firmware preparation never depends on `raw.githubusercontent.com/Zagitta`
  being reachable or unchanged, on top of the sources these scripts already
  download (NVIDIA's own archives);
- the scripts themselves are covered by this plugin's own SHA-256 pinning
  in `RTX-3090-Unlock.plg`, the same mechanism Unraid uses to verify every
  other file it downloads.

`tests/test-vendor.py` fails CI if any of these five files drifts from the
hashes recorded below, so an update must be a deliberate, reviewed change:

    NOTICE.md                  56c8d56ca47d705de6c68a62630d42115040ab47f94fb93ca37ba74a428cb875
    artifacts-610.43.03.json   766be4acb90a9ce2448adc3eb4cead81ea142e96b614f30bde1600b74fe5a4bc
    extract_boot_assets.py     7acc5f488cd35700c499bc942a07e7d0d9b0822b1e2ad040cd34bacf99fa5986
    fetch_artifacts.py         5655e3e497b16e17e3a9c307cf733ef2207cd7a3d0be5a9d0b2c532d66abe76b
    generate_v67.py            4b41e5199c6b9968d134c43a5a42d8127d094eebfe9dca78204be4d7c8237fd0

None of this changes what firmware is produced: the bytes extracted and the
generated V67 image are identical to what the original, non-vendored scripts
produced, because they are the same scripts. See firmware/NOTICE.md (in this
directory) for the firmware's own provenance and licensing, and the main
README's Licensing section for how this plugin as a whole is licensed.
