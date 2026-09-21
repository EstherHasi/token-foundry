#!/usr/bin/env bash
# Builds release files into dist/:
#   token-foundry-<version>.plugin               Cowork / Claude Code plugin
#   token-foundry-figma-plugin-<version>.zip     Figma plugin (manifest.json, code.js, ui.html)
# Usage: bash scripts/release.sh [--skip-tests]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION=$(python3 -c "import json;print(json.load(open('.claude-plugin/plugin.json'))['version'])")
bash skills/token-push-figma/figma-plugin/build.sh >/dev/null
[ "${1:-}" = "--skip-tests" ] || bash tests/run-tests.sh
rm -rf dist && mkdir -p dist
zip -qr "dist/token-foundry-$VERSION.plugin" .claude-plugin skills README.md LICENSE -x "*.DS_Store" "*__pycache__*"
(cd skills/token-push-figma/figma-plugin && zip -q "$ROOT/dist/token-foundry-figma-plugin-$VERSION.zip" manifest.json code.js ui.html)
ls -1 dist
