import { EMERALD_BITMAP_FONTS, type BitmapFont } from "./emeraldBitmapFont";

export const NATIVE_WIDTH = 240;
export const NATIVE_HEIGHT = 160;
export const BITMAP_FONT_SIZE = 11;
export const LETTER_SPACING64 = 32;

export const EMERALD_UI_PALETTE = {
  paper: "#fffbff",
  ink: "#5e5c5f",
  inkShadow: "#d5d2cb",
  title: "#1d9906",
  titleShadow: "#93f392",
  blue: "#3f70d8",
  blueShadow: "#b7cdf2",
  green: "#2d9e4e",
  greenShadow: "#bee5c7",
  red: "#cc433c",
  redShadow: "#f0b9b4",
} as const;

export type PixelRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type BitmapTextOptions = {
  color?: string;
  shadow?: string;
  align?: CanvasTextAlign;
};

export function configureNativeCanvas(canvas: HTMLCanvasElement) {
  canvas.width = NATIVE_WIDTH;
  canvas.height = NATIVE_HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("A 2D canvas context is required.");
  context.imageSmoothingEnabled = false;
  return context;
}
export function pixelShape(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  color: string,
  cut = 1,
) {
  context.fillStyle = color;
  context.beginPath();
  context.moveTo(x + cut, y);
  context.lineTo(x + width - cut, y);
  context.lineTo(x + width, y + cut);
  context.lineTo(x + width, y + height - cut);
  context.lineTo(x + width - cut, y + height);
  context.lineTo(x + cut, y + height);
  context.lineTo(x, y + height - cut);
  context.lineTo(x, y + cut);
  context.closePath();
  context.fill();
}

export function steppedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  color: string,
  cut = 1,
) {
  context.fillStyle = color;
  context.fillRect(x + cut, y, width - cut * 2, height);
  context.fillRect(x, y + cut, width, height - cut * 2);
}

export function drawNeutralWindow(context: CanvasRenderingContext2D, rect: PixelRect) {
  const { x, y, width, height } = rect;
  steppedRect(context, x + 1, y + 1, width, height, "#3b3948", 1);
  steppedRect(context, x, y, width, height, "#293231", 1);
  steppedRect(context, x + 1, y + 1, width - 2, height - 2, "#49486a", 1);
  context.fillStyle = "#8b8acc";
  context.fillRect(x + 3, y + 1, width - 6, 1);
  steppedRect(context, x + 2, y + 2, width - 4, height - 4, "#736886", 1);
  steppedRect(context, x + 3, y + 3, width - 6, height - 6, "#71647e", 1);
  steppedRect(context, x + 4, y + 4, width - 8, height - 8, "#ddd1dd", 1);
  steppedRect(context, x + 5, y + 5, width - 10, height - 10, EMERALD_UI_PALETTE.paper, 1);
}

export function drawDialogueWindow(context: CanvasRenderingContext2D, rect: PixelRect) {
  const { x, y, width, height } = rect;
  pixelShape(context, x + 1, y + 1, width, height, "#27665f", 3);
  pixelShape(context, x, y, width, height, "#187e70", 3);
  pixelShape(context, x + 1, y + 1, width - 2, height - 2, "#00d9a5", 2);
  pixelShape(context, x + 3, y + 3, width - 6, height - 6, "#73f4ca", 2);
  pixelShape(context, x + 4, y + 4, width - 8, height - 8, "#d8f4e9", 1);
  pixelShape(context, x + 6, y + 6, width - 12, height - 12, EMERALD_UI_PALETTE.paper, 1);
  context.fillStyle = "#fbffff";
  context.fillRect(x + 7, y + 7, width - 14, 1);
  context.fillRect(x + 7, y + 7, 1, height - 14);
}

function getBitmapFont() {
  return EMERALD_BITMAP_FONTS[BITMAP_FONT_SIZE];
}

function textAdvance64(text: string, font: BitmapFont) {
  const fallback = font.glyphs["?"];
  const characters = [...text];
  let width = 0;

  characters.forEach((character, index) => {
    width += (font.glyphs[character] ?? fallback).advance64;
    if (index < characters.length - 1) width += LETTER_SPACING64;
  });

  return width;
}

export function measureBitmapText(text: string) {
  return Math.round(textAdvance64(text, getBitmapFont()) / 64);
}

function drawBitmapTextLayer(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  color: string,
  font: BitmapFont,
  align: CanvasTextAlign,
) {
  const advance64 = textAdvance64(text, font);
  let originX = x;
  if (align === "right" || align === "end") originX -= Math.round(advance64 / 64);
  if (align === "center") originX -= Math.round(advance64 / 128);

  const fallback = font.glyphs["?"];
  const characters = [...text];
  let cursor64 = 0;
  context.fillStyle = color;

  characters.forEach((character, index) => {
    const glyph = font.glyphs[character] ?? fallback;
    const glyphX = originX + Math.round(cursor64 / 64) + glyph.xOffset;
    const glyphY = y + glyph.yOffset;

    glyph.rows.forEach((rowBits, rowIndex) => {
      for (let column = 0; column < glyph.width; column += 1) {
        const mask = 1 << (glyph.width - column - 1);
        if (rowBits & mask) context.fillRect(glyphX + column, glyphY + rowIndex, 1, 1);
      }
    });

    cursor64 += glyph.advance64;
    if (index < characters.length - 1) cursor64 += LETTER_SPACING64;
  });
}

export function drawBitmapText(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  options: BitmapTextOptions = {},
) {
  const font = getBitmapFont();
  const color = options.color ?? EMERALD_UI_PALETTE.ink;
  const shadow = options.shadow ?? EMERALD_UI_PALETTE.inkShadow;
  const align = options.align ?? "left";
  drawBitmapTextLayer(context, text, x + 1, y + 1, shadow, font, align);
  drawBitmapTextLayer(context, text, x, y, color, font, align);
}

export function wrapBitmapText(text: string, maxWidth: number, maxLines = 2) {
  const words = text.split(" ");
  const lines: string[] = [];
  let line = "";

  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (measureBitmapText(candidate) > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  }

  if (line) lines.push(line);
  return lines.slice(0, maxLines);
}

export function drawSelectionCursor(context: CanvasRenderingContext2D, x: number, y: number) {
  context.fillStyle = EMERALD_UI_PALETTE.inkShadow;
  context.beginPath();
  context.moveTo(x + 1, y + 1);
  context.lineTo(x + 6, y + 5);
  context.lineTo(x + 1, y + 9);
  context.closePath();
  context.fill();

  context.fillStyle = EMERALD_UI_PALETTE.ink;
  context.beginPath();
  context.moveTo(x, y);
  context.lineTo(x + 5, y + 4);
  context.lineTo(x, y + 8);
  context.closePath();
  context.fill();
}

export function clientPointToNative(
  canvas: HTMLCanvasElement,
  clientX: number,
  clientY: number,
) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.floor(((clientX - bounds.left) / bounds.width) * NATIVE_WIDTH),
    y: Math.floor(((clientY - bounds.top) / bounds.height) * NATIVE_HEIGHT),
  };
}
