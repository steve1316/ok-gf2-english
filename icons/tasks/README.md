# Task icons

The icons on the Global task rows and on the Tasks page tabs.

The set is original and drawn from scratch as plain SVG paths on a 32x32 grid. No game art, logos or datamined assets are used, so there is no licence question.
The shapes borrow the game's angular look: cut corners and solid silhouettes. Peak Value and Boss Fight follow the generic symbols on the game's own cards, a bar
chart on a baseline and a warning triangle, redrawn here.

## Colours

Every file uses exactly two colours, and both are placeholders:

- `#FFFFFF` is the ink. `src/task_icons.py` swaps it for the theme's text colour. An opacity on it gives the dimmer second tone.
- `#F06C18` is the key mark. It is swapped for orange or teal, depending on the task.

Keep both spellings exact when editing, because the swap is a plain text replace. The placeholders mean a file still previews correctly on a dark background.

## Rules for a new icon

- Plain `<path>` elements only. Qt's SVG renderer quietly drops CSS, filters and text.
- Fill the 32x32 viewBox, or the icon draws smaller than the rest of the set.
- It has to stay readable at 20px, the size used on the tabs.
