import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.validate_catalog as vc


def create_pack_zip(zip_path: Path, manifest_dict: dict, extra_files: dict = None) -> bytes:
    """Helper to create a temporary .eli-pack file and return its sha256 checksum."""
    if extra_files is None:
        extra_files = {"content.json": "{}"}

    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest_dict))
        for fname, content in extra_files.items():
            z.writestr(fname, content)

    digest = hashlib.sha256()
    with zip_path.open("rb") as f:
        digest.update(f.read())
    return digest.hexdigest()


def test_real_repo_catalog():
    """Verify that the actual community-packs.json catalog passes validation."""
    assert vc.main() == 0


def test_valid_pack_archive_pass(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()

    manifest = {
        "pack_id": "test.my-pack",
        "pack_version": "1.0.0",
        "content_type": "pack",
        "title": "Test Pack",
    }
    pack_file = pack_dir / "test.my-pack.eli-pack"

    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("content.json", "{}")

    pack_entry = {
        "pack_id": "test.my-pack",
        "version": "1.0.0",
        "content_type": "pack",
    }

    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert errors == []


def test_mismatched_pack_id(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    manifest = {
        "pack_id": "wrong.id",
        "version": "1.0.0",
        "content_type": "pack",
    }
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))

    pack_entry = {
        "pack_id": "expected.id",
        "version": "1.0.0",
        "content_type": "pack",
    }
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert len(errors) == 1
    assert "manifest pack_id mismatch" in errors[0]


def test_mismatched_version(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    manifest = {
        "pack_id": "test.id",
        "pack_version": "2.0.0",
        "content_type": "pack",
    }
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))

    pack_entry = {
        "pack_id": "test.id",
        "version": "1.0.0",
        "content_type": "pack",
    }
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert len(errors) == 1
    assert "manifest version mismatch" in errors[0]


def test_mismatched_content_type(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    manifest = {
        "pack_id": "test.id",
        "version": "1.0.0",
        "content_type": "world",
    }
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))

    pack_entry = {
        "pack_id": "test.id",
        "version": "1.0.0",
        "content_type": "pack",
    }
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert len(errors) == 1
    assert "manifest content_type mismatch" in errors[0]


def test_missing_manifest(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("content.json", "{}")

    pack_entry = {"pack_id": "test.id", "version": "1.0.0"}
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert any("missing root 'manifest.json'" in e for e in errors)


def test_ambiguous_or_duplicate_manifest(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    manifest = {"pack_id": "test.id", "version": "1.0.0"}
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("subdir/manifest.json", json.dumps(manifest))

    pack_entry = {"pack_id": "test.id", "version": "1.0.0"}
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert any("ambiguous or duplicate manifest entries" in e for e in errors)


def test_unsafe_member_paths(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    manifest = {"pack_id": "test.id", "version": "1.0.0"}
    with zipfile.ZipFile(pack_file, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("../evil.txt", "payload")
        z.writestr("/absolute/path.txt", "payload")

    pack_entry = {"pack_id": "test.id", "version": "1.0.0"}
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert any("unsafe member path '../evil.txt'" in e for e in errors)
    assert any("unsafe member path '/absolute/path.txt'" in e for e in errors)


def test_not_a_zip_file(tmp_path):
    pack_file = tmp_path / "test.eli-pack"
    pack_file.write_bytes(b"not a zip file at all")

    pack_entry = {"pack_id": "test.id", "version": "1.0.0"}
    errors = vc._validate_pack_archive(pack_file, pack_entry)
    assert any("is not a valid zip archive" in e for e in errors)


def test_is_safe_member_path():
    assert vc._is_safe_member_path("manifest.json") is True
    assert vc._is_safe_member_path("sub/folder/file.txt") is True
    assert vc._is_safe_member_path("../file.txt") is False
    assert vc._is_safe_member_path("sub/../file.txt") is False
    assert vc._is_safe_member_path("/abs/file.txt") is False
    assert vc._is_safe_member_path("C:\\Windows\\file.txt") is False
