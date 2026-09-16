#!/usr/bin/env python3
"""Validate community-packs.json against the schema + extra rules.

Run by CI on every PR/push. Exits non-zero (with messages) on any problem so a bad
submission can't be merged. Checks:
  1. community-packs.json is valid JSON and matches schema/community-packs.schema.json.
  2. pack_id is unique across the catalog (anti-typosquat / de-dupe).
  3. version is unique per pack_id (no two identical pack_id+version entries).
  4. download_url / store_url are https only (no plaintext, no other schemes).
  5. For packs hosted in THIS repo (a download_url referencing packs/ in ScottUlmer/eli-packs),
     the catalog sha256 + size_bytes must match the actual file bytes. This is the
     integrity guarantee ELI relies on at download time. Done against the local repo
     file (no network), so it is deterministic and works on PRs before merge.
     Packs hosted on an external URL are https-checked but their bytes are not
     fetched here (CI stays network-free); they are still sha256-pinned and verified
     by ELI on download.
"""

import hashlib
import json
import re
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
DEFAULT_REPO_SLUG = "ScottUlmer/eli-packs"


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_file_for_url(
    url: str,
    packs_dir: Path = PACKS_DIR,
    repo_slug: str = DEFAULT_REPO_SLUG,
) -> Path | None:
    """Resolve a download_url to a repo file under packs_dir IF the URL points to this repository.

    To prevent unrelated external URLs from matching local repo files by basename alone,
    this function enforces exact recognition of supported URL formats that refer to this
    repository (default: 'ScottUlmer/eli-packs').

    Supported URL formats referencing this repository:
      1. jsDelivr CDN:
         https://cdn.jsdelivr.net/gh/<owner>/<repo>[@<ref>]/packs/<filename>
         (also accepts fastly, gcore, or testing jsdelivr subdomains)
      2. raw.githubusercontent.com:
         https://raw.githubusercontent.com/<owner>/<repo>/<ref>/packs/<filename>
      3. GitHub raw / blob / media:
         https://github.com/<owner>/<repo>/(raw|blob|media)/<ref>/packs/<filename>
      4. GitHub release downloads:
         https://github.com/<owner>/<repo>/releases/download/<tag>/[packs/]<filename>

    Returns:
      - Path to the candidate file under packs_dir if URL matches this repository.
      - None if the URL is external or does not match supported repo forms.
    """
    if not isinstance(url, str) or not url:
        return None

    slug_pattern = re.escape(repo_slug)

    patterns = [
        # jsDelivr: https://cdn.jsdelivr.net/gh/ScottUlmer/eli-packs@ref/packs/filename
        rf"^https://(?:[a-z0-9-]+\.)?jsdelivr\.net/gh/{slug_pattern}(?:@[^/]+)?/packs/(.+)$",
        # raw.githubusercontent.com: https://raw.githubusercontent.com/ScottUlmer/eli-packs/ref/packs/filename
        rf"^https://raw\.githubusercontent\.com/{slug_pattern}/[^/]+/packs/(.+)$",
        # github.com raw/blob/media: https://github.com/ScottUlmer/eli-packs/(raw|blob|media)/ref/packs/filename
        rf"^https://github\.com/{slug_pattern}/(?:raw|blob|media)/[^/]+/packs/(.+)$",
        # github.com releases: https://github.com/ScottUlmer/eli-packs/releases/download/[^/]+/(?:packs/)?(.+)$",
        rf"^https://github\.com/{slug_pattern}/releases/download/[^/]+/(?:packs/)?(.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, url, re.IGNORECASE)
        if match:
            rel_path_str = match.group(1)
            try:
                packs_dir_resolved = packs_dir.resolve()
                candidate = (packs_dir / rel_path_str).resolve()
                if candidate.is_relative_to(packs_dir_resolved):
                    return candidate
            except (ValueError, Exception):
                return None
            return None

    return None


def _check_entry_integrity(
    pack: dict,
    index: int,
    errors: list[str],
    packs_dir: Path = PACKS_DIR,
    repo_slug: str = DEFAULT_REPO_SLUG,
) -> None:
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
    local_file = _local_file_for_url(download_url, packs_dir=packs_dir, repo_slug=repo_slug)
    if local_file is None:
        print(f"  note: '{pack_id}' is hosted externally — bytes not verified by CI (ELI verifies on download).")
        return

    if not local_file.is_file():
        errors.append(f"'{pack_id}': repo-hosted pack file '{local_file.name}' not found under packs/")
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


def validate_catalog(
    catalog_path: Path = CATALOG,
    schema_path: Path = SCHEMA,
    packs_dir: Path = PACKS_DIR,
    repo_slug: str = DEFAULT_REPO_SLUG,
) -> tuple[int, list[str]]:
    errors: list[str] = []

    if not catalog_path.is_file():
        return 1, [f"ERROR: catalog file not found at {catalog_path}"]
    if not schema_path.is_file():
        return 1, [f"ERROR: schema file not found at {schema_path}"]

    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return 1, [f"ERROR: community-packs.json is not valid JSON: {exc}"]

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return 1, [f"ERROR: schema is not valid JSON: {exc}"]

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

        _check_entry_integrity(pack, index, errors, packs_dir=packs_dir, repo_slug=repo_slug)

    exit_code = 1 if errors else 0
    return exit_code, errors


def main() -> int:
    code, errors = validate_catalog()
    if errors:
        print("Catalog validation FAILED:")
        for message in errors:
            print(f"  - {message}")
        return code

    print("Catalog OK: all valid, unique, and checksum-verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
