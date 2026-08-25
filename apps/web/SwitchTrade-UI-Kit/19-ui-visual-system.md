# SwitchTrade UI Visual System Handoff

Status: approved visual language and rendering rules
Purpose: implementation handoff for the final SwitchTrade desktop application
Companion product document: `docs/18-user-flow.md`

## 1. Read this first

This document defines the approved **UI primitives, typography, rendering behavior, and visual constraints**.

It does **not** define the final application layout.

The current Emerald Window Study is only a test bench that places several UI elements on one 240×160 screen so they can be judged together. Do not copy its information panel position, menu position, background, navigation, row arrangement, or dialogue placement into the final application by default.

The final screen structure must be designed from `docs/18-user-flow.md` and the real application states. This visual system should be applied to those screens after their information hierarchy and actions are understood.

### Source-of-truth priority

When instructions conflict, use this order:

1. `docs/18-user-flow.md` — screen sequence, user goals, states, and actions.
2. This document — visual language and rendering rules.
3. The prototype — pixel-level reference for approved components only.

Prototype reference: <https://switchtrade-ui-concepts.minwlim72.chatgpt.site>

## 2. Approved direction

The final UI should feel like a faithful third-generation Pokémon interface adapted into an original SwitchTrade application.

Approved characteristics:

- Native-pixel rendering instead of a modern web UI with a pixel filter.
- A small, consistent component vocabulary.
- Pixelated borders with shallow three-dimensional layering.
- One neutral panel family and one green dialogue family.
- A true bitmap text renderer with the approved Emerald-style glyph shapes.
- Restrained colors and minimal decoration.
- A uniform application skeleton whose content changes by screen state.

The look must come from the glyph construction, border layers, palette, and integer geometry. Do not add a grain texture or noise overlay to simulate age.

## 3. Explicit non-goals

Do not:

- Treat the prototype composition as the final app layout.
- Reproduce the prototype's website heading, concept navigation, footer, field background, or fixed panel coordinates.
- Force every screen to contain an information panel, a menu, and a dialogue box simultaneously.
- Create a different frame style for each screen.
- Add modern cards, pills, glass panels, gradients, soft shadows, large rounded rectangles, or dashboard widgets.
- Use dozens of nested boxes to divide information.
- use `canvas.fillText()`, CSS text, or browser font rasterization for in-game UI text.
- Apply alpha thresholding, dilation, sharpening filters, blur filters, or post-processing to glyphs.
- Render glyphs at fractional coordinates.
- Scale the native canvas by a non-integer factor.
- Copy ROM graphics or UI assets when the approved clean-room primitives already cover the requirement.

## 4. Rendering model

### 4.1 Native coordinate system

- Design the in-game UI on a **240×160 native pixel plane**.
- Every primitive, glyph, cursor, and border layer must land on integer native coordinates.
- Present the canvas at 2×, 3×, or 4× scale.
- If the available window cannot fit an integer scale, letterbox or center the canvas. Do not stretch it fractionally.
- Disable interpolation for every scaled bitmap surface.

Canvas requirements:

```ts
canvas.width = 240;
canvas.height = 160;
context.imageSmoothingEnabled = false;
```

Display requirements:

```css
.game-canvas {
  image-rendering: crisp-edges;
  image-rendering: pixelated;
}
```

The final desktop shell may use normal high-resolution controls outside the game viewport when necessary. The SwitchTrade interaction screens themselves should use the native-pixel system consistently.

### 4.2 No fake grain

The desired texture comes from:

- one-pixel strokes;
- irregular bitmap glyph silhouettes;
- light southeast glyph shadows;
- stepped corners;
- several adjacent one-pixel frame colors;
- nearest-neighbor enlargement.

Do not add grain, scanlines, random noise, chromatic aberration, or CRT distortion.

## 5. Component vocabulary

The default visual system contains only these core primitives:

1. `NeutralWindow`
2. `DialogueWindow`
3. `BitmapText`
4. `SelectionCursor`
5. Optional content-specific pixel indicators using the existing palette

