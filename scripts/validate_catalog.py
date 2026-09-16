#!/usr/bin/env python3
"""Validate community-packs.json against the schema + extra rules.

Run by CI on every PR/push. Exits non-zero (with messages) on any problem so a bad
submission can't be merged. Checks:
  1. community-packs.json is valid JSON and matches schema/community-packs.schema.json.
  2. pack_id is unique across the catalog (anti-typosquat / de-dupe).
  3. version is unique per pack_id (no two identical pack_id+version entries).
  4. download_url is https only (no plaintext, no other schemes).
  5. For packs hosted in THIS repo (ScottUlmer/eli-packs download_url pointing to packs/<filename>),
     the catalog sha256 + size_bytes must match the actual file bytes. Done against the local repo
     file (no network), so it is deterministic and works on PRs before merge.
  6. For repo-hosted .eli-pack archives, perform bounded no-extraction inspection:
     validate ZIP structure, entry count, uncompressed size limits, safe member paths, exactly
     one root manifest.json, manifest size limits, and manifest fields matching catalog metadata.
     Packs hosted on an external URL are https-checked but their bytes are not
     fetched here (CI stays network-free); they are still sha256-pinned and verified
     by ELI on download.
"""

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from jsonschema import Draft7Validator
except ImportError:
    print("ERROR: jsonschema not installed (pip install jsonschema).")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "community-packs.json"
SCHEMA = ROOT / "schema" / "community-packs.schema.json"
PACKS_DIR = ROOT / "packs"

MAX_ZIP_ENTRIES = 100
MAX_UNCOMPRESSED_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_MANIFEST_SIZE_BYTES = 64 * 1024  # 64 KB

# Patterns matching supported ScottUlmer/eli-packs repository-host URL forms
# 1. jsDelivr: https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@<ref>/packs/<filename>
# 2. Raw GitHub: https://raw.githubusercontent.com/ScottUlmer/eli-packs/<ref>/packs/<filename>
# 3. GitHub direct/release/raw: https://github.com/ScottUlmer/eli-packs/(raw|blob|releases/download)/<ref>/packs/<filename> or similar
RE_JSDELIVR = re.compile(
    r"^https://cdn\.jsdelivr\.net/gh/ScottUlmer/eli-packs@[^/]+/(.+)$"
)
RE_RAW_GITHUB = re.compile(
    r"^https://raw\.githubusercontent\.com/ScottUlmer/eli-packs/[^/]+/(.+)$"
)
RE_GITHUB_COMMUNITY = re.compile(
    r"^https://github\.com/ScottUlmer/eli-packs/(?:raw|blob|releases/download)/[^/]+/(.+)$"
)


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_file_for_url(url: str):
    """Resolve a download_url to a repo file under packs/, or None if not repo-hosted.

    Recognizes exact supported ScottUlmer/eli-packs URL forms. Same-basename URLs
    from unrelated hosts/repos remain external. Rejects path traversal/ambiguous repo paths.
    Returns (local_file, error_msg_if_invalid_repo_path).
    """
    if not isinstance(url, str) or not url:
        return None, None

    rel_path_str = None
    m = RE_JSDELIVR.match(url)
    if m:
        rel_path_str = m.group(1)
    else:
        m = RE_RAW_GITHUB.match(url)
        if m:
            rel_path_str = m.group(1)
        else:
            m = RE_GITHUB_COMMUNITY.match(url)
            if m:
                rel_path_str = m.group(1)

    if rel_path_str is None:
        return None, None

    rel_path_str = unquote(rel_path_str)

    # Rejection of path traversal / ambiguous repo paths:
    # Must start with "packs/" and have no path traversal components (".."), backslashes, etc.
    if "\\" in rel_path_str:
        return None, "repo URL contains invalid backslash characters"

    parts = [p for p in rel_path_str.split("/") if p]
    if len(parts) != 2 or parts[0] != "packs":
        return None, f"repo URL relative path '{rel_path_str}' does not point directly to 'packs/<filename>'"

    filename = parts[1]
    if filename in (".", "..") or ".." in filename:
        return None, f"repo URL contains invalid path traversal in filename '{filename}'"

    candidate = (PACKS_DIR / filename).resolve()
    packs_dir_resolved = PACKS_DIR.resolve()

    try:
        candidate.relative_to(packs_dir_resolved)
    except ValueError:
        return None, f"repo URL path '{filename}' escapes packs directory"

    if candidate.is_file():
        return candidate, None
    else:
        return None, f"repo URL refers to '{filename}' which does not exist in packs/"


