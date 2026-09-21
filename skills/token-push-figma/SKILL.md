---
name: token-push-figma
description: >
  This skill should be used when the user asks to "import the tokens into Figma", "push tokens.css to Figma",
  "update the Figma variables from the manifest", "sync variables with the new CSS", "export my Figma variables",
  "audit my variables inside Figma", or needs the Token Foundry Figma plugin. The bundled Figma plugin scans, audits,
  shows readable results and applies fixes on its own. Writes a token-foundry manifest into Figma variables through the
  Figma MCP (use_figma) or, without MCP, through a bundled Figma plugin. Matches variables by Figma ID,
  keeps aliases across collections, simulates before applying, never deletes, and is idempotent.
metadata:
  version: "0.2.0"
---

# Push tokens to Figma

Apply `tokens.manifest.json` (produced by the `token-audit` skill) to the variables of a Figma file. The CSS alone carries no IDs; always import the manifest. If the user only has `tokens.css`, run `token-audit` step 2 and step 6 (`ingest` then `generate`) first to produce a manifest.

Two routes run the same code (`figma-plugin/core.js` in this skill's base directory):

| Route | When | How |
|---|---|---|
| Figma MCP | Figma connector available and the user gives a file link | `use_figma` with `core.js` + a call to `tfApply` |
| Figma plugin | No MCP, no edit access through MCP, or the user prefers to run it | Import `figma-plugin/manifest.json` in Figma desktop |

Offer the route that fits; ask only when both are possible and the user has not said.

## What tfApply does

1. Collections: match by Figma ID, then by name; create missing ones; rename the first mode of a new collection; add missing modes (reports plan limits: Free 1 mode, Professional 4).
2. Variables: match by Figma ID, then `collection + name`; rename when the ID matches but the name changed; create missing ones; skip type mismatches with an error.
3. Values per mode: literal or `VARIABLE_ALIAS` by target ID (cross-collection aliases preserved); write only when different.
4. Metadata: description (only when the manifest has one), WEB code syntax, scopes (when the manifest has a list).
5. Leftovers: variables in touched collections that are not in the manifest are reported, never deleted.
6. Safety net (apply only): re-reads every variable and reports modes without value and aliases that do not resolve.

Simulation (`dryRun: true`, the default) makes no writes and treats variables that would be created as pending, so aliases to them are not reported as errors.

## Route A: Figma MCP

1. Load the `figma:figma-use` skill (mandatory before `use_figma`).
2. Read `figma-plugin/core.js` and the manifest.
3. Simulate: call `use_figma` with the full `core.js` text followed by
   ```js
   const MANIFEST = <manifest JSON inline>;
   return await tfApply(MANIFEST, { dryRun: true });
   ```
   Code runs with top-level `await`; do not wrap it in an IIFE and do not call `figma.closePlugin()`.
4. Show the summary (created, renamed, updated, unchanged, leftovers, errors). Resolve errors before applying.
5. Apply with `{ dryRun: false }`. Report `summary` and `safety.problems`.
6. Verify idempotency: run the simulation again; `summary.totalChanges` must be 0.
7. Save `idMap` (collection::name → Figma ID) back into the manifest's `figmaId` fields for new variables, so the next audit keeps them. Alternatively re-export with `tfExport()` and re-run `tokenkit ingest --manifest`.

Large manifests: if the call is too big, pass `{ only: ["CollectionName"] }` and run one collection at a time, primitives first, then alias, then mapped/responsive.

## Route B: Figma plugin (standalone, no Claude needed)

The bundled plugin runs the whole flow inside Figma with the same engine (`engine.js`, a JavaScript port of `tokenkit.py` kept in parity by `tests/parity.js`):

1. **Scan**: reads the file's local variables on open (or *Scan variables*).
2. **Audit**: structure, WCAG 2.2 AA contrast, AI-readiness, plus an informative APCA preview for the WCAG 3 draft.
3. **Read results**: *Overview* (scores, collections with editable tiers, top issues), *Findings* (plain-language explanation per finding, affected tokens), *Contrast* (swatches, ratios, APCA Lc).
4. **Fix & apply**: automatic fixes (raw values to primitives, CSS code syntax, optional scopes) and a choice per failing contrast pair (keep, nearest ramp step, minimal lightness shift). *Preview changes* simulates in Figma and shows projected scores; *Apply to Figma* writes, re-scans and shows before/after.
5. **Export**: report (.md), full audit (.md, .json), `tokens.css`, `tokens.manifest.json`, raw variables export. *Audit another source* loads a CSS file, a Figma export or a manifest and can write it into the current file.

Install for the user: Figma desktop → Plugins → Development → Import plugin from manifest → `figma-plugin/manifest.json`. Deliver `manifest.json`, `code.js` and `ui.html` (zip) when they need the files.

Sources: `core.js` (Figma API side), `shell.js` (plugin messaging), `engine.js` (audit/generate), `ui.src.html` (interface). `code.js` and `ui.html` are generated: run `bash figma-plugin/build.sh` after editing any source. When `tokenkit.py` changes, port the change to `engine.js` and run `tests/parity.js`.

## After import

Report in two sentences: what changed in Figma and any leftovers or safety problems that need a decision. Recommend binding checks on a few key components, since renamed variables keep their bindings but new variables start unbound.
