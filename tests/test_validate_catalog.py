import hashlib
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path so scripts can be imported during pytest runs
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from scripts.validate_catalog import (
    CATALOG,
    PACKS_DIR,
    SCHEMA,
    _local_file_for_url,
    validate_catalog,
)


def _file_sha256_and_size(content: bytes) -> tuple[str, int]:
    digest = hashlib.sha256(content).hexdigest()
    return digest, len(content)


def _setup_fixture_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Helper to copy the real schema into a disposable temp dir."""
    schema_path = tmp_path / "community-packs.schema.json"
    schema_path.write_text(SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
    catalog_path = tmp_path / "community-packs.json"
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    return catalog_path, schema_path, packs_dir


def _make_pack(
    pack_id: str = "test.pack",
    version: str = "1.0.0",
    download_url: str = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/test.pack.eli-pack",
    sha256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    size_bytes: int = 0,
    **kwargs,
) -> dict:
    pack = {
        "pack_id": pack_id,
        "title": "Test Pack Title",
        "author": "Test Author",
        "description": "A valid description for testing.",
        "version": version,
        "min_eli_version": "2026.06.24",
        "content_type": "pack",
        "download_url": download_url,
        "sha256": sha256,
        "size_bytes": size_bytes,
    }
    pack.update(kwargs)
    return pack


# --- Real Catalog Integration Test ---

def test_real_catalog_validation():
    code, errors = validate_catalog(CATALOG, SCHEMA, PACKS_DIR)
    assert code == 0, f"Real catalog validation failed: {errors}"
    assert errors == []


# --- Malformed JSON and Schema Error Tests ---

def test_malformed_catalog_json(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    catalog_path.write_text("{ malformed json ...", encoding="utf-8")

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("not valid JSON" in err for err in errors)


def test_malformed_schema_json(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    catalog_path.write_text(json.dumps({"schema_version": 1, "packs": []}), encoding="utf-8")
    schema_path.write_text("invalid schema json", encoding="utf-8")

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("schema is not valid JSON" in err for err in errors)


def test_schema_validation_failures(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    # Invalid schema_version and missing required title in pack
    bad_catalog = {
        "schema_version": 99,
        "packs": [
            {
                "pack_id": "Invalid-Pack-ID!",
                "version": "1.0.0",
            }
        ],
    }
    catalog_path.write_text(json.dumps(bad_catalog), encoding="utf-8")

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("schema:" in err for err in errors)


# --- Duplicate IDs and Versions Tests ---

def test_duplicate_pack_ids(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    p1 = _make_pack(pack_id="dup.pack", version="1.0.0")
    p2 = _make_pack(pack_id="dup.pack", version="2.0.0")
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [p1, p2]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("duplicate pack_id 'dup.pack'" in err for err in errors)


def test_duplicate_pack_id_and_version(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    p1 = _make_pack(pack_id="dup.pack", version="1.0.0")
    p2 = _make_pack(pack_id="dup.pack", version="1.0.0")
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [p1, p2]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("duplicate pack_id 'dup.pack'" in err for err in errors)
    assert any("duplicate pack_id+version 'dup.pack@1.0.0'" in err for err in errors)


# --- Paid Link-Out Rules Tests ---

def test_paid_link_out_success(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    paid_pack = {
        "pack_id": "paid.pack",
        "title": "Paid Pack",
        "author": "Paid Author",
        "description": "Paid pack description.",
        "version": "1.0.0",
        "min_eli_version": "2026.06.24",
        "content_type": "pack",
        "paid": True,
        "store_url": "https://store.example.com/item/1",
    }
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [paid_pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 0, f"Paid link-out should succeed, got errors: {errors}"


def test_paid_link_out_missing_or_invalid_store_url(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    paid_pack_no_store = {
        "pack_id": "paid.pack.bad",
        "title": "Paid Pack Bad",
        "author": "Author",
        "description": "Paid pack description.",
        "version": "1.0.0",
        "min_eli_version": "2026.06.24",
        "content_type": "pack",
        "paid": True,
        "store_url": "http://insecure.example.com/item/1",
    }
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [paid_pack_no_store]}),
        encoding="utf-8",
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("schema:" in err or "needs an https store_url" in err for err in errors)


def test_paid_pack_with_download_url_and_bad_store_url(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    paid_pack = _make_pack(
        pack_id="paid.pack.download",
        paid=True,
        store_url="http://insecure-store.com/item",
        download_url="https://example.com/external.eli-pack",
    )
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [paid_pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("store_url must be an https:// URL" in err or "schema:" in err for err in errors)


# --- HTTP / Non-HTTP URLs Tests ---

def test_non_https_download_url(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    pack = _make_pack(download_url="http://insecure.com/pack.eli-pack")
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("download_url must be an https:// URL" in err or "schema:" in err for err in errors)


def test_invalid_scheme_url(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    pack = _make_pack(download_url="ftp://files.example.com/pack.eli-pack")
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("download_url must be an https:// URL" in err or "schema:" in err for err in errors)


# --- Local Hash / Size Mismatch Tests ---

def test_local_file_sha256_mismatch(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    file_path = packs_dir / "test.pack.eli-pack"
    file_bytes = b"actual file contents"
    file_path.write_bytes(file_bytes)
    actual_sha256, actual_size = _file_sha256_and_size(file_bytes)

    wrong_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
    pack = _make_pack(
        pack_id="local.mismatch",
        download_url="https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/test.pack.eli-pack",
        sha256=wrong_sha256,
        size_bytes=actual_size,
    )
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("sha256 mismatch" in err for err in errors)


def test_local_file_size_mismatch(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    file_path = packs_dir / "test.pack.eli-pack"
    file_bytes = b"actual file contents"
    file_path.write_bytes(file_bytes)
    actual_sha256, actual_size = _file_sha256_and_size(file_bytes)

    pack = _make_pack(
        pack_id="local.size.mismatch",
        download_url="https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/test.pack.eli-pack",
        sha256=actual_sha256,
        size_bytes=999999,
    )
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("size_bytes mismatch" in err for err in errors)


def test_local_repo_hosted_file_missing(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    pack = _make_pack(
        pack_id="local.missing",
        download_url="https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/nonexistent.eli-pack",
    )
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 1
    assert any("not found under packs/" in err for err in errors)


# --- Exact Repo-Host URL & External Host Behavior Tests ---

def test_local_file_for_url_recognition(tmp_path: Path):
    _, _, packs_dir = _setup_fixture_dir(tmp_path)
    pack_file = packs_dir / "my-pack.eli-pack"
    pack_file.write_bytes(b"data")

    # Recognized repo URLs pointing to ScottUlmer/eli-packs
    valid_urls = [
        "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/my-pack.eli-pack",
        "https://fastly.jsdelivr.net/gh/ScottUlmer/eli-packs@v1.0.0/packs/my-pack.eli-pack",
        "https://raw.githubusercontent.com/ScottUlmer/eli-packs/main/packs/my-pack.eli-pack",
        "https://github.com/ScottUlmer/eli-packs/raw/main/packs/my-pack.eli-pack",
        "https://github.com/ScottUlmer/eli-packs/blob/main/packs/my-pack.eli-pack",
        "https://github.com/ScottUlmer/eli-packs/releases/download/v1.0.0/my-pack.eli-pack",
    ]
    for url in valid_urls:
        resolved = _local_file_for_url(url, packs_dir=packs_dir)
        assert resolved == pack_file, f"Failed for repo URL: {url}"

    # External URLs (even with same filename) must NOT match local files
    unrelated_external_urls = [
        "https://cdn.jsdelivr.net/gh/otheruser/eli-packs@main/packs/my-pack.eli-pack",
        "https://raw.githubusercontent.com/otheruser/eli-packs/main/packs/my-pack.eli-pack",
        "https://github.com/otheruser/eli-packs/releases/download/v1.0.0/my-pack.eli-pack",
        "https://example.com/downloads/my-pack.eli-pack",
        "https://myhost.org/packs/my-pack.eli-pack",
    ]
    for url in unrelated_external_urls:
        resolved = _local_file_for_url(url, packs_dir=packs_dir)
        assert resolved is None, f"Unrelated URL should return None: {url}"


def test_path_traversal_url(tmp_path: Path):
    _, _, packs_dir = _setup_fixture_dir(tmp_path)
    url = "https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/../../etc/passwd"
    resolved = _local_file_for_url(url, packs_dir=packs_dir)
    assert resolved is None


def test_external_host_with_same_filename_as_local_file(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)
    local_file = packs_dir / "common.eli-pack"
    local_file.write_bytes(b"local repository file contents")

    # External pack entry pointing to unrelated repo with same filename "common.eli-pack"
    ext_pack = _make_pack(
        pack_id="external.pack",
        download_url="https://github.com/external-author/repo/releases/download/v1.0/common.eli-pack",
        sha256="1111111111111111111111111111111111111111111111111111111111111111",
        size_bytes=12345,
    )
    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [ext_pack]}), encoding="utf-8"
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    # Must succeed without attempting to check hash/size against local "common.eli-pack"
    assert code == 0, f"External pack misclassified or failed: {errors}"


# --- Successful Validation Cases ---

def test_successful_local_and_external_catalog(tmp_path: Path):
    catalog_path, schema_path, packs_dir = _setup_fixture_dir(tmp_path)

    # 1. Local repo pack
    local_file = packs_dir / "local-pack.eli-pack"
    local_bytes = b"hello local pack"
    local_file.write_bytes(local_bytes)
    local_sha256, local_size = _file_sha256_and_size(local_bytes)

    p_local = _make_pack(
        pack_id="local.pack",
        download_url="https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@main/packs/local-pack.eli-pack",
        sha256=local_sha256,
        size_bytes=local_size,
    )

    # 2. External pack
    p_external = _make_pack(
        pack_id="ext.pack",
        download_url="https://github.com/external/repo/releases/download/1.0/ext.eli-pack",
        sha256="a" * 64,
        size_bytes=500,
    )

    # 3. Paid link-out pack
    p_paid = {
        "pack_id": "paid.linkout",
        "title": "Paid Title",
        "author": "Paid Author",
        "description": "Paid pack link-out.",
        "version": "1.0.0",
        "min_eli_version": "2026.06.24",
        "content_type": "pack",
        "paid": True,
        "store_url": "https://store.example.com/buy",
    }

    catalog_path.write_text(
        json.dumps({"schema_version": 1, "packs": [p_local, p_external, p_paid]}),
        encoding="utf-8",
    )

    code, errors = validate_catalog(catalog_path, schema_path, packs_dir)
    assert code == 0, f"Validation failed for valid mixed catalog: {errors}"
    assert errors == []