Before creating another framed component, determine whether the content can be expressed inside `NeutralWindow` or `DialogueWindow`. A new frame family requires a clear functional reason and explicit design approval.

## 6. Neutral window

### 6.1 Use

Use the neutral window for:

- menus;
- save/session data;
- room metadata;
- device or connection status;
- confirmation choices;
- compact settings;
- recoverable error information.

The same frame is used at different sizes. Do not create separate menu, status, and confirmation border styles.

### 6.2 Geometry

The window has lightly stepped one-pixel corners and a layered lavender-gray frame. It should look pixelated but slightly dimensional.

Layer order from outside to inside:

| Layer | Offset | Size change | Color | Role |
| --- | ---: | ---: | --- | --- |
| Drop shadow | `x+1, y+1` | none | `#3B3948` | Light muted violet-gray shadow |
| Outer outline | `x, y` | none | `#293231` | Dark structural edge |
| Violet edge | `x+1, y+1` | `-2` | `#49486A` | Outer frame color |
| Top highlight | `x+3, y+1` | horizontal inset 3 | `#8B8ACC` | One-pixel top light |
| Mid frame | `x+2, y+2` | `-4` | `#736886` | Dimensional transition |
| Inner frame | `x+3, y+3` | `-6` | `#71647E` | Inner violet edge |
| Pale rim | `x+4, y+4` | `-8` | `#DDD1DD` | Light separator |
| Paper | `x+5, y+5` | `-10` | `#FFFBFF` | Content surface |

Use a one-pixel stepped rectangle for each layer. Do not replace these layers with `border`, `border-radius`, `box-shadow`, or a CSS gradient.

Reference algorithm:

```ts
function steppedRect(ctx, x, y, width, height, color, cut = 1) {
  ctx.fillStyle = color;
  ctx.fillRect(x + cut, y, width - cut * 2, height);
  ctx.fillRect(x, y + cut, width, height - cut * 2);
}

function drawNeutralWindow(ctx, x, y, width, height) {
  steppedRect(ctx, x + 1, y + 1, width, height, "#3B3948", 1);
  steppedRect(ctx, x, y, width, height, "#293231", 1);
  steppedRect(ctx, x + 1, y + 1, width - 2, height - 2, "#49486A", 1);
  ctx.fillStyle = "#8B8ACC";
  ctx.fillRect(x + 3, y + 1, width - 6, 1);
  steppedRect(ctx, x + 2, y + 2, width - 4, height - 4, "#736886", 1);
  steppedRect(ctx, x + 3, y + 3, width - 6, height - 6, "#71647E", 1);
  steppedRect(ctx, x + 4, y + 4, width - 8, height - 8, "#DDD1DD", 1);
  steppedRect(ctx, x + 5, y + 5, width - 10, height - 10, "#FFFBFF", 1);
}
```

## 7. Green dialogue window

### 7.1 Use

Use the dialogue window for:

- guidance;
- questions;
- connection progress explanations;
- warnings written as player-facing sentences;
- confirmation prompts paired with a neutral selection menu;
- concise recovery instructions.

It is not required on every screen. Do not use it as a permanent footer merely because it appears at the bottom of the test screen.

### 7.2 Geometry

The dialogue frame uses larger stepped corners than the neutral frame. The approved frame does **not** contain an additional decorative horizontal line along the bottom interior.

Layer order:

| Layer | Offset | Size change | Color | Corner cut |
| --- | ---: | ---: | --- | ---: |
| Drop shadow | `x+1, y+1` | none | `#27665F` | 3 |
| Dark teal outline | `x, y` | none | `#187E70` | 3 |
| Bright green edge | `x+1, y+1` | `-2` | `#00D9A5` | 2 |
| Mint transition | `x+3, y+3` | `-6` | `#73F4CA` | 2 |
| Pale rim | `x+4, y+4` | `-8` | `#D8F4E9` | 1 |
| Paper | `x+6, y+6` | `-12` | `#FFFBFF` | 1 |
| Interior highlight | `x+7, y+7` | top and left only | `#FBFFFF` | n/a |

