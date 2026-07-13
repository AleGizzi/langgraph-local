import React from "react";

/* 8-bit sprites drawn as inline SVG pixel grids — no image assets, crisp at any
 * size, and they inherit the current text colour. Each sprite is a list of rows
 * where "X" is a lit pixel. */

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
};

export default function PixelSprite({ name = "invader", size = 22,
                                      color = "currentColor", className = "" }) {
  const grid = SPRITES[name] || SPRITES.invader;
  const cols = grid[0].length;
  const rows = grid.length;
  const px = [];
  grid.forEach((row, y) => {
    [...row].forEach((cell, x) => {
      if (cell === "X") px.push(<rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" />);
    });
  });
  return (
    <svg className={className} width={size} height={(size / cols) * rows}
      viewBox={`0 0 ${cols} ${rows}`} fill={color}
      shapeRendering="crispEdges" aria-hidden="true">
      {px}
    </svg>
  );
}
