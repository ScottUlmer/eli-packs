# Native Task Schema — eli-packs

Native task records live in `docs/tasks/<ID>.md` where `<ID>` matches `^PACK-[0-9]{3,}$`.

## Frontmatter Format

Task records begin with a YAML-like strict `key: value` block bounded by `---`.
Lines are parsed strictly by splitting on the first colon `:`. Unknown keys are rejected.

## Required Fields

- `id`: Exact task ID (e.g., `PACK-001`). Must match the filename `<id>.md`.
- `title`: Non-empty single line describing the task.
- `kind`: One of:
  - `pack-add`: Addition of a new community pack
  - `pack-update`: Revision/update of an existing pack
  - `schema-update`: Evolution of catalog schema or validator rules
  - `governance`: Repository, task, or contribution governance
  - `chore`: Maintenance, CI, or dependency updates
  - `incident`: Catalog or integrity incident remediation
- `status`: One of:
  - `ready`: Eligible for implementation
  - `in-progress`: Actively under development
  - `blocked`: Blocked by dependency or external condition
  - `done`: Implemented and submitted/merged
  - `verified`: Formally verified by native owner
- `created`: ISO 8601 date (`YYYY-MM-DD`).
- `updated`: ISO 8601 date (`YYYY-MM-DD`).
- `owner`: Native owner (e.g., `scott`, `community`, `worker`).

## Optional Fields

- `pack_id`: Target pack ID in `community-packs.json` if applicable.
- `model`: Recommended execution model (e.g., `sonnet`, `gemini`, `scott`).
- `effort`: Effort level (`low`, `medium`, `high`).
- `subagents`: Delegation policy (`none`, `optional`, `required`).
- `reviewer`: Required reviewer (e.g., `scott`).
- `dependencies`: Comma-separated list or sequence of prerequisite `PACK-*` task IDs.
- `blocked_on`: Description of blocker when status is `blocked`.
- `commits`: Git commit hashes associated with task resolution.
- `verified_by`: Identity confirming verification.
