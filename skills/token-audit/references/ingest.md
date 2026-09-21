# Ingest: inputs and conventions

## Figma export (preferred source when Figma is the source of truth)

Three equivalent ways to get the same JSON (`token-foundry/figma-export@1`):

1. **Figma plugin (no MCP needed).** Import `token-push-figma/figma-plugin/manifest.json` in Figma desktop (Plugins > Development > Import plugin from manifest), run it, click *Export variables (JSON)*, download or copy, attach to the chat.
2. **Figma MCP.** Load `figma:figma-use` first. Then call `use_figma` with the full text of `core.js` followed by:
   ```js
   return await tfExport();
   ```
   Do not wrap in an IIFE; `use_figma` supports top-level `await` and `return`. Save the result to `figma-variables.json`. For very large files, export per collection by filtering `variables` in a follow-up call.
3. **REST API.** `GET https://api.figma.com/v1/files/:file_key/variables/local` (Enterprise plan). `tokenkit ingest` reads the `meta.variables` / `meta.variableCollections` shape directly.

Remote (library) collections are skipped. Aliases to remote variables are kept and marked `external`.

Figma colors arrive as `{r,g,b,a}` floats and are converted to hex (`#rrggbb` or `#rrggbbaa`).

## CSS input

Any stylesheet with custom properties. The parser reads:

| Pattern | Interpreted as |
|---|---|
| `:root`, `html`, `:host` | default mode |
| `[data-theme="dark"]`, `.dark`, `.theme-dark` | theme mode `dark` (collection `Theme`) |
| `@media (prefers-color-scheme: dark)` | theme mode `dark` |
| `@media (max-width: …)` / `(min-width: …)` | viewport mode (collection `Responsive`) |
| `[data-<x>="<y>"]` | mode `<y>` of collection `<X>` |
| `var(--x)` | alias to `--x` (fallbacks are ignored and noted) |
| `#hex`, `rgb()`, `hsl()`, named black/white | COLOR |
| `px`, unitless numbers | FLOAT; `rem`/`em` converted with a 16px base |
| anything else | STRING (composites like shadows are flagged as not representable in Figma) |

Tier inference for single-mode CSS variables: a literal is a **primitive** when another token references it or its name looks like a palette entry (numeric last segment or a hue word); otherwise it is a **semantic** token with a hardcoded value (finding S2).

CSS names become Figma-style names by replacing `-` with `/` (`--color-red-400` → `color/red/400`). Pass `--manifest` with a previous manifest to recover the real names and IDs.

## Round-trip

`tokens.css` written by `generate` carries block annotations such as `/* @collection Mapped @tier mapped @mode Dark */`. Re-ingesting it restores collections, tiers and modes exactly; with `--manifest` it also restores Figma names and IDs. A Figma export plus the previous manifest restores CSS names and selectors.
