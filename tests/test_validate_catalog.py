import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import functions from validate_catalog
from scripts.validate_catalog import (
    _check_entry_integrity,
    _local_file_for_url,
    _sha256_of_file,
    main,
)


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

    def test_local_file_for_url(self):
        self.assertIsNone(_local_file_for_url(""))
        self.assertIsNone(_local_file_for_url(None))
        self.assertIsNone(_local_file_for_url("https://example.com/nonexistent-file.eli-pack"))

        # Test matching existing pack in repo packs/ directory
        dnd_url = "https://github.com/ScottUlmer/eli-community-packs/releases/download/v1.0.0/eli.dnd-srd.eli-pack"
        local_file = _local_file_for_url(dnd_url)
        self.assertIsNotNone(local_file)
        self.assertTrue(local_file.is_file())
        self.assertEqual(local_file.name, "eli.dnd-srd.eli-pack")

    def test_check_entry_integrity_paid_linkout(self):
        errors = []
        paid_entry = {
            "pack_id": "test.paid",
            "paid": True,
            "store_url": "http://http-store.com/pack",  # Non-https
        }
        _check_entry_integrity(paid_entry, 0, errors)
        self.assertTrue(any("paid link-out entry needs an https store_url" in e for e in errors))

        errors.clear()
        valid_paid_entry = {
            "pack_id": "test.paid",
            "paid": True,
            "store_url": "https://store.example.com/pack",
        }
        _check_entry_integrity(valid_paid_entry, 0, errors)
        self.assertEqual(len(errors), 0)

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
            "download_url": "https://example.com/eli.dnd-srd.eli-pack",
            "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "size_bytes": 1,
        }
        _check_entry_integrity(entry, 0, errors)
        self.assertTrue(any("sha256 mismatch" in e for e in errors))
        self.assertTrue(any("size_bytes mismatch" in e for e in errors))

    def test_main_valid_catalog(self):
        self.assertEqual(main(), 0)

    def test_main_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write("{ invalid json")
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.CATALOG", tmp_path), \
                 patch("sys.stdout") as mock_stdout:
                self.assertEqual(main(), 1)
                # Verify standard output was called with non-disclosing message
                written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
                self.assertIn("ERROR: community-packs.json is not valid JSON or could not be read.", written)
                self.assertNotIn("Expecting property name", written)
        finally:
            tmp_path.unlink()

    def test_main_invalid_schema_json(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
            tmp.write("{ invalid json")
            tmp_path = Path(tmp.name)

        try:
            with patch("scripts.validate_catalog.SCHEMA", tmp_path), \
                 patch("sys.stdout") as mock_stdout:
                self.assertEqual(main(), 1)
                written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
                self.assertIn("ERROR: schema is not valid JSON or could not be read.", written)
                self.assertNotIn("Expecting property name", written)
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
