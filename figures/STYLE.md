# Method diagram style

How the method figures in this project are drawn (figures/loop.py is the reference). Give this file to whoever
draws the next one, person or model, and the result should look like it belongs in the same paper.

## Principles

- **Real things, plain words.** Draw the actual artefacts (geometry, code, tables, data) as they are, small. Keep
  every label schematic and high level, so a reader who has never seen the code can follow it. Never show internal
  ids, counts that depend on one run, or file names.
- **Quiet by default.** Black, white and greys. Colour only where it encodes something, one meaning per colour,
  and the same colour means the same thing in every figure.
- **True to the method.** Every box is a real step and every arrow a real flow of data. Simplify by leaving
  things out, never by drawing something the method does not do.
- **One idea per box.** A box answers one question. Its title names it and one line under it says what it does.
- **Hierarchy by weight and grouping, not decoration.** No shadows, gradients, icons or badges. Emphasis comes
  from a heavier line, a shared grey panel, or one small drawing.
- **Obvious reading order.** Left to right: input, process, output. A loop goes round once, clockwise. No
  crossing lines.

## Layout

- Columns labelled in small caps above the figure: INPUT, LOOP (or METHOD), OUTPUT. 11 px, bold, letter spacing
  0.12 em, grey.
- A grid. Boxes in a row share their top and bottom; boxes in a column share their left and right. Input and
  output may span the full height. Equal gutters (about 40 px between boxes).
- The steps that are deterministic (or that otherwise belong together) sit on one rounded panel, fill #efeeea,
  1 px edge #cfccc5, labelled in its bottom left corner in the same small caps.
- Leave room between rows for arrows and their labels; nothing touches a box edge but an arrow head.

## Boxes

- White, square corners, 1 px edge #a8a8a8.
- Content in the top part: a small drawing, table, code or chart. Title and caption at the bottom left, 12 px
  in from the edge: title 14 px bold #1d1d1b, caption 11 px #6b6b6b, one line, lower case, no full stop.
- Lists of items (rules, steps) as cards: white, 3 px corners, 1 px edge, a filled black circle with the item's
  number (1, 2, 3, then three dots, then n; never a real count), a bold name, and a line under it in 9.5 px.
- Tables: small caps headers in grey over a hairline; rows in 9.5 to 10 px; code in a monospace.
- Code: monospace 10.5 px; a diff shows removed lines in red with "-", added lines in green #2f8a4a with "+".
- A learned model (an LLM) is marked by a small drawing of a neural network (nodes in layers, joined each to
  each, black nodes, grey links) in the box's corner, and "LLM" in its title. Nothing else is marked this way.

## Arrows

- Straight segments and right angles only, with small filled arrow heads.
- The main flow (the loop) 1.6 px black; what enters and leaves it 1 px light grey (#a3a3a0).
- A label is one or two plain words in 11 px, beside the arrow's middle or start, never on it: "edit",
  "build", "score", "parent", "report".

## Drawings of the real thing

- Axonometric, from the same direction in every figure, white faces with fine dark edges (0.25 px #4a4a47).
- Hidden lines done properly: render with a depth buffer (nearest face per pixel, an edge wherever faces meet),
  never by painting shapes back to front, which gets crossing members wrong.
- Show only what carries the point (the shell of a building, not its insides); what is behind stays faint
  (#c4c4c0 edges, near white faces).
- Highlight by filling the members concerned, not by outlining: red #d8342c for hard faults, amber #e8930c for
  soft, each with a legend of a square and a word, no counts. Parts of an assembly (prefab panels) get muted
  tints, distinct where they touch, shaded slightly lighter on top faces than on sides.
- Loads and other forces as small red arrows on the drawing.
- An exploded view pulls the parts apart from their common centre, more vertically than sideways.

## Type and colour

- Helvetica or Arial throughout; Menlo for code.
- Ink #1d1d1b, secondary text #6b6b6b, box edges #a8a8a8, panel #efeeea, red #d8342c, amber #e8930c, green
  #2f8a4a. No other colours except panel tints.

## Output

- One script draws the figure from the project's own code and data, so it can be redrawn when the method
  changes. It writes SVG, a vector PDF for the paper, and a PNG at 3x.
- Check it at the size it will print, and close up, before calling it done.
