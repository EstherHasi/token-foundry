---
name: token-audit
description: >
  This skill should be used when the user asks to "audit my design tokens", "audit these Figma variables",
  "check my tokens CSS", "are my tokens accessible", "are my tokens AI-ready", "clean up my variables",
  "rebuild the tokens CSS", or shares a tokens/variables CSS file, a Figma variables JSON export or a Figma
  file link and wants a review plus a regenerated token file. Audits structure, WCAG 2.2 AA contrast and
  AI-readiness, writes a one-page report, and generates a new CSS file where every semantic token
  references a primitive, plus a JSON manifest that keeps the Figma variable IDs. Works with any
  design system and any brand.
metadata:
  version: "0.2.0"
---

# Token audit

Audit a set of design tokens and produce three deliverables:

1. `token-audit-report.md`: one-page mini-report.
2. `tokens.css`: clean CSS custom properties, importable in code and (through the manifest) in Figma. Primitives hold raw values; every alias and semantic token references a primitive with `var()`.
3. `tokens.manifest.json`: machine-readable twin of the CSS with Figma variable IDs, collection and mode IDs, scopes, descriptions and code syntax. The CSS stays free of IDs.

Stay brand-agnostic. Never assume collection names, ramp names, colors or company names; derive everything from the input.

## Tooling

All deterministic work runs through `scripts/tokenkit.py` (Python 3.8+, stdlib only) in this skill's base directory. Call it as `python3 <base>/scripts/tokenkit.py <cmd>`. Subcommands: `ingest`, `audit`, `generate`. Run `-h` on any of them for flags. Work in a folder named `token-audit-<yyyy-mm-dd>/` in the outputs location (or beside the user's source file when a folder is connected).

## Workflow

### 1. Get the input

Accept any of these:

| Input | How to obtain |
|---|---|
| CSS with custom properties | Attached file or file in a connected folder. |
| Figma variables export | JSON from the Token Foundry Figma plugin (Export button), or Figma REST `GET /v1/files/:key/variables/local`. |
| Figma file link, Figma MCP connected | Load the `figma:figma-use` skill, then run `use_figma` with the contents of `../token-push-figma/figma-plugin/core.js` followed by `return await tfExport();`. Save the returned JSON as `figma-variables.json`. |
| Previous `tokens.manifest.json` | Pass it as input to re-audit, or as `--manifest` next to CSS/Figma input to recover names, IDs and CSS selectors. |

Do not use `get_variable_defs` as the source: it returns only resolved values for one node, without IDs or aliases. Read `references/ingest.md` for the export snippet, format details and CSS conventions.

### 2. Normalize

```bash
python3 tokenkit.py ingest <input> [--manifest prev.manifest.json] -o work/model.json
```

The command prints collections with their inferred tier (`primitive`, `alias`, `mapped`, `responsive`). Check the tiers. If one is wrong, rerun with `--tier "Collection=primitive"`. Ask the user only when the tier cannot be inferred with confidence.

### 3. Audit

```bash
python3 tokenkit.py audit work/model.json -o work [--pairs pairs.json]
```

Produces `work/audit.json` (all findings, contrast checks, AI criteria, fix proposals) and `work/audit.md` (full appendix). Then interpret each area:

**3a. Structure.** Invoke the `design:design-system` skill in audit mode (`/design-system audit`) and give it the collection/tier table plus the structure findings from `audit.md`. Use its Audit output (naming consistency, token coverage, priority actions) as the structure narrative; skip component completeness, which does not apply to tokens. If that skill is not available, apply `references/structure-checks.md` directly. Check IDs S1 to S10 are defined there.

**3b. Accessibility (WCAG 2.2 AA).** ARIA defines roles and states, not color. WCAG 2.2 AA is the scored standard. WCAG 3.0 is a W3C Working Draft (latest: 10 Sep 2026) whose contrast method is not final; every check also carries an APCA Lc value and finding A12 lists pairs that pass 2.2 but look weak under APCA. Report these as an early warning, never as failures. Before stating WCAG 3 status in a report, check the current status on w3.org. Test color against WCAG 2.2 AA: 1.4.3 text 4.5:1 (3:1 large text), 1.4.11 non-text 3:1 for icons, interactive borders and focus indicators. The script infers pairs from token roles (on-X with X, component siblings, text/icon/border/focus against neutral surfaces, inverse with inverse). Read `references/accessibility-checks.md` for the rules and exemptions. When the inferred pairs miss real usage, write a `pairs.json` (`[{"fg": "Collection::name", "bg": "...", "min": 4.5}]`) and rerun.

**3c. AI-readiness.** Score 0 to 100 from eight weighted criteria (AI1 to AI8). Read `references/ai-readiness-checks.md` for what each criterion means and how to explain it.

### 4. Write the mini-report

Write `token-audit-report.md` in the user's language, following `references/report-template.md`. One page maximum: three scores, top findings (max 8, most severe first), what the new CSS changes automatically, and decisions that need a human. Link the full appendix `audit.md` instead of repeating it. Write short, factual sentences; avoid em dashes and filler adjectives.

### 5. Agree on changes

Two kinds of change:

- **Automatic** (no question): semantic literals become aliases of primitives. A matching primitive is reused; otherwise a new primitive is created in the closest ramp (for example `color/grey/650` between 600 and 700) and, when the alias tier mirrors that ramp, a matching alias token too. Shadows, gradients and other composite strings stay literal and are reported.
- **Decisions** (ask with AskUserQuestion, grouped, max 4 questions): contrast fixes (use `suggestions` in `audit.json`: nearest passing ramp step or minimal lightness shift; mention that changing the background is the alternative), identical states, missing mode values, renames, Figma scopes (`--infer-scopes`).

Write accepted decisions to `work/changes.json`. Supported ops: `set`, `alias`, `rename`, `add`, `describe`, `scopes`. Token refs use `Collection::name`. See `references/output-format.md`.

### 6. Generate

```bash
python3 tokenkit.py generate work/model.json -o out --changes work/changes.json [--infer-scopes] [--colors-only] [--mode-selector "Theme:Dark=.dark"]
```

Outputs `out/tokens.css`, `out/tokens.manifest.json`, `out/generate-log.json`. Mode selectors: default mode on `:root`; theme modes as `[data-theme="<mode>"]`; viewport modes as media queries; anything else as `[data-<collection>="<mode>"]`. Selectors from CSS input are preserved. Override with `--mode-selector`.

### 7. Verify

1. Re-ingest the generated CSS with its manifest and re-audit: `ingest out/tokens.css --manifest out/tokens.manifest.json`, then `audit`. Report the score change (before → after) in the report.
2. Run `generate` again on the re-ingested model: it must report `"changes": {}` (idempotent).
3. Confirm there are no `S4`, `S4b` or `S5` errors introduced by the changes.

### 8. Deliver

Deliver the report, `tokens.css` and `tokens.manifest.json` (keep `audit.md` as appendix). In one or two sentences, state the scores and the number of automatic changes. Offer the next step: import into Figma with the `token-push-figma` skill (MCP or the bundled Figma plugin), or drop `tokens.css` into the codebase. For designers who want to work without Claude, the Figma plugin runs this same audit, fix and apply flow on its own.

## Rules

- Never delete tokens. Leftovers and unused primitives are reported only.
- Never invent values for missing modes; report them as decisions.
- Keep existing Figma IDs, names and CSS names stable unless a rename is approved.
- Keep brand and company names out of generated names, comments and reports unless they come from the input.
