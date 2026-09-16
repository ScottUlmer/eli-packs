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


MAX_ZIP_ENTRIES = 10000
MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_MANIFEST_SIZE = 10 * 1024 * 1024  # 10 MB


def _is_safe_member_path(name: str) -> bool:
    """Check if zip member path is safe (no zip slip, absolute paths, or escaping)."""
    if not name:
        return True
    if name.startswith("/") or name.startswith("\\") or ":" in name:
        return False
    # Standardize path separators to /
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    for part in parts:
        if part == "..":
            return False
    return True


def _validate_pack_archive(local_file: Path, pack: dict) -> list[str]:
    """Inspect local .eli-pack zip file bounds, member safety, and manifest identity."""
    errors: list[str] = []
    pack_id = pack.get("pack_id", local_file.name)

    import zipfile

    if not zipfile.is_zipfile(local_file):
        errors.append(f"'{pack_id}': local file {local_file.name} is not a valid zip archive")
        return errors

    try:
        with zipfile.ZipFile(local_file, "r") as z:
            infolist = z.infolist()
            if len(infolist) > MAX_ZIP_ENTRIES:
                errors.append(
                    f"'{pack_id}': archive exceeds entry limit ({len(infolist)} > {MAX_ZIP_ENTRIES})"
                )
                return errors

            total_uncompressed = sum(info.file_size for info in infolist)
            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE:
                errors.append(
                    f"'{pack_id}': archive exceeds uncompressed size limit "
                    f"({total_uncompressed} > {MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE} bytes)"
                )
                return errors

            # Validate path safety and check for duplicate/ambiguous member names
            seen_names = set()
            manifest_candidates = []

            for info in infolist:
                member_name = info.filename
                if not _is_safe_member_path(member_name):
                    errors.append(
                        f"'{pack_id}': archive contains unsafe member path '{member_name}'"
                    )

                # Track duplicates
                if member_name in seen_names:
                    errors.append(
                        f"'{pack_id}': archive contains duplicate entry '{member_name}'"
                    )
                seen_names.add(member_name)

                # Track manifest candidates (case-insensitive or ending with manifest.json)
                norm_lower = member_name.replace("\\", "/").lower()
                if norm_lower == "manifest.json" or norm_lower.endswith("/manifest.json"):
                    manifest_candidates.append(member_name)

            if "manifest.json" not in seen_names:
                errors.append(f"'{pack_id}': archive is missing root 'manifest.json'")
                return errors

            if len(manifest_candidates) != 1 or manifest_candidates[0] != "manifest.json":
                errors.append(
                    f"'{pack_id}': archive contains ambiguous or duplicate manifest entries ({manifest_candidates})"
                )
                return errors

            # Read and parse manifest.json
            manifest_info = z.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_SIZE:
                errors.append(
                    f"'{pack_id}': manifest.json exceeds size limit "
                    f"({manifest_info.file_size} > {MAX_MANIFEST_SIZE} bytes)"
                )
                return errors

            try:
                manifest_data = z.read("manifest.json").decode("utf-8")
                manifest = json.loads(manifest_data)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"'{pack_id}': failed to parse manifest.json: {exc}")
                return errors

            if not isinstance(manifest, dict):
                errors.append(f"'{pack_id}': manifest.json root must be a JSON object")
                return errors

            # Cross-check pack_id
            m_pack_id = manifest.get("pack_id")
            cat_pack_id = pack.get("pack_id")
            if m_pack_id != cat_pack_id:
                errors.append(
                    f"'{pack_id}': manifest pack_id mismatch — "
                    f"catalog says '{cat_pack_id}', manifest says '{m_pack_id}'"
                )

            # Cross-check version (check pack_version first, then version)
            m_version = manifest.get("pack_version") or manifest.get("version")
            cat_version = pack.get("version")
            if m_version != cat_version:
                errors.append(
                    f"'{pack_id}': manifest version mismatch — "
                    f"catalog says '{cat_version}', manifest says '{m_version}'"
                )

            # Cross-check content_type if present in manifest
            if "content_type" in manifest:
                m_content_type = manifest.get("content_type")
                cat_content_type = pack.get("content_type")
                if m_content_type != cat_content_type:
                    errors.append(
                        f"'{pack_id}': manifest content_type mismatch — "
                        f"catalog says '{cat_content_type}', manifest says '{m_content_type}'"
                    )

    except zipfile.BadZipFile:
        errors.append(f"'{pack_id}': corrupted zip archive {local_file.name}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"'{pack_id}': error reading archive {local_file.name}: {exc}")

    return errors


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

    # Validate archive manifest and member safety
    archive_errors = _validate_pack_archive(local_file, pack)
    errors.extend(archive_errors)


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