Reference algorithm:

```ts
function pixelShape(ctx, x, y, width, height, color, cut = 1) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x + cut, y);
  ctx.lineTo(x + width - cut, y);
  ctx.lineTo(x + width, y + cut);
  ctx.lineTo(x + width, y + height - cut);
  ctx.lineTo(x + width - cut, y + height);
  ctx.lineTo(x + cut, y + height);
  ctx.lineTo(x, y + height - cut);
  ctx.lineTo(x, y + cut);
  ctx.closePath();
  ctx.fill();
}
```

The size and position must be chosen per screen. The test value of `236×39` at `2,119` is not a final layout requirement.

## 8. Bitmap typography

### 8.1 Font source

The approved source font is the bundled **Pokémon Emerald (GBA)** FontStruction by TechniMan. It is licensed under CC0. When redistributing the WOFF2, keep its readme and license beside it.

Reference files:

- `public/fonts/pokemon-emerald-gba.woff2`
- `public/fonts/Pokemon-Emerald-GBA-readme.txt`
- `public/fonts/Pokemon-Emerald-GBA-license.txt`
- `scripts/generate-emerald-bitmap-font.py`
- `app/emeraldBitmapFont.ts`

### 8.2 Required rendering method

The WOFF2 is a source for generating glyph data. It is **not** rendered directly in the application.

Generate the approved 11-pixel glyph set once in monochrome mode, store each glyph as bitmap rows plus metrics, and draw individual pixels with `fillRect()`.

Required settings:

- Native glyph source size: `11px`.
- Glyph color layer: foreground palette color.
- Glyph shadow: same bitmap at `x+1, y+1`.
- Shadow is drawn first; foreground is drawn second.
- Character tracking: `0.5` native pixels on average.
- Tracking accumulator: fixed-point `32/64` pixel per character gap.
- Final glyph coordinates: rounded to whole native pixels.
- The resulting gaps alternate between zero and one pixel. No glyph pixel is drawn at a fractional coordinate.

Do not generate or use reduced 9px or 10px glyph variants. They distort the intended shapes. Use the same native 11px glyph set for headings, labels, values, menus, and dialogue copy. Hierarchy should come from color, position, grouping, and available space—not by shrinking the bitmap font.

### 8.3 Tracking and measurement

Text drawing, wrapping, cursor placement, hit regions, and right alignment must all use the same bitmap metrics.

```ts
const BITMAP_FONT_SIZE = 11;
const LETTER_SPACING64 = 32;

function textAdvance64(text, font) {
  const fallback = font.glyphs["?"];
  const characters = [...text];
  let width = 0;

  characters.forEach((character, index) => {
    width += (font.glyphs[character] ?? fallback).advance64;
    if (index < characters.length - 1) width += LETTER_SPACING64;
  });

  return width;
}
```

Accumulate fractional advance internally, but round only when placing each glyph on the canvas. Never draw a glyph at `x + 0.5`.

### 8.4 Typography palette

| Role | Foreground | Shadow |
| --- | --- | --- |
| Default text | `#5E5C5F` | `#D5D2CB` |
| Green title/success | `#1D9906` or `#2D9E4E` | `#93F392` or `#BEE5C7` |
| Blue value/link | `#3F70D8` | `#B7CDF2` |
| Red warning/error | `#CC433C` | `#F0B9B4` |

Use colored text sparingly. Most copy should remain default gray. Color communicates status or hierarchy; it is not decoration.

### 8.5 Copy constraints

- Default language is English.
- Prefer short, game-like sentences.
- Keep menu labels concise and verb-led when possible.
- Wrap dialogue by measured bitmap width, not character count.
- Use at most two dialogue lines unless a specific flow requires a dedicated reading screen.
- Avoid modern technical jargon in player-facing dialogue when a plain action statement works.

## 9. Selection cursor

Use the classic right-pointing triangular cursor for the current selection.

