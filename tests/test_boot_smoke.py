"""The smoke test must never confuse ADB availability with Android startup."""
import tempfile
import unittest
from pathlib import Path

from scripts.boot_smoke import boot_confirmed, probe


class BootValidationTests(unittest.TestCase):
    @staticmethod
    def ready():
        return {
            "boot_completed": "1",
            "sdk": "37",
            "abi": "x86_64",
            "fingerprint": "aosp/example",
            "system_server_pid": "1234",
        }

    def test_reports_boot_only_when_framework_is_running(self):
        self.assertTrue(boot_confirmed(self.ready(), 37))

    def test_adb_only_does_not_count_as_boot(self):
        status = self.ready()
        status["boot_completed"] = ""
        self.assertFalse(boot_confirmed(status, 37))

    def test_kernel_boot_only_does_not_count_as_android(self):
        status = self.ready()
        status["system_server_pid"] = ""
        self.assertFalse(boot_confirmed(status, 37))

    def test_wrong_android_version_rejected(self):
        self.assertFalse(boot_confirmed(self.ready(), 36))

    def test_wrong_architecture_rejected(self):
        status = self.ready()
        status["abi"] = "arm64-v8a"
        self.assertFalse(boot_confirmed(status, 37))

    def test_missing_image_fails_before_starting_any_emulator(self):
        with tempfile.TemporaryDirectory() as root:
            image = Path(root, "nonexistent.img")
            with self.assertRaisesRegex(ValueError, "missing or too small"):
                probe(image, "test", 37, Path(root, "report.json"), 1)


if __name__ == "__main__":
    unittest.main()
