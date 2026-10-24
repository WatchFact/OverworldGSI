# OverworldGSI

**Generic Android system images built from AOSP source, plus an experimental stock-firmware conversion toolkit.**

OverworldGSI treats these as **different products**:

| Mode | Output | Generic-system-image status |
| --- | --- | --- |
| **Source GSI (recommended)** | Compiles AOSP `system.img` for a documented `gsi_*` target | Real AOSP-source GSI; not a universal boot guarantee |
| **Legacy firmware converter** | Extracts and patches a device manufacturer's firmware | Experimental device-derived conversion, **not** a certified/general-purpose GSI |

The official AOSP GSI workflow offers **Android 17 and 16** build inputs. An Android version being selectable does not establish that an individual phone's kernel, VNDK interface, graphics, radio, vendor HALs, or Treble implementation can support it.

## Build a real AOSP GSI from GitHub Actions

1. Prepare an x86_64 Linux self-hosted runner with the labels `self-hosted`, `linux`, `x64`, `overworld-large`. Google recommends **400 GB free disk and 64 GB RAM** for full AOSP source compilation. A standard GitHub Actions runner with approximately **14 GB SSD** cannot build the entire current AOSP source tree.
2. Install the AOSP prerequisites and the official Google `repo` tool on that runner, following [Google's setup instructions](https://source.android.com/docs/setup/start/requirements).
3. Under **Actions → Build genuine AOSP GSI → Run workflow**, choose `android17-release` or `android16-release`, a GSI architecture and `userdebug` or `user`.
4. The workflow downloads the official AOSP manifest, syncs sources, selects the `gsi_*` target, builds the system image, checks the output, creates an XZ-compressed image with SHA-256 checksums and source manifest, and publishes a **prerelease** when selected.

Source: [`scripts/build_aosp_gsi.sh`](scripts/build_aosp_gsi.sh). The pipeline fails when source sync, target selection, image building, image verification, or release publishing fails. No empty placeholder image is published.

### Run locally on a capable Linux machine

```bash
# After installing Git, Google's repo launcher, and the AOSP build packages:
export AOSP_BRANCH=android17-release
export AOSP_TARGET=gsi_arm64-userdebug
export AOSP_WORKDIR=/path/to/large-volume/overworld-aosp
export DIST_DIR=/path/to/overworld-output
bash scripts/build_aosp_gsi.sh
```

The resulting release includes `system.img.xz`, hashes, `build-info.json`, and `source-manifest.xml`. The source image is a **GSI**, not a prepatched Samsung/One UI system image. It should be flashed only according to the target device's supported GSI installation method after backups and unlock checks.

## Legacy firmware conversion

The existing Python pipeline remains available to experiment with extracting and adapting full factory archives, OTA payloads, Samsung TAR/LZ4, KDZ, PAC, QFIL, Sony SIN, Huawei UPDATE.APP, and supported partition filesystems. **Manufacturer features or a newer framework do not become generic just because partitions were merged.**

Read [legacy setup, CLI options, and examples](docs/legacy-firmware-conversion.md). New extraction integrity tests cover truncated payload operations, image checksums when available, decompression errors, safe archive filtering and sparse image post-processing.

The legacy tool no longer switches secure ADB properties to insecure values by default. The opt-in `--insecure-adb` flag is for controlled experiments only, **never production releases**.

## Compatibility boundaries

- **Treble/VINTF compatibility** depends on the device's vendor image, kernel, VNDK/HAL contracts and architecture. Test on actual hardware.
- **Android 17** source building is supported as a workflow option; successful runtime boot and hardware operation are **not** yet validated.
- **SELinux enforcing**, Verified Boot, camera, Wi-Fi, modem, sound and boot all require device-level testing. Do not infer them from Python unit tests or a green source build.
- Do not disable AVB or change device partitions automatically. Device-specific flashing is deliberately out of scope of a generic image builder.

## Validation

On a normal development host:

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q cli.py make.py tools tests
python -m unittest discover -s tests -v
ruff check tools/extractor/archive.py tools/extractor/postprocess.py tools/extractor/formats/payload.py tests
bash -n scripts/build_aosp_gsi.sh
```

GitHub Actions runs the lightweight tests automatically. **Running a full AOSP source build requires the large runner** and is not simulated by these tests.

## Sources and license

- [Official AOSP GSI architecture and target documentation](https://source.android.com/docs/core/tests/vts/gsi)
- [Google's AOSP build requirements](https://source.android.com/docs/setup/start/requirements)
- [Official Android GSI releases](https://developer.android.com/topic/generic-system-image/releases)
- [GitHub-hosted runner limitations](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)

Apache-2.0 repository license; see [LICENSE](LICENSE) and [NOTICE](NOTICE) for bundled components.
