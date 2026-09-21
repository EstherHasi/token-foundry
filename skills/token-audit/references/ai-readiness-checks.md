# AI-readiness checks

"AI-ready" means an agent (Figma MCP, code assistant, design generator) can choose the right token from its name, trace it to a value, and emit the exact code reference without guessing.

| ID | Weight | Criterion | Measured as | Typical fix |
|---|---|---|---|---|
| AI1 | 20 | Semantic tokens reference primitives | % of semantic values that are aliases | auto in `generate` |
| AI2 | 15 | Predictable, code-safe naming | % tokens without uppercase, spaces, mixed separators or CSS collisions | rename |
| AI3 | 15 | Descriptions on semantic tokens | % semantic tokens with a description | `describe` ops; one line: when to use |
| AI4 | 10 | Figma scopes set | % tokens with scopes other than ALL_SCOPES (Figma input only) | `--infer-scopes` |
| AI5 | 10 | Explicit code syntax | % tokens with Figma WEB code syntax (100 for CSS input) | set automatically in the manifest |
| AI6 | 10 | Role-based semantic names | % semantic tokens without hue words or numeric steps in mapped tiers | rename (`surface/red` → `surface/danger`) |
| AI7 | 10 | Integrity | 100 − 10 per broken, circular, missing or upward reference | fix S3/S4/S5 |
| AI8 | 10 | Explicit fg/bg pairs | % surfaces with an on-* or sibling foreground | add `text/on-<surface>` tokens |

Score = weighted mean over the criteria that apply (AI4 is dropped for CSS input).

AI6b (info) flags positional surface names such as `surface/secondary`: they describe order, not purpose.

Writing descriptions (AI3): one line, starting with the use, naming the pair when relevant. Example: "Default page background. Pair with text/primary." Draft them for the user to approve as `describe` ops; never publish invented usage rules without approval.