- Foreground: `#5E5C5F`.
- Shadow: `#D5D2CB` at `x+1, y+1`.
- Draw the shadow triangle first and the foreground triangle second.
- Keep the cursor on integer coordinates.
- Reserve a stable cursor column so labels do not shift between selected and unselected states.
- Do not replace it with a modern highlight pill, glow, checkbox, or animated focus ring.

Subtle stepped movement or a two-frame blink may be added later, but motion is optional and must never reduce readability.

## 10. Layout rules for the final application

### 10.1 Flow first

For every screen in `docs/18-user-flow.md`:

1. Identify the user's immediate goal.
2. Identify the information required to make the next decision.
3. Identify the primary and secondary actions.
4. Choose the smallest set of approved primitives needed for that state.
5. Compose the screen around that task.

Do not begin by copying the prototype and replacing its labels.

### 10.2 Uniform skeleton, flexible content

The final application should have one stable screen skeleton, but that does not mean every screen has identical boxes.

Keep stable where practical:

- native viewport and safe margins;
- title placement region;
- navigation behavior;
- cursor behavior;
- dialogue typography and padding;
- primary-action convention;
- back/cancel convention;
- status color meanings;
- transition rhythm.

Allow to change by screen need:

- panel dimensions;
- number of panels;
- whether a dialogue box is present;
- whether a selection menu is present;
- whether the content is a list, status summary, progress state, or confirmation;
- placement required by the specific information hierarchy.

### 10.3 Box restraint

- Start with zero boxes and add only those required to group or operate content.
- Prefer one well-composed neutral window over several small cards.
- Avoid nested windows unless replicating a proven game interaction such as a selection menu over a status view.
- A confirmation normally uses one dialogue window plus one compact neutral menu.
- A status screen normally uses one neutral window; add dialogue only when the user needs instruction.
- Empty space is allowed and preferable to decorative panels.

### 10.4 Spacing

Use native integer values only.

Recommended starting scale:

- Screen safe margin: 3–6px.
- Neutral-window content inset: minimum 6px from the outer frame.
- Dialogue text inset: approximately 12px from the outer frame, adjusted to the chosen window size.
- Text row step: 12–14px depending on descenders and shadow.
- Cursor-to-label gap: 2px after the cursor's visible edge.
- Minimum separation between unrelated text groups: 4px.

These are starting rules, not final coordinates. Validate every screen against its actual content.

## 11. State and interaction rules

Every interactive screen should explicitly support the states that apply:

- default;
- focused/selected;
- confirming;
- waiting;
- success;
- recoverable error;
- blocked/disabled;
- empty;
- reconnecting or retrying.

Do not invent a new frame family for each state. Prefer text color, copy, cursor state, and content changes inside the approved windows.

Input rules:

- Keyboard/controller navigation should be deterministic.
- Up/down moves within a menu.
- Confirm activates the selected item.
- Back/cancel returns to the previous safe state.
- Mouse/touch hit regions may be larger than the visible pixel labels, but visible geometry must not change.
- Selection must never depend on color alone; the cursor is required.

## 12. Architecture recommendation

Keep screen logic separate from pixel rendering.

Suggested layers:

```text
Application state machine
  -> Screen model from docs/18-user-flow.md
    -> Screen composition
      -> NeutralWindow / DialogueWindow / SelectionCursor / BitmapText
        -> 240×160 integer-pixel renderer
```

Recommended component responsibilities:

- `ScreenController`: owns flow state, transitions, loading, recovery, and back behavior.
- `ScreenView`: decides which approved primitives the current state needs.
- `NeutralWindow`: draws only the approved neutral frame and exposes a content rectangle.
- `DialogueWindow`: draws only the approved green frame and exposes a text rectangle.
- `BitmapText`: owns glyph measurement, wrapping, alignment, foreground, and shadow.
- `SelectionMenu`: owns cursor position, item navigation, and activation; it reuses `NeutralWindow` and `BitmapText`.
- `PixelViewport`: owns native resolution, integer scaling, letterboxing, and input-coordinate conversion.

