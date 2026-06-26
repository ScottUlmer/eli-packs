# Submitting a pack

Thanks for sharing your work. Here's how to get a pack into the ELI Workshop.

## 1. Build and host your pack

1. In ELI, open the world you want to share from, then **Tools > Export Pack**. Choose "Content pack", pick what to include, and save the `.eli-pack` file.
2. Host the file somewhere public with a direct download link. The easiest option is a **GitHub Release** on any repo of yours: create a release and attach the `.eli-pack` file, then use the asset's download URL.
3. Get the file's SHA-256. On most systems:
   - Windows (PowerShell): `Get-FileHash yourpack.eli-pack -Algorithm SHA256`
   - macOS/Linux: `shasum -a 256 yourpack.eli-pack`

## 2. Add your entry

Fork this repo and add one object to the `packs` array in `community-packs.json`. Example:

```json
{
	"pack_id": "yourname.my-pack",
	"title": "My Pack",
	"author": "Your Name",
	"description": "A short, honest description of what's inside.",
	"version": "1.0.0",
	"min_eli_version": "2026.06.24",
	"content_type": "pack",
	"download_url": "https://github.com/yourname/yourrepo/releases/download/my-pack-1.0.0/my-pack.eli-pack",
	"sha256": "<the 64-character hash from step 1>",
	"size_bytes": 123456,
	"license": "CC-BY-4.0",
	"tags": ["starter"]
}
```

Rules:

- `pack_id` must be unique in the catalog and use only lowercase letters, numbers, `.`, `-`, `_`. Prefixing it with your name (`yourname.my-pack`) avoids clashes.
- `download_url` must be `https` and point straight at the file.
- `sha256` must match the file you're hosting. ELI rejects a download whose hash doesn't match.
- `version` should match the pack's own version. Bump it when you update the pack, and update the `download_url` + `sha256` to the new file.

## 3. Open a pull request

Open a PR with your change. The PR template asks you to confirm a few things - most importantly, that **you made this pack or have the right to share it, and it contains no infringing content**. CI will check your entry against the schema. I review and merge by hand, so give me a little time.

## Updating or removing your pack

- **Update:** open a PR that changes your entry's `version`, `download_url`, and `sha256`.
- **Remove:** open a PR that deletes your entry, or email me (see TAKEDOWN.md).

## What packs may not contain

Packs are data, not software. Don't try to smuggle in anything that isn't worldbuilding content, and don't include material you don't have the rights to (commercial adventures, other people's art, etc.). Anything questionable won't be merged.
