import React from "react";

/* 8-bit sprites drawn as inline SVG pixel grids — no image assets, crisp at any
 * size. Single-colour sprites are a list of rows where "X" is a lit pixel and
 * inherit the current text colour. Multi-colour sprites are
 * { grid: [...rows], palette: { char: "#hex", … } } where each non-space char
 * maps to a colour. */

// Original pixel flame character for the help assistant (Calcifer): a friendly
// fire sprite with eyes and a smile. My own simple 8-bit design.
const FLAME = {
  palette: { r: "#e23b0f", o: "#ff7a18", y: "#ffcc33", w: "#fff7e6", k: "#2b0a02", b: "#6b3b12" },
  grid: [
    "......y......",
    "...y..o..y...",
    "..o.y.o.y.o..",
    "..o.oooo.oo..",
    ".rooyyyyoor..",
    ".rooyyyyooor.",
    "rooywwoowwyor",
    "rooywkookwyor",
    "rooyyooooyyor",
    "rooykwwwwkyor",
    ".rooykkkkyor.",
    ".rrooyyyyorr.",
    "..brooooorb..",
    "..bbbbbbbbb..",
  ],
};

export const SPRITES = {
  // classic "crab" invader — the app mark
  invader: [
    "..X.....X..",
    "...X...X...",
    "..XXXXXXX..",
    ".XX.XXX.XX.",
    "XXXXXXXXXXX",
    "X.XXXXXXX.X",
    "X.X.....X.X",
    "...XX.XX...",
  ],
  // "squid" invader — the help assistant
  squid: [
    "...XX...",
    "..XXXX..",
    ".XXXXXX.",
    "XX.XX.XX",
    "XXXXXXXX",
    "..X..X..",
    ".X.XX.X.",
    "X.X..X.X",
  ],
  // pixel X, for the assistant's close state
  close: [
    "X......X",
    ".X....X.",
    "..X..X..",
    "...XX...",
    "...XX...",
    "..X..X..",
    ".X....X.",
    "X......X",
  ],
  calcifer: FLAME,
};

export default function PixelSprite({ name = "invader", size = 22,
                                      color = "currentColor", className = "" }) {
  const sprite = SPRITES[name] || SPRITES.invader;
  const multi = !Array.isArray(sprite);
  const grid = multi ? sprite.grid : sprite;
  const palette = multi ? sprite.palette : null;
  const cols = grid[0].length;
  const rows = grid.length;
  const px = [];
  grid.forEach((row, y) => {
    [...row].forEach((cell, x) => {
      if (cell === " " || cell === ".") return;
      if (multi) {
        const c = palette[cell];
        if (c) px.push(<rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill={c} />);
      } else if (cell === "X") {
        px.push(<rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" />);
      }
    });
  });
  return (
    <svg className={className} width={size} height={(size / cols) * rows}
      viewBox={`0 0 ${cols} ${rows}`} fill={multi ? undefined : color}
      shapeRendering="crispEdges" aria-hidden="true">
      {px}
    </svg>
  );
}
