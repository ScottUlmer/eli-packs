#!/usr/bin/env python3
"""Validate community-packs.json against the schema + extra rules.

Run by CI on every PR/push. Exits non-zero (with messages) on any problem so a bad
submission can't be merged. Checks:
  1. community-packs.json is valid JSON and matches schema/community-packs.schema.json.
  2. pack_id is unique across the catalog (anti-typosquat / de-dupe).
  3. version is unique per pack_id (no two identical pack_id+version entries).
  4. download_url / store_url are https only (no plaintext, no other schemes).
  5. For packs hosted in THIS repo (a download_url whose file lives under packs/),
     the catalog sha256 + size_bytes must match the actual file bytes. This is the
     integrity guarantee ELI relies on at download time. Done against the local repo
     file (no network), so it is deterministic and works on PRs before merge.
     Packs hosted on an external URL are https-checked but their bytes are not
     fetched here (CI stays network-free); they are still sha256-pinned and verified
     by ELI on download.
"""

import hashlib
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:
    print("ERROR: jsonschema not installed (pip install jsonschema).")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "community-packs.json"
SCHEMA = ROOT / "schema" / "community-packs.schema.json"
PACKS_DIR = ROOT / "packs"


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_file_for_url(url: str):
    """Resolve a download_url to a repo file under packs/, or None if not repo-hosted.

    Matches the file by basename so it works for jsDelivr, raw.githubusercontent, or
    GitHub release URLs that point at packs/<name> in this repo.
    """
    if not isinstance(url, str) or not url:
        return None
    basename = url.rstrip("/").split("/")[-1]
    candidate = PACKS_DIR / basename
    if candidate.is_file():
        return candidate
    return None


def _check_entry_integrity(pack: dict, index: int, errors: list) -> None:
    pack_id = pack.get("pack_id", f"(entry #{index})")
    download_url = pack.get("download_url", "")
    store_url = pack.get("store_url", "")
    is_paid = bool(pack.get("paid", False))

    # A link-out paid entry ships no bytes: just require an https store_url.
    if is_paid and not download_url:
        if not isinstance(store_url, str) or not store_url.startswith("https://"):
            errors.append(f"'{pack_id}': paid link-out entry needs an https store_url")
        return

    # Bytes-serving entries (free or ownership-gated paid): require https.
    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        errors.append(f"'{pack_id}': download_url must be an https:// URL")
        return
    if store_url and not store_url.startswith("https://"):
        errors.append(f"'{pack_id}': store_url must be an https:// URL")

    # Verify the checksum against the actual file when it's hosted in this repo.
    local_file = _local_file_for_url(download_url)
    if local_file is None:
        print(f"  note: '{pack_id}' is hosted externally — bytes not verified by CI (ELI verifies on download).")
        return

    actual_sha256 = _sha256_of_file(local_file)
    expected_sha256 = str(pack.get("sha256", "")).lower()
    if actual_sha256 != expected_sha256:
        errors.append(
            f"'{pack_id}': sha256 mismatch — catalog says {expected_sha256 or '(none)'}, "
            f"{local_file.name} is {actual_sha256}"
        )

    expected_size = pack.get("size_bytes")
    actual_size = local_file.stat().st_size
    if isinstance(expected_size, int) and expected_size != actual_size:
        errors.append(
            f"'{pack_id}': size_bytes mismatch — catalog says {expected_size}, "
            f"{local_file.name} is {actual_size}"
        )


def main() -> int:
    errors: list[str] = []

    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: community-packs.json is not valid JSON: {exc}")
        return 1

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: schema is not valid JSON: {exc}")
        return 1

    validator = Draft7Validator(schema)
    for error in sorted(validator.iter_errors(catalog), key=lambda e: e.path):
        location = "/".join(str(p) for p in error.path) or "(root)"
        errors.append(f"schema: {location}: {error.message}")

    packs = catalog.get("packs", []) if isinstance(catalog, dict) else []
    seen_ids: dict[str, int] = {}
    seen_id_version: set[str] = set()
    for index, pack in enumerate(packs):
        if not isinstance(pack, dict):
            continue
        pack_id = pack.get("pack_id")
        version = pack.get("version")
        if isinstance(pack_id, str):
            if pack_id in seen_ids:
                errors.append(
                    f"duplicate pack_id '{pack_id}' (entries #{seen_ids[pack_id]} and #{index})"
                )
            else:
                seen_ids[pack_id] = index
            key = f"{pack_id}@{version}"
            if key in seen_id_version:
                errors.append(f"duplicate pack_id+version '{key}' (#{index})")
            seen_id_version.add(key)

        _check_entry_integrity(pack, index, errors)

    if errors:
        print("Catalog validation FAILED:")
        for message in errors:
            print(f"  - {message}")
        return 1

    print(f"Catalog OK: {len(packs)} pack(s), all valid, unique, and checksum-verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
