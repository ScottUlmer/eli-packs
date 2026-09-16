import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.validate_catalog import (
    _check_entry_integrity,
    _inspect_archive_and_manifest,
    _local_file_for_url,
    _sha256_of_file,
    main,
)


def _create_zip_bytes(files_entries):
    """Utility to create an in-memory zip file from a list or dict of (filename, content) tuples/pairs."""
    import io

    buf = io.BytesIO()
    items = files_entries.items() if isinstance(files_entries, dict) else files_entries
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in items:
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    buf.seek(0)
    return buf.getvalue()


class TestValidateCatalog(unittest.TestCase):
    def test_sha256_of_file(self):
        content = b"hello world\n"
        expected = hashlib.sha256(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            self.assertEqual(_sha256_of_file(tmp_path), expected)
        finally:
            tmp_path.unlink()

    def test_local_file_for_url_recognized_and_external(self):
        self.assertEqual(_local_file_for_url("")[0], None)
        self.assertEqual(_local_file_for_url(None)[0], None)

        # Same-basename external URL must remain external (not resolved to local file)
        ext_url = "https://example.com/other-repo/eli.dnd-srd.eli-pack"
        local_file, err = _local_file_for_url(ext_url)
        self.assertIsNone(local_file)
        self.assertIsNone(err)

        # Recognized ScottUlmer/eli-packs repo URL variants pointing to existing pack
        jsdelivr_url = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/eli.dnd-srd.eli-pack"
        raw_url = "https://raw.githubusercontent.com/ScottUlmer/eli-packs/main/packs/eli.dnd-srd.eli-pack"
        gh_blob_url = "https://github.com/ScottUlmer/eli-packs/blob/main/packs/eli.dnd-srd.eli-pack"
        gh_release_url = "https://github.com/ScottUlmer/eli-packs/releases/download/v1.0.0/packs/eli.dnd-srd.eli-pack"

        for url in [jsdelivr_url, raw_url, gh_blob_url, gh_release_url]:
            f, e = _local_file_for_url(url)
            self.assertIsNotNone(f, f"Failed for URL: {url}")
            self.assertIsNone(e)
            self.assertEqual(f.name, "eli.dnd-srd.eli-pack")

    def test_local_file_for_url_path_traversal_and_ambiguous_paths(self):
        # Path traversal in URL
        url_traversal = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/../packs/eli.dnd-srd.eli-pack"
        f, e = _local_file_for_url(url_traversal)
        self.assertIsNone(f)
        self.assertIsNotNone(e)
        self.assertIn("does not point directly to 'packs/<filename>'", e)

        # Ambiguous repo path (subdirectories inside packs/)
        url_subdir = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/sub/eli.dnd-srd.eli-pack"
        f, e = _local_file_for_url(url_subdir)
        self.assertIsNone(f)
        self.assertIsNotNone(e)
        self.assertIn("does not point directly to 'packs/<filename>'", e)

        # Backslash in URL
        url_backslash = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs\\eli.dnd-srd.eli-pack"
        f, e = _local_file_for_url(url_backslash)
        self.assertIsNone(f)
        self.assertIsNotNone(e)

    def test_local_file_for_url_missing_local_file(self):
        missing_url = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/nonexistent.eli-pack"
        f, e = _local_file_for_url(missing_url)
        self.assertIsNone(f)
        self.assertIsNotNone(e)
        self.assertIn("does not exist in packs/", e)

    def test_check_entry_integrity_http_download_url(self):
        errors = []
        entry = {
            "pack_id": "test.http",
            "download_url": "http://example.com/pack.eli-pack",
        }
        _check_entry_integrity(entry, 0, errors)
        self.assertTrue(any("download_url must be an https:// URL" in e for e in errors))

    def test_check_entry_integrity_sha256_size_mismatch(self):
        errors = []
        entry = {
            "pack_id": "eli.dnd-srd",
            "version": "1.1.0",
            "content_type": "pack",
            "download_url": "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/eli.dnd-srd.eli-pack",
            "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "size_bytes": 1,
        }
        _check_entry_integrity(entry, 0, errors)
        self.assertTrue(any("sha256 mismatch" in e for e in errors))
        self.assertTrue(any("size_bytes mismatch" in e for e in errors))

    def test_archive_inspection_invalid_zip(self):
        errors = []
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(b"not a zip file")
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("failed to open zip archive" in e for e in errors))
            self.assertFalse(any("Traceback" in e or "Exception" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_excessive_entries(self):
        errors = []
        files = [(f"file_{i}.txt", "data") for i in range(105)]
        zip_bytes = _create_zip_bytes(files)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("exceeding limit of 100" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_excessive_uncompressed_size(self):
        errors = []
        # Create a zip with 11MB of uncompressed data
        big_data = b"0" * (11 * 1024 * 1024)
        zip_bytes = _create_zip_bytes([("big.txt", big_data)])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("exceeds limit of 10485760 bytes" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_duplicate_entries(self):
        errors = []
        # Create zip with duplicate file path entries
        zip_bytes = _create_zip_bytes([
            ("manifest.json", '{"pack_id": "test.pack", "pack_version": "1.0.0", "content_type": "pack"}'),
            ("file.txt", "content 1"),
            ("file.txt", "content 2"),
        ])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("duplicate archive entry path 'file.txt'" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_unsafe_member_paths(self):
        unsafe_paths = [
            "/abs/path.txt",
            "C:/win.txt",
            "..",
            "dir/../../secret.txt",
            "dir\\file.txt",
            "control\x01char.txt",
        ]
        for path in unsafe_paths:
            errors = []
            zip_bytes = _create_zip_bytes([(path, "data"), ("manifest.json", "{}")])
            with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
                tmp.write(zip_bytes)
                tmp_path = Path(tmp.name)

            try:
                pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
                _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
                self.assertTrue(
                    any("unsafe" in e or "backslash" in e or "traversal" in e or "control" in e for e in errors),
                    f"Failed to detect unsafe path: {path} (errors: {errors})"
                )
            finally:
                tmp_path.unlink()

    def test_archive_inspection_missing_or_duplicate_manifest(self):
        # Missing manifest
        errors = []
        zip_bytes = _create_zip_bytes([("content.json", "{}")])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("missing root manifest.json" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_oversized_manifest(self):
        errors = []
        big_manifest = json.dumps({"pack_id": "test.pack", "version": "1.0.0", "data": "a" * 70000})
        zip_bytes = _create_zip_bytes([("manifest.json", big_manifest)])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("manifest.json uncompressed size" in e and "exceeds limit" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_malformed_manifest(self):
        # Invalid UTF-8
        errors = []
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", b"\x80\x81\x82")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(buf.getvalue())
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("not valid UTF-8" in e for e in errors))
        finally:
            tmp_path.unlink()

        # Invalid JSON
        errors = []
        zip_bytes = _create_zip_bytes([("manifest.json", "{ invalid json")])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("not valid JSON" in e for e in errors))
        finally:
            tmp_path.unlink()

        # JSON array instead of JSON object
        errors = []
        zip_bytes = _create_zip_bytes([("manifest.json", "[]")])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("root must be a JSON object" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_archive_inspection_identity_mismatches(self):
        valid_manifest = {
            "pack_id": "test.pack",
            "pack_version": "1.0.0",
            "content_type": "pack",
        }

        # pack_id mismatch
        errors = []
        zip_bytes = _create_zip_bytes([("manifest.json", json.dumps(valid_manifest))])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "other.pack", "version": "1.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "other.pack", errors)
            self.assertTrue(any("manifest pack_id 'test.pack' does not match catalog pack_id 'other.pack'" in e for e in errors))
        finally:
            tmp_path.unlink()

        # version mismatch
        errors = []
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "2.0.0", "content_type": "pack"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("manifest version '1.0.0' does not match catalog version '2.0.0'" in e for e in errors))
        finally:
            tmp_path.unlink()

        # content_type mismatch
        errors = []
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eli-pack") as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            pack = {"pack_id": "test.pack", "version": "1.0.0", "content_type": "world"}
            _inspect_archive_and_manifest(tmp_path, pack, "test.pack", errors)
            self.assertTrue(any("manifest content_type 'pack' does not match catalog content_type 'world'" in e for e in errors))
        finally:
            tmp_path.unlink()

    def test_main_valid_catalog(self):
        self.assertEqual(main(), 0)

    def test_main_paid_linkout_valid(self):
        catalog_data = {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "test.paid",
                    "title": "Paid Pack",
                    "author": "Author",
                    "description": "Desc",
                    "version": "1.0.0",
                    "min_eli_version": "2026.01.01",
                    "content_type": "pack",
                    "paid": True,
                    "store_url": "https://store.example.com/pack",
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write(json.dumps(catalog_data))
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path):
                self.assertEqual(main(), 0)
        finally:
            tmp_path.unlink()

    def test_main_incomplete_free_entry(self):
        catalog_data = {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "test.free",
                    "title": "Free Pack",
                    "author": "Author",
                    "description": "Desc",
                    "version": "1.0.0",
                    "min_eli_version": "2026.01.01",
                    "content_type": "pack",
                    # Missing download_url and sha256
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write(json.dumps(catalog_data))
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path):
                self.assertEqual(main(), 1)
        finally:
            tmp_path.unlink()

    def test_main_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write("{ invalid json")
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path):
                self.assertEqual(main(), 1)
        finally:
            tmp_path.unlink()

    def test_main_schema_error(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write(json.dumps({"schema_version": 1, "packs": [{"invalid": "pack"}]}))
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path):
                self.assertEqual(main(), 1)
        finally:
            tmp_path.unlink()

    def test_main_duplicate_pack_id(self):
        catalog_data = {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "dup.pack",
                    "title": "Pack 1",
                    "author": "Author",
                    "description": "Desc",
                    "version": "1.0.0",
                    "min_eli_version": "2026.01.01",
                    "content_type": "pack",
                    "download_url": "https://example.com/pack1.eli-pack",
                    "sha256": "a" * 64,
                    "size_bytes": 100,
                    "license": "MIT",
                },
                {
                    "pack_id": "dup.pack",
                    "title": "Pack 2",
                    "author": "Author",
                    "description": "Desc",
                    "version": "2.0.0",
                    "min_eli_version": "2026.01.01",
                    "content_type": "pack",
                    "download_url": "https://example.com/pack2.eli-pack",
                    "sha256": "b" * 64,
                    "size_bytes": 200,
                    "license": "MIT",
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write(json.dumps(catalog_data))
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path):
                self.assertEqual(main(), 1)
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
