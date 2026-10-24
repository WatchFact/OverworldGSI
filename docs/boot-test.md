# OverworldGSI boot-verification protocol

This document distinguishes **successfully extracting/building an image** from **successfully booting Android**.

## What GitHub Actions currently verifies

The lightweight `verify-and-release.yml` workflow runs on ordinary GitHub-hosted Ubuntu runners. It checks Python syntax, Ruff, shell syntax, regression tests for archive/OTA processing and unit tests of the boot-completion decision.

**This workflow cannot establish that Android booted.** It does not contain a kernel, vendor implementation, or a bootable Android system image.

## True GSI boot test

The manually dispatched `build-aosp-gsi.yml` workflow requires a large **self-hosted** x86_64 Linux runner to download AOSP and compile the GSI. For `x86_64` variants, it then installs an AOSP Android Emulator image for the **same API level**, replaces only the emulator's system image with **the exact image just built** using `-system`, and cold-boots with wiped emulated user data.

The boot test declares `BOOTED` **only** when all conditions are true:

1. The emulator process is still running.
2. `adb shell getprop sys.boot_completed` is exactly `1`.
3. `adb shell getprop ro.build.version.sdk` matches the selected Android build (37 for Android 17, 36 for Android 16).
4. The system architecture is x86 or x86_64 and `system_server` has a live PID.

The test writes `boot-results/boot-smoke.json`, the emulator console output and, if available, a logcat tail. The workflow publishes those logs as an artifact even if the test fails. **An x86_64 image is not released when its boot probe fails.** Testing the image on actual target hardware is a separate requirement.

The Android Emulator's [documented `-system` option](https://developer.android.com/studio/run/emulator-commandline) allows substituting a custom system image. An emulator is useful for checking Android framework startup; it cannot certify Treble compatibility on different hardware.

## Hardware and limitations

- Android 17 AVDs allocate at least 4 GB RAM; the AOSP source build host requires far more.
- `arm64`, `arm` and `x86` images do **not** currently get a boot claim from this x86_64-only probe. They may be source-build verified, but are **not device boot verified**.
- Android 17 and 16 source branches and GSI build targets need a high-capacity build runner. A ~14 GB GitHub-hosted runner cannot perform a full source checkout and build.
- Reaching `sys.boot_completed=1` is a basic boot milestone, not proof of working telephony, Wi-Fi, cameras, graphics acceleration, CTS/VTS, or enforcing SELinux.

## Run against a prebuilt GSI locally

With a matching Android x86_64 AVD and host SDK installed:

```bash
python3 scripts/boot_smoke.py \
  --system-image /absolute/path/to/raw/system.img \
  --avd overworld-gsi-test \
  --expected-sdk 37 \
  --timeout 900 \
  --report boot-results/boot-smoke.json
```

The probe intentionally **fails** when the input image does not exist. It never substitutes the AVD's default system image as a fallback.

References: [AOSP GSI reference](https://source.android.com/docs/core/tests/vts/gsi), [Android Emulator command line](https://developer.android.com/studio/run/emulator-commandline), [AOSP system requirements](https://source.android.com/docs/setup/start/requirements).
