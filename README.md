# Token Foundry

[![tests](https://github.com/EstherHasi/token-foundry/actions/workflows/test.yml/badge.svg)](https://github.com/EstherHasi/token-foundry/actions/workflows/test.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Brand-agnostic toolkit for design tokens. Works with any CSS custom-property file or any Figma variables file.

## Skills

| Skill | What it does |
|---|---|
| `token-audit` | Reads CSS or a Figma variables export, audits structure (with `design:design-system`), WCAG 2.2 AA contrast and AI-readiness, writes a one-page report, and generates `tokens.css` + `tokens.manifest.json`. |
| `token-push-figma` | Writes the manifest into Figma variables via the Figma MCP or the bundled Figma plugin. Simulate first, never deletes, idempotent. |

## Figma plugin (standalone)

`skills/token-push-figma/figma-plugin/` is a Figma plugin that does everything inside Figma, no Claude needed:

1. Scan the file's local variables.
2. Audit structure, WCAG 2.2 AA contrast and AI-readiness (with an informative APCA preview for the WCAG 3 draft).
3. Read the results: scores, findings in plain language, contrast pairs with swatches.
4. Choose fixes, preview them (simulation plus projected scores) and apply. Never deletes; a second run shows 0 changes.
5. Export the report, `tokens.css` and `tokens.manifest.json`, or audit a CSS file and write it into Figma.

Install: see [Install](#install).

## Flow

```
CSS  ─┐                                   ┌─> tokens.css            (code)
      ├─> ingest ─> audit ─> report ─> generate
Figma ┘   (IDs kept)                      └─> tokens.manifest.json  (Figma IDs) ─> token-push-figma ─> Figma
```

## Output rules

- Primitives hold raw values. Alias, mapped and responsive tokens reference primitives with `var()`.
- The CSS has no IDs. Figma variable, collection and mode IDs live in the manifest.
- Missing primitives are created in the closest ramp (for example `color/grey/650`), never invented for missing modes.
- Nothing is deleted; leftovers are reported.

## Requirements

- Python 3.8+ (stdlib only) for `skills/token-audit/scripts/tokenkit.py`.
- Optional: Figma connector (MCP) for reading and writing variables directly; otherwise use the Figma plugin in `skills/token-push-figma/figma-plugin/`.
- Optional: the `design` plugin for the `design:design-system` structure review.

## Install

- **Figma plugin**: download `token-foundry-figma-plugin-<version>.zip` from [Releases](https://github.com/EstherHasi/token-foundry/releases), unzip, then in Figma desktop - right mouse click: Plugins → Development → Import plugin from manifest → select the `manifest.json` file.
- **Cowork**: download `token-foundry-<version>.plugin` from [Releases](https://github.com/EstherHasi/token-foundry/releases), open it and accept.
- **Claude Code**:

```
/plugin marketplace add EstherHasi/token-foundry
/plugin install token-foundry@token-foundry
```

## Tests

`bash tests/run-tests.sh` (Python 3.8+, Node 18+; Playwright for the plugin UI test). Manual checklist in [TESTING.md](TESTING.md).

## Command line (no Claude needed)

```bash
python3 skills/token-audit/scripts/tokenkit.py ingest tokens.css -o work/model.json
python3 skills/token-audit/scripts/tokenkit.py audit work/model.json -o work
python3 skills/token-audit/scripts/tokenkit.py generate work/model.json -o out
```

## Releasing

1. Bump `version` in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and the `VERSION` constants in `tokenkit.py`, `engine.js` and `core.js`.
2. `bash scripts/release.sh` builds `dist/` locally and runs the tests.
3. Push a tag (`git tag v0.2.0 && git push --tags`): GitHub Actions runs the tests and publishes both files as a release.

## License

[MIT](LICENSE) © Esther SJ Diez
