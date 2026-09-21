# Accessibility checks (WCAG 2.2 AA)

ARIA covers roles, states and names. Color tokens are tested against WCAG 2.2 AA. Say this plainly in the report when the user asked for "ARIA".

| Criterion | Applies to | Minimum |
|---|---|---|
| 1.4.3 Contrast (Minimum) | text, placeholder | 4.5:1; 3:1 for large text (≥24px, or ≥18.66px bold) |
| 1.4.11 Non-text Contrast | icons, input/control borders, focus indicator, state indicators | 3:1 against adjacent colors |
| 2.5.8 Target Size (Minimum) | size tokens named target/touch/control-height | 24×24 px |

Exempt: disabled text and controls; decorative borders (dividers). Decorative borders below 3:1 are reported as info (A5b) because they must reach 3:1 when they are the only visible boundary of a control.

## Pair inference

Roles come from name segments:

- bg: surface, background, bg, canvas, container, fill, layer, page
- text: text, foreground, fg, content, label, heading, body, title
- icon: icon · border: border, outline, stroke, divider · focus: focus, ring

Pairs tested, per mode of the multi-mode collection:

1. `on-X` / `on/X` / `onX` against the bg token whose last segment is X (A1).
2. Component siblings: `button/primary/text` against `button/primary/bg` (A1).
3. Generic text, icon, border, focus against every **neutral** surface (chroma ≤ 0.1, opaque), excluding disabled surfaces (A2 to A5).
4. `inverse` foregrounds against `inverse` surfaces only (A2b).
5. Pairs declared in `--pairs` (A6).

Semi-transparent colors are composited over the background, and the background over white (light modes) or black (modes named dark/night/dim).

Other findings: A7 saturated surface without an on-* partner; A4b no focus token; A8 two states (hover, disabled, selected…) resolve to the same color in every mode; A10 font sizes under 12px; A11 targets under 24px.

## Fix proposals

`audit.json → suggestions[]` gives per failing token and mode:

- `nearestStep`: closest ramp step (by step number) that passes against every tested background; when the token is mapped and an alias mirrors that step, the alias is proposed.
- `minimalShift`: the smallest lightness change (same hue and saturation) that passes.
- `change`: a ready-to-use entry for `changes.json`.

Present both options plus "change the background instead". A failing white-on-color pair (only fixable by switching to dark text) is a sign the background should change.

Score = % of required checks that pass (decorative borders excluded). `null` when no pairs could be inferred.

## WCAG 3.0 preview (informative)

WCAG 3.0 is a W3C Working Draft (latest seen: 10 September 2026). It does not deprecate WCAG 2, and its contrast algorithm is still to be determined. APCA (Accessible Perceptual Contrast Algorithm, APCA-W3 0.0.98G) is the leading candidate, so each check also stores:

- `apca`: Lc value (positive = dark text on light background, negative = light on dark).
- `apcaMin`: APCA guidance used for the preview: 60 for text, 45 for large text/headings, 30 for non-text.
- `apcaPass`: whether |Lc| reaches that guidance.

Finding A12 (info) lists pairs that pass WCAG 2.2 but fall below the APCA guidance. Never count these as failures or include them in the score. Recheck the WCAG 3 status before quoting it; update the thresholds here and in both engines when the method is final.
