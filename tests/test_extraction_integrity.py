"""Regression tests for lossless firmware extraction.

All fixtures are tiny, synthetic images. No real firmware is distributed.
"""

import hashlib
import os
import struct
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.extractor import archive, postprocess
from tools.extractor.formats import payload, sparse


class ArchiveIntegrityTests(unittest.TestCase):
    def test_archive_member_path_restrictions(self):
        good = ("images/system.img", "foo\\bar\\product.img")
        bad = ("/etc/passwd", "../escape.img", "folder/../escape.img",
               "C:\\Windows\\system.img", "folder\\..\\escape.img")
        for path in good:
            with self.subTest(path=path):
                self.assertTrue(archive._safe_archive_member(path))
        for path in bad:
            with self.subTest(path=path):
                self.assertFalse(archive._safe_archive_member(path))

    def test_zip_filters_out_non_target_images(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "firmware.zip")
            output = os.path.join(root, "out")
            os.mkdir(output)
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("images/system.img", b"SYSTEM")
                zf.writestr("images/modem.img", b"MODEM")
            files = archive.extract_archive(
                path, output, filter_func=lambda n: n == "system.img"
            )
            self.assertEqual(len(files), 1)
            self.assertEqual(Path(files[0]).read_bytes(), b"SYSTEM")
            self.assertFalse(os.path.exists(os.path.join(output, "modem.img")))

    def test_tar_does_not_extract_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "firmware.tar")
            output = os.path.join(root, "out")
            os.mkdir(output)
            with tarfile.open(path, "w") as tf:
                symlink = tarfile.TarInfo("system.img")
                symlink.type = tarfile.SYMTYPE
                symlink.linkname = "../../outside"
                tf.addfile(symlink)
            self.assertEqual(archive.extract_archive(path, output), [])
            self.assertFalse(os.path.lexists(os.path.join(output, "system.img")))

    def test_flatten_scratch_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            scratch = os.path.join(root, "scratch")
            out = os.path.join(root, "out")
            os.mkdir(scratch)
            os.mkdir(out)
            os.mkdir(os.path.join(scratch, "nested"))
            Path(scratch, "nested", "system.img").write_bytes(b"ok")
            Path(scratch, "nested", "radio.img").write_bytes(b"skip")
            if hasattr(os, "symlink"):
                try:
                    os.symlink("/etc/passwd", os.path.join(scratch, "link.img"))
                except (OSError, NotImplementedError):
                    pass
            selected = archive._collect_scratch(
                scratch, out, lambda n: n == "system.img"
            )
            self.assertEqual(len(selected), 1)
            self.assertEqual(Path(out, "system.img").read_bytes(), b"ok")
            self.assertFalse(Path(out, "radio.img").exists())
            self.assertFalse(Path(out, "link.img").exists())


@unittest.skipIf(payload.pb is None, "protobuf unavailable")
class PayloadIntegrityTests(unittest.TestCase):
    @staticmethod
    def create_payload(path, *, data=b"ABCD", declared=4, hash_data=None,
                       partition_name="system"):
        manifest = payload.pb.DeltaArchiveManifest()
        manifest.block_size = 4
        part = manifest.partitions.add()
        part.partition_name = partition_name
        part.new_partition_info.size = 4
        if hash_data is not None:
            part.new_partition_info.hash = hashlib.sha256(hash_data).digest()
        op = part.operations.add()
        op.type = payload.OP_REPLACE
        op.data_offset = 0
        op.data_length = declared
        ext = op.dst_extents.add()
        ext.start_block = 0
        ext.num_blocks = 1
        encoded = manifest.SerializeToString()
        Path(path).write_bytes(
            b"CrAU" + struct.pack(">QQI", 2, len(encoded), 0) + encoded + data
        )

    def test_full_payload_extracts_exact_partition(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "payload.bin")
            self.create_payload(source, hash_data=b"ABCD")
            files = payload.extract_payload(source, root)
            self.assertEqual(len(files), 1)
            self.assertEqual(Path(files[0]).read_bytes(), b"ABCD")

    def test_truncated_operation_never_replaces_good_output(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "payload.bin")
            target = os.path.join(root, "system.img")
            Path(target).write_bytes(b"EXISTING")
            self.create_payload(source, data=b"AB", declared=4)
            with self.assertRaisesRegex(payload.PayloadError, "Truncated"):
                payload.extract_payload(source, root)
            self.assertEqual(Path(target).read_bytes(), b"EXISTING")
            self.assertFalse(any(x.startswith(".payload-") for x in os.listdir(root)))

    def test_wrong_hash_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "payload.bin")
            self.create_payload(source, hash_data=b"WXYZ")
            with self.assertRaisesRegex(payload.PayloadError, "SHA-256 mismatch"):
                payload.extract_payload(source, root)
            self.assertFalse(Path(root, "system.img").exists())

    def test_unsafe_partition_name_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "payload.bin")
            self.create_payload(source, partition_name="../system")
            with self.assertRaisesRegex(payload.PayloadError, "Unsafe partition"):
                payload.extract_payload(source, root)


class ZstdIntegrityTests(unittest.TestCase):
    def test_invalid_zstd_never_published(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "system.img.zst")
            destination = os.path.join(root, "system.img")
            Path(source).write_bytes(postprocess.ZSTD_MAGIC + b"not-compressed")
            with self.assertRaises(RuntimeError):
                postprocess._finalize_image(source, destination, logger=None)
            self.assertFalse(os.path.exists(destination))
            self.assertTrue(os.path.exists(source))

    def test_zstd_wrapped_sparse_is_converted_to_raw(self):
        if not postprocess.HAS_ZSTD:
            self.skipTest("zstandard unavailable")
        import zstandard

        header = struct.pack(
            sparse.SPARSE_HEADER_FORMAT,
            sparse.SPARSE_HEADER_MAGIC, 1, 0, 28, 12, 4, 1, 1, 0,
        )
        chunk = struct.pack(sparse.CHUNK_HEADER_FORMAT,
                            sparse.CHUNK_TYPE_RAW, 0, 1, 16)
        compressed = zstandard.ZstdCompressor().compress(header + chunk + b"ABCD")
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "system.img.zst")
            destination = os.path.join(root, "system.img")
            Path(source).write_bytes(compressed)
            postprocess._finalize_image(source, destination, logger=None)
            self.assertEqual(Path(destination).read_bytes(), b"ABCD")
            self.assertFalse(os.path.exists(source))


if __name__ == "__main__":
    unittest.main()
