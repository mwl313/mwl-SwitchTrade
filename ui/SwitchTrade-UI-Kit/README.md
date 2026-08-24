# SwitchTrade Emerald UI Kit

This package contains the exact reusable code and assets behind the approved SwitchTrade UI elements.

It deliberately does **not** contain the prototype screen composition. The current prototype is only a component test screen. Build production layouts from `docs/18-user-flow.md` and use `19-ui-visual-system.md` for visual rules.

## Package contents

- `19-ui-visual-system.md` — complete design and implementation rules.
- `emerald-ui-primitives.ts` — layout-neutral Canvas drawing API.
- `emeraldBitmapFont.ts` — generated 11px monochrome glyph data.
- `pixel-viewport.css` — integer-scaled 240×160 viewport styles.
- `host-markup.html` — minimal, layout-neutral host markup.
- `generate-emerald-bitmap-font.py` — reproducible glyph-data generator.
- `pokemon-emerald-gba.woff2` — source font used by the generator.
- `Pokemon-Emerald-GBA-readme.txt` and `Pokemon-Emerald-GBA-license.txt` — attribution and CC0 license.

## Recommended integration

1. Put `emerald-ui-primitives.ts` and `emeraldBitmapFont.ts` beside each other in the target app.
2. Import the viewport CSS into the desktop renderer.
3. Create one 240×160 canvas using the host markup or an equivalent React component.
4. Read `docs/18-user-flow.md` before composing any production screen.
5. Use the exported primitives to build the actual flow-specific screens.

The implementation uses Canvas because HTML/CSS text rendering cannot reproduce the approved bitmap glyphs reliably. HTML and CSS provide the host viewport; the UI itself is drawn with the included integer-pixel primitives.

## Important prohibitions

- Do not use the prototype coordinates as production defaults.
- Do not use `fillText()` for the native UI.
- Do not add smaller glyph variants.
- Do not render at fractional coordinates.
- Do not scale the viewport fractionally.
- Do not replace the frame functions with CSS borders or rounded rectangles.
