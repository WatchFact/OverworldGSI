#!/usr/bin/env python3
"""Probe a built x86_64 AOSP GSI in an Android Emulator.

This does not claim physical-device boot or Treble/VTS compliance.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ADB_SERIAL = "emulator-5554"


def adb(*arguments, timeout=10):
    try:
        result = subprocess.run(
            ["adb", "-s", ADB_SERIAL, *arguments],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def status_snapshot():
    return {
        "boot_completed": adb("shell", "getprop", "sys.boot_completed"),
        "sdk": adb("shell", "getprop", "ro.build.version.sdk"),
        "abi": adb("shell", "getprop", "ro.product.cpu.abi"),
        "fingerprint": adb("shell", "getprop", "ro.build.fingerprint"),
        "system_server_pid": adb("shell", "pidof", "system_server"),
    }


def boot_confirmed(status, expected_sdk):
    """Check Android framework startup, not merely kernel/ADB connectivity."""
    return (
        status["boot_completed"] == "1"
        and status["sdk"] == str(expected_sdk)
        and status["abi"] in ("x86_64", "x86")
        and bool(status["system_server_pid"])
    )


def probe(image, avd, sdk, report_path, timeout_seconds=900, interval=10):
    image = Path(image).resolve()
    if not image.is_file() or image.stat().st_size < 4096:
        raise ValueError(f"GSI image is missing or too small: {image}")
    if not Path(os.environ.get("ANDROID_HOME", "/invalid")).is_dir():
        raise RuntimeError("ANDROID_HOME must point to the installed Android SDK")
    if not (Path(os.environ["ANDROID_HOME"]) / "emulator" / "emulator").exists():
        raise RuntimeError("Android Emulator SDK package is not installed")

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = report_path.with_suffix(".emulator.log")
    status = {}
    report = {
        "result": "NOT_BOOTED",
        "expected_sdk": sdk,
        "image": image.name,
        "avd": avd,
        "boot_completed": False,
        "reason": "Emulator did not reach Android framework boot",
    }
    process = None
    began = time.monotonic()
    try:
        with log_path.open("wb") as log:
            command = [
                str(Path(os.environ["ANDROID_HOME"]) / "emulator" / "emulator"),
                "-avd", avd,
                "-system", str(image),
                "-port", "5554",
                "-no-window", "-no-audio", "-no-boot-anim",
                "-no-snapshot", "-wipe-data",
                "-gpu", "swiftshader_indirect",
            ]
            # Do not silently accept a different reference/system image.
            print("Booting candidate image:", image, flush=True)
            process = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT
            )
            while time.monotonic() - began < timeout_seconds:
                if process.poll() is not None:
                    report["reason"] = (
                        f"Emulator exited with code {process.returncode} "
                        "before framework boot"
                    )
                    break
                status = status_snapshot()
                if boot_confirmed(status, sdk):
                    report["result"] = "BOOTED"
                    report["boot_completed"] = True
                    report["reason"] = (
                        "sys.boot_completed=1, expected API level, and "
                        "running system_server confirmed"
                    )
                    break
                time.sleep(interval)
            else:
                report["reason"] = f"Timed out after {timeout_seconds}s"
    finally:
        report["observed"] = status
        report["elapsed_seconds"] = round(time.monotonic() - began, 2)
        report["emulator_log"] = str(log_path)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        if process is not None:
            adb("emu", "kill", timeout=5)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        # Capture recent Android logs only when the device responded to ADB.
        if status.get("sdk"):
            logcat = adb("logcat", "-d", "-t", "1000", timeout=30)
            report_path.with_suffix(".logcat.txt").write_text(logcat)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["boot_completed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-image", required=True)
    parser.add_argument("--avd", default="overworld-gsi-test")
    parser.add_argument("--expected-sdk", type=int, choices=(36, 37), required=True)
    parser.add_argument("--report", default="boot-results/boot-smoke.json")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        return probe(args.system_image, args.avd, args.expected_sdk,
                     args.report, args.timeout)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"BOOT TEST ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
