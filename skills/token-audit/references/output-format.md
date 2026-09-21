# Output format

## tokens.css

```css
/* @collection Primitives @tier primitive @mode Value (default) */
:root {
  --color-grey-650: #717171;
}

/* @collection Alias @tier alias @mode Mode 1 (default) */
:root {
  --neutral-650: var(--color-grey-650);
}

/* @collection Mapped @tier mapped @mode Light (default) */
:root, [data-theme="light"] {
  --text-muted: var(--neutral-650);
}

/* @collection Mapped @tier mapped @mode Dark */
[data-theme="dark"] {
  --text-muted: var(--neutral-400);
}

/* @collection Responsive @tier responsive @mode Mobile */
@media (max-width: 767px) {
  :root {
    --spacing-md: var(--spacing-12);
  }
}
```

- Order: primitive, alias, mapped/responsive. Default mode first.
- CSS name: Figma WEB code syntax when present, else the Figma name slugified (`color/Grey 50` → `--color-grey-50`).
- FLOAT: `px`, except weight, opacity, z-index (unitless) and durations (`ms`/`s`).
- Only primitives hold raw values. Composite strings (shadows) stay literal and are listed in the report.
- Mode switching in code: set `data-theme="dark"` on `<html>` (or any container). Mapped tokens only point at single-mode tokens, so nested theme containers resolve correctly.

## tokens.manifest.json

```json
{
  "format": "token-foundry/manifest@1",
  "css": "tokens.css",
  "collections": [
    { "name": "Mapped", "figmaId": "VariableCollectionId:3:0", "tier": "mapped",
      "modes": [ { "name": "Light", "figmaId": "3:0", "selector": ":root, [data-theme=\"light\"]" } ] }
  ],
  "tokens": [
    { "cssVar": "--text-muted", "name": "text/muted", "collection": "Mapped",
      "figmaId": "VariableID:3:73", "type": "COLOR", "scopes": ["TEXT_FILL"],
      "description": "", "codeSyntax": { "WEB": "var(--text-muted)" }, "status": "changed",
      "values": {
        "Light": { "alias": { "collection": "Alias", "name": "neutral/650", "cssVar": "--neutral-650", "figmaId": null } },
        "Dark":  { "alias": { "collection": "Alias", "name": "neutral/400", "cssVar": "--neutral-400", "figmaId": "VariableID:2:50" } }
      } }
  ],
  "changes": [ { "op": "add-primitive", "token": "Primitives::color/grey/650", "value": "#717171" } ]
}
```

`figmaId: null` means the variable will be created on import. `status`: unchanged, changed, new, renamed.

## changes.json (approved decisions)

```json
[
  { "op": "set",      "token": "Mapped::text/muted", "mode": "Light", "value": "#6b6b6b" },
  { "op": "alias",    "token": "Mapped::border/input", "mode": "Light", "to": "Alias::neutral/600" },
  { "op": "rename",   "token": "Mapped::surface/secondary", "to": "surface/brand" },
  { "op": "describe", "token": "Mapped::surface/primary", "description": "Default page background. Pair with text/primary." },
  { "op": "scopes",   "token": "Mapped::border/input", "scopes": ["STROKE_COLOR"] },
  { "op": "add", "collection": "Mapped", "name": "surface/inverse", "type": "COLOR",
    "values": { "Light": { "alias": "Alias::neutral/900" }, "Dark": { "alias": "Alias::neutral/50" } } }
]
```

Omitting `mode` applies the op to every mode. `set` with a raw value is converted to an alias of a new or existing primitive during `generate`. Renames keep the Figma ID, so existing bindings in Figma survive.
