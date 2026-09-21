# Structure checks

Target architecture (any brand):

| Tier | Holds | References |
|---|---|---|
| primitive | Raw values: color ramps, spacing scale, radii, font families | nothing |
| alias | Semantic ramps or brand roles (`primary/400`, `neutral/100`) | primitives |
| mapped | Role tokens per theme (`surface/*`, `text/*`, `border/*`), multi-mode | alias (or primitives) |
| responsive | Spacing, radius, type per breakpoint, multi-mode | primitives |

Rule of thumb: values live only in primitives. Everything above references downward.

| ID | Severity | Check | Fix |
|---|---|---|---|
| S1 | error | No primitive layer | generate creates `Primitives` and moves values there |
| S1b | warning | No semantic layer | decision: define roles before components bind to primitives |
| S2 | error (color) / warning | Semantic token holds a raw value | auto: alias to matching or new primitive |
| S3 | error | Upward reference (lower tier points at higher tier) | decision: re-point to the lower tier |
| S3b | info | Mapped skips the alias tier | optional: point at the alias ramp |
| S4 | error | Broken alias | decision |
| S4b | error | Circular alias | decision |
| S4c | info | Alias to external library | none; verify library is published |
| S5 | error | Missing value in some mode | decision; never invent a value |
| S6a / S6b | warning | Uppercase or spaces in names | decision: rename (Figma ID keeps bindings) |
| S6c | warning | Mixed word separators | decision: pick the dominant style |
| S6d | error | Two tokens map to the same CSS name | auto: collection prefix added, reported |
| S6e | info | Irregular naming depth inside a group | optional |
| S7 | info | Ramp missing common steps | optional |
| S7b | warning | Ramp lightness not monotonic | decision |
| S8 | warning | Duplicate primitive colors | decision: keep one, alias or remove later |
| S9 | info | Unused primitives | none; report only |
| S10 | warning | Alias chain deeper than 3 | optional flatten |

When invoking `design:design-system` audit, map: Naming Consistency ← S6*; Token Coverage ← S1, S2 and counts by type; Priority Actions ← top errors. Score = 100 − 15 per error finding − 5 per warning − 1 per info (floor 0).
