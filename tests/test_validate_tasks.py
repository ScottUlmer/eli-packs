#!/usr/bin/env python3
"""Unit tests for native task validation (PACK-001)."""

import tempfile
import unittest
from pathlib import Path

from scripts.validate_tasks import parse_task_file, validate_all_tasks


class TestValidateTasks(unittest.TestCase):
    def test_valid_pack_001(self):
        root = Path(__file__).resolve().parent.parent
        task_path = root / "docs" / "tasks" / "PACK-001.md"
        data, errors = parse_task_file(task_path)
        self.assertEqual(errors, [])
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], "PACK-001")
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["owner"], "scott")

    def test_invalid_missing_key(self):
        with tempfile.TemporaryDirectory() as td:
            bad_task = Path(td) / "PACK-999.md"
            bad_task.write_text("---\nid: PACK-999\ntitle: Incomplete\n---\n")
            data, errors = parse_task_file(bad_task)
            self.assertIsNone(data)
            self.assertTrue(any("missing required keys" in e for e in errors))

    def test_filename_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            bad_task = Path(td) / "PACK-002.md"
            bad_task.write_text(
                "---\n"
                "id: PACK-003\n"
                "title: Mismatch\n"
                "kind: chore\n"
                "status: ready\n"
                "created: 2026-10-14\n"
                "updated: 2026-10-14\n"
                "owner: scott\n"
                "---\n"
            )
            data, errors = parse_task_file(bad_task)
            self.assertIsNone(data)
            self.assertTrue(any("filename does not match task id" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
