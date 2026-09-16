import json
import pytest
from jsonschema import Draft7Validator

from scripts import validate_catalog


def test_main_valid_catalog():
    assert validate_catalog.main() == 0


def test_strict_schema_rejects_paid_and_store_url():
    schema = json.loads(validate_catalog.SCHEMA.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    catalog_with_paid = {
        "schema_version": 1,
        "packs": [
            {
                "pack_id": "test.paid-pack",
                "title": "Paid Pack",
                "author": "Test Author",
                "description": "Test description",
                "version": "1.0.0",
                "min_eli_version": "2026.06.24",
                "content_type": "pack",
                "download_url": "https://example.com/pack.eli-pack",
                "sha256": "a" * 64,
                "paid": True,
            }
        ],
    }
    errors = list(validator.iter_errors(catalog_with_paid))
    assert len(errors) > 0
    assert "paid" in errors[0].message

    catalog_with_store_url = {
        "schema_version": 1,
        "packs": [
            {
                "pack_id": "test.store-pack",
                "title": "Store Pack",
                "author": "Test Author",
                "description": "Test description",
                "version": "1.0.0",
                "min_eli_version": "2026.06.24",
                "content_type": "pack",
                "download_url": "https://example.com/pack.eli-pack",
                "sha256": "a" * 64,
                "store_url": "https://example.com/store",
            }
        ],
    }
    errors = list(validator.iter_errors(catalog_with_store_url))
    assert len(errors) > 0
    assert "store_url" in errors[0].message


def test_non_https_download_url():
    errors = []
    pack = {
        "pack_id": "test.http-pack",
        "download_url": "http://example.com/pack.eli-pack",
    }
    validate_catalog._check_entry_integrity(pack, 0, errors)
    assert any("download_url must be an https:// URL" in err for err in errors)
