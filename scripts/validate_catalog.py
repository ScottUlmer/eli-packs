#!/usr/bin/env python3
"""Validate community-packs.json against the schema + extra rules.

Run by CI on every PR/push. Exits non-zero (with messages) on any problem so a bad
submission can't be merged. Checks:
  1. community-packs.json is valid JSON and matches schema/community-packs.schema.json.
  2. pack_id is unique across the catalog (anti-typosquat / de-dupe).
  3. version is unique per pack_id (no two identical pack_id+version entries).
"""

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

    if errors:
        print("Catalog validation FAILED:")
        for message in errors:
            print(f"  - {message}")
        return 1

    print(f"Catalog OK: {len(packs)} pack(s), all valid and unique.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