def _inspect_archive_and_manifest(local_file: Path, pack: dict, pack_id: str, errors: list) -> None:
    """Perform bounded no-extraction archive inspection and catalog metadata verification."""
    try:
        zf = zipfile.ZipFile(local_file, "r")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"'{pack_id}': failed to open zip archive {local_file.name}: {exc}")
        return

    with zf:
        infolist = zf.infolist()

        if len(infolist) > MAX_ZIP_ENTRIES:
            errors.append(
                f"'{pack_id}': archive contains {len(infolist)} entries, exceeding limit of {MAX_ZIP_ENTRIES}"
            )
            return

        total_uncompressed = sum(info.file_size for info in infolist)
        if total_uncompressed > MAX_UNCOMPRESSED_SIZE_BYTES:
            errors.append(
                f"'{pack_id}': archive uncompressed size {total_uncompressed} bytes exceeds limit of {MAX_UNCOMPRESSED_SIZE_BYTES} bytes"
            )
            return

        seen_names = set()
        manifest_infos = []

        for info in infolist:
            name = info.filename
            if name in seen_names:
                errors.append(f"'{pack_id}': duplicate archive entry path '{name}'")
                return
            seen_names.add(name)

            # Check safe member path:
            # - No absolute paths (starting with / or drive letters)
            # - No path traversal components (..)
            # - No backslashes or control characters
            if name.startswith("/") or name.startswith("\\") or re.match(r"^[a-zA-Z]:", name):
                errors.append(f"'{pack_id}': archive member '{name}' uses unsafe absolute path")
                return
            if "\\" in name:
                errors.append(f"'{pack_id}': archive member '{name}' contains backslash")
                return
            parts = name.split("/")
            if ".." in parts:
                errors.append(f"'{pack_id}': archive member '{name}' contains path traversal ('..')")
                return
            if any(ord(c) < 32 for c in name):
                errors.append(f"'{pack_id}': archive member '{name}' contains control characters")
                return

            if name == "manifest.json":
                manifest_infos.append(info)

        if len(manifest_infos) == 0:
            errors.append(f"'{pack_id}': archive missing root manifest.json")
            return
        elif len(manifest_infos) > 1:
            errors.append(f"'{pack_id}': archive contains duplicate manifest.json entries")
            return

        manifest_info = manifest_infos[0]
        if manifest_info.file_size > MAX_MANIFEST_SIZE_BYTES:
            errors.append(
                f"'{pack_id}': manifest.json uncompressed size {manifest_info.file_size} bytes exceeds limit of {MAX_MANIFEST_SIZE_BYTES} bytes"
            )
            return

        try:
            manifest_bytes = zf.read(manifest_info)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"'{pack_id}': failed reading manifest.json: {exc}")
            return

        try:
            manifest_text = manifest_bytes.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"'{pack_id}': manifest.json is not valid UTF-8")
            return

        try:
            manifest = json.loads(manifest_text)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"'{pack_id}': manifest.json is not valid JSON: {exc}")
            return

        if not isinstance(manifest, dict):
            errors.append(f"'{pack_id}': manifest.json root must be a JSON object")
            return

        # Validate authoritative fields against catalog:
        # pack_id:
        manifest_pack_id = manifest.get("pack_id")
        catalog_pack_id = pack.get("pack_id")
        if manifest_pack_id != catalog_pack_id:
            errors.append(
                f"'{pack_id}': manifest pack_id '{manifest_pack_id}' does not match catalog pack_id '{catalog_pack_id}'"
            )

        # version: manifest uses 'pack_version' (or 'version' as legacy in eli.ironsworn-srd)
        manifest_version = manifest.get("pack_version") or manifest.get("version")
        catalog_version = pack.get("version")
        if manifest_version != catalog_version:
            errors.append(
                f"'{pack_id}': manifest version '{manifest_version}' does not match catalog version '{catalog_version}'"
            )

        # content_type: manifest 'content_type' vs catalog 'content_type'
        manifest_content_type = manifest.get("content_type")
        catalog_content_type = pack.get("content_type")
        if manifest_content_type != catalog_content_type:
            errors.append(
                f"'{pack_id}': manifest content_type '{manifest_content_type}' does not match catalog content_type '{catalog_content_type}'"
            )


def _check_entry_integrity(pack: dict, index: int, errors: list) -> None:
    pack_id = pack.get("pack_id", f"(entry #{index})")
    download_url = pack.get("download_url", "")

    # Bytes-serving entries: require https.
    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        errors.append(f"'{pack_id}': download_url must be an https:// URL")
        return

    # Verify the checksum and archive structure when hosted in this repo.
    local_file, repo_err = _local_file_for_url(download_url)
    if repo_err:
        errors.append(f"'{pack_id}': invalid repo download_url path: {repo_err}")
        return

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

    _inspect_archive_and_manifest(local_file, pack, str(pack_id), errors)


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
