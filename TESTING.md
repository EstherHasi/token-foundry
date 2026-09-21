# Testing

## Automated (no Figma needed)

```bash
bash tests/run-tests.sh
```

Needs Python 3.8+ and Node 18+ (plus `npm i playwright` for the plugin UI test). Covers: Figma export and REST ingest, CSS ingest, audit findings, primitive enforcement, change ops, CSS/manifest/Figma round trips, and idempotent apply against a mocked Figma Plugin API, parity between the Python and JavaScript engines, and the full Figma plugin UI flow in headless Chromium. `tests/make-fixtures.py` rebuilds the demo Figma export.

## Manual

Use a **duplicate** of a real Figma file for steps 3 and 4.

| # | Step | Expected |
|---|---|---|
| 1 | In Cowork, attach `tests/fixtures/tokens-demo.css` and ask "audit these tokens" | One-page report, `tokens.css`, `tokens.manifest.json`, `audit.md`. Failing pairs: `text/subtle`, `focus/ring`, `button/primary/text`. |
| 2 | Repeat with your own tokens CSS | Tiers inferred correctly (ask to correct with `--tier` if not). No brand-specific assumptions in the report. |
| 3 | Figma desktop: import `skills/token-push-figma/figma-plugin/manifest.json`, run *Export variables (JSON)* on the duplicate file, attach the JSON in Cowork and ask for an audit | Manifest keeps the file's Figma IDs. |
| 4 | Plugin: load the new `tokens.manifest.json`, *Simulate*, then *Apply*, then *Simulate* again | Apply reports 0 errors; the second simulation shows 0 changes. Aliases across collections intact in the Variables panel. Nothing deleted. |
| 5 | With the Figma connector: ask "push the manifest to this Figma file" with the duplicate's link | Same result as step 4 through `use_figma`. |
| 5b | Figma plugin alone: open it on the duplicate file | Scores appear without any file handling. Findings and Contrast tabs readable. In *Fix & apply*: *Select recommended*, *Preview changes*, *Apply to Figma*. Scores update; a second preview shows 0 changes. *Export* downloads the report, CSS and manifest. |
| 6 | Put the generated `tokens.css` in a page, toggle `data-theme="dark"` on `<html>` | Mapped tokens switch; primitives unchanged. |

Report issues with: input file (or a minimal extract), the command or prompt, and `audit.json` / plugin report.
