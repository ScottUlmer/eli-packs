#!/usr/bin/env python3
"""Validate native task records in docs/tasks/ (PACK-001).

Zero external dependencies; runs on pure Python 3.10+ standard library.
Enforces strict frontmatter formatting, known keys, required types, and
task ID correspondence.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TASK_ID_RE = re.compile(r"^PACK-[0-9]{3,}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

REQUIRED_KEYS = frozenset({"id", "title", "kind", "status", "created", "updated", "owner"})
OPTIONAL_KEYS = frozenset({
    "pack_id", "model", "effort", "subagents", "reviewer",
    "dependencies", "blocked_on", "commits", "verified_by",
})
KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS

VALID_KINDS = frozenset({"pack-add", "pack-update", "schema-update", "governance", "chore", "incident"})
VALID_STATUSES = frozenset({"ready", "in-progress", "blocked", "done", "verified"})
VALID_EFFORTS = frozenset({"low", "medium", "high"})
VALID_SUBAGENTS = frozenset({"none", "optional", "required"})


def parse_task_file(path: Path) -> tuple[dict[str, str] | None, list[str]]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, [f"{path}: failed to read as UTF-8: {exc}"]

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, [f"{path}: missing opening '---' frontmatter delimiter"]

    frontmatter_lines: list[str] = []
    closing_idx = -1
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_idx = idx
            break
        frontmatter_lines.append(line)

    if closing_idx == -1:
        return None, [f"{path}: missing closing '---' frontmatter delimiter"]

    data: dict[str, str] = {}
    for line_no, raw_line in enumerate(frontmatter_lines, start=2):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in raw_line:
            errors.append(f"{path}:{line_no}: invalid line (missing colon): {raw_line!r}")
            continue
        key, val = raw_line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key in data:
            errors.append(f"{path}:{line_no}: duplicate key: {key!r}")
        data[key] = val

    # Validate keys
    unknown_keys = set(data.keys()) - KNOWN_KEYS
    if unknown_keys:
        errors.append(f"{path}: unknown frontmatter keys: {sorted(unknown_keys)}")

    missing_required = REQUIRED_KEYS - set(data.keys())
    if missing_required:
        errors.append(f"{path}: missing required keys: {sorted(missing_required)}")

    task_id = data.get("id", "")
    if not TASK_ID_RE.fullmatch(task_id):
        errors.append(f"{path}: invalid id format: {task_id!r} (must match ^PACK-[0-9]{{3,}}$)")
    elif path.name != f"{task_id}.md":
        errors.append(f"{path}: filename does not match task id {task_id}.md")

    if not data.get("title", ""):
        errors.append(f"{path}: empty title")

    kind = data.get("kind", "")
    if kind and kind not in VALID_KINDS:
        errors.append(f"{path}: invalid kind: {kind!r} (expected one of {sorted(VALID_KINDS)})")

    status = data.get("status", "")
    if status and status not in VALID_STATUSES:
        errors.append(f"{path}: invalid status: {status!r} (expected one of {sorted(VALID_STATUSES)})")

    for date_field in ("created", "updated"):
        val = data.get(date_field, "")
        if val and not DATE_RE.fullmatch(val):
            errors.append(f"{path}: invalid {date_field} date format: {val!r} (must be YYYY-MM-DD)")

    if "effort" in data and data["effort"] not in VALID_EFFORTS:
        errors.append(f"{path}: invalid effort: {data['effort']!r}")

    if "subagents" in data and data["subagents"] not in VALID_SUBAGENTS:
        errors.append(f"{path}: invalid subagents: {data['subagents']!r}")

    return data if not errors else None, errors


def validate_all_tasks(tasks_dir: Path) -> int:
    if not tasks_dir.is_dir():
        print(f"ERROR: {tasks_dir} is not a directory", file=sys.stderr)
        return 1

    task_files = sorted(tasks_dir.glob("*.md"))
    valid_count = 0
    total_errors: list[str] = []

    for task_file in task_files:
        if task_file.name.startswith("_"):
            continue
        data, errs = parse_task_file(task_file)
        if errs:
            total_errors.extend(errs)
        else:
            valid_count += 1

    if total_errors:
        print(f"FAILED: {len(total_errors)} errors found in {len(task_files)} task files:", file=sys.stderr)
        for err in total_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK: {valid_count} native task records validated cleanly in {tasks_dir}.")
    return 0


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent / "docs" / "tasks"
    sys.exit(validate_all_tasks(base_dir))
