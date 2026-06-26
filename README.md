# ELI community packs

This is the catalog for the in-app pack browser ("Workshop") in [ELI](https://github.com/ScottUlmer), my collaborative worldbuilding notebook for TTRPGs and fiction.

An `.eli-pack` is a single file that bundles templates, entities, and the images they use. It is **plain data only** - a pack can't contain anything that runs, so importing one is safe. ELI reads the catalog in this repo and lets people browse and install the packs listed here.

## What's in this repo

- `community-packs.json` - the catalog ELI reads. One entry per pack.
- `schema/community-packs.schema.json` - the shape every entry must match. CI checks every change against it.
- `CONTRIBUTING.md` - how to submit a pack.
- `TAKEDOWN.md` - how to report a pack or request removal.

The pack files themselves are not stored in this repo. Each catalog entry points to a `download_url` (a GitHub Release asset or other public link) plus a `sha256` so ELI can verify the download.

## How ELI uses this

ELI fetches `community-packs.json` over a CDN, anonymously - no login, no token. When someone installs a pack, ELI downloads it from its `download_url`, checks the `sha256`, runs its own integrity and safety checks, takes a backup of the open world, and imports it.

## Submitting a pack

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: open a pull request that adds your entry to `community-packs.json`, confirm you have the right to share it, and I'll review and merge it.

## Reporting a problem

See [TAKEDOWN.md](TAKEDOWN.md) to report a pack that infringes a copyright or is otherwise a problem.
