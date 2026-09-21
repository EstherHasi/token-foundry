# Mini-report template (one page)

Write in the user's language. Fill from `audit.json` (before) and the re-audit (after). Keep to one page: if a section runs long, cut the least severe items and point to `audit.md`.

```markdown
# Token audit · <source name> · <date>

<N> tokens · <C> collections (<tier list>) · modes: <modes>

| | Before | After |
|---|---|---|
| Structure | <s>/100 | <s>/100 |
| Accessibility (WCAG 2.2 AA) | <a>/100 · <failed>/<total> pairs fail | <a>/100 |
| AI-ready | <ai>/100 | <ai>/100 |

## Top findings
1. **<severity> · <title>** (<count>). <one sentence: impact>. <one sentence: fix or decision>.
   … max 8, errors first

## Applied automatically in tokens.css
- <n> semantic values now reference primitives (<n> new primitives: <names>)
- <other generate-log ops, one line each>

## Needs your decision
- <decision> · options: <A> / <B>

## Files
tokens.css · tokens.manifest.json (Figma IDs) · audit.md (full findings)
```

Style: short factual sentences, numbers over adjectives, token names in `code`. No em dashes. When "After" is not computed yet (report written before decisions), omit that column.