Do not embed room logic, networking logic, or user-flow transitions inside frame-drawing functions.

## 13. Implementation sequence for Codex Desktop

1. Read `docs/18-user-flow.md` completely.
2. Read this document completely.
3. Inspect the reference implementation files listed in section 8.1.
4. List the required screens and state transitions from the user-flow document.
5. Propose one uniform application skeleton based on those flows. Do not use the prototype coordinates.
6. Implement `PixelViewport`, `BitmapText`, `NeutralWindow`, `DialogueWindow`, and `SelectionMenu` as reusable primitives.
7. Verify the primitives on a temporary component test screen if needed.
8. Implement the real screens from the flow document.
9. Remove or isolate the temporary test screen. It must not become the production home screen.
10. Verify every production screen at integer display scales.

## 14. Acceptance checklist

### Typography

- [ ] All in-game UI text uses the generated 11px bitmap glyph data.
- [ ] No `fillText()`, CSS text, or outline-font rendering is used inside the native UI.
- [ ] Foreground and one-pixel southeast shadow remain distinct.
- [ ] Tracking averages 0.5 native pixels through fixed-point accumulation.
- [ ] Every glyph lands on integer coordinates.
- [ ] Text width, wrapping, alignment, and cursor placement share the same metrics.
- [ ] No reduced-size mangled glyph set is used.

### Frames

- [ ] Neutral windows use the exact approved layer order and palette.
- [ ] Dialogue windows use the exact approved layer order and palette.
- [ ] The green window has no unnecessary bottom interior line.
- [ ] Corners are stepped pixels, not smooth CSS rounding.
- [ ] No additional frame family was introduced without approval.

### Layout

- [ ] Production layouts were derived from `docs/18-user-flow.md`.
- [ ] The prototype composition and coordinates were not copied as defaults.
- [ ] Screens share a coherent skeleton without forcing identical content arrangements.
- [ ] Boxes are limited to those needed for comprehension or interaction.
- [ ] Confirmation, waiting, success, error, and recovery states are represented.

### Rendering

- [ ] The native plane is 240×160.
- [ ] Display scaling is integer-only.
- [ ] Image smoothing is disabled.
- [ ] No fake grain or post-processing overlay is present.
- [ ] Input coordinates correctly map back to native pixels.

## 15. Ready-to-use Codex Desktop instruction

Use the following instruction when beginning the final app UI implementation:

> Read `docs/18-user-flow.md` and `docs/19-ui-visual-system.md` completely before editing. Treat `docs/18-user-flow.md` as the source of truth for screen structure and navigation, and `docs/19-ui-visual-system.md` as the source of truth for visual primitives and rendering. The existing Emerald Window Study is only a component test screen: do not copy its layout, background, coordinates, website navigation, or assumption that every screen needs all three window types. Build a uniform application skeleton from the user flow, then compose each screen using only the approved neutral window, green dialogue window, bitmap text, and selection cursor. Preserve the exact frame palettes and layer geometry. Use the generated 11px bitmap glyph data with a one-pixel southeast shadow and 0.5-pixel average tracking accumulated in fixed point; draw every glyph on integer native coordinates. Keep the in-game viewport at 240×160 and scale it only by integer factors. Do not use browser text rendering, reduced-size glyph variants, fake grain, modern cards, pills, gradients, or additional frame families. First propose the production screen skeleton and component map, then implement it and verify all states defined in the user flow.

## 16. Reference implementation warning

The current prototype is valuable for validating:

- border appearance;
- frame colors;
- corner construction;
- text silhouette;
- glyph shadow;
- character spacing;
- integer scaling;
- selection cursor appearance.

It is **not** an approved reference for:

- final screen hierarchy;
- final app navigation;
- final content density;
- panel placement;
- background art;
- the number of windows per screen;
- the final SwitchTrade user flow.

When in doubt, preserve the primitives and redesign the composition from the user-flow document.
