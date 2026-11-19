# Changelog

## 0.2.1 — UV fixes

### Fixed
- Moving UV islands (especially in Face mode on dense meshes) was slow and could freeze Blender: the
  UV island colours in the 3D View were rebuilt on every frame of the drag. They now update once,
  a moment after you stop editing, and the rebuild itself is several times faster.
- Auto-detach didn't work with smart (auto) selection: the select mode left by the last click decided it.
  In smart mode Blaya now looks at the selection itself, and moving whole faces splits them.
- Auto-detach only worked when dragging the selection with the Move tool, but the Move tool's drag
  box-selects, so moves really go through its gizmo, which skipped it. Face and Island selections
  are now kept split from their neighbours as soon as they're made, so the gizmo, G and the tool drag
  all move just the selected faces. G also runs the auto-detach move.
- D+V in the UV Editor ran Stitch (V) instead of the vertex pivot snap. Held-key combos now come
  before plain keys in the keymap.

### Changed
- A UV pivot placed with D + V / C / F / G / X now belongs to the selection it was placed for, like Maya:
  select something else and the UV Editor goes back to its previous pivot (bounding box center by
  default) instead of staying on the 2D cursor.
- Moving the selection carries its custom UV pivot along (Move tool drag, G, the gizmo); rotating or
  scaling around it leaves it where it is.

## 0.2.0 — UV workflow

### Added
- **Smart UV selection:** a click in the UV Editor selects the vertex, edge or face closest to the mouse,
  switching the select mode automatically. Keys 1-4 fix a mode (vertex / edge / face / island), 5 returns
  to smart selection. Double-click selects a whole island.
- **UV marking menu (RMB):** vertex / edge / face / island modes in the same slots as the 3D marking menu,
  plus unwrap, split, stitch, straighten, align X / Y, seams, pack, average island scale, UV sync and sticky
  selection, and UV pivot placement.
- **Auto-detach on move:** in Face or Island mode, dragging with the Move tool splits the selection from
  the rest of its island first, so neighbouring faces don't stretch (Vertex/Edge mode still stretches, for
  reshaping). Toggle in the preferences.
- **Straighten (Shift+W):** lines up the selected UVs on their average, picking horizontal or vertical
  automatically. Align X / Align Y are in the marking menu.
- **UV pivot editing (D + V / C / F / G / X):** places the 2D cursor with highlighted snap targets
  (vertices, edges in steps with the midpoint marked, face centers, grid) and uses it as the pivot.
  Key hints in the bottom-right corner.
- **UV island colours in 3D:** in Edit Mode, while a UV Editor is open, each UV island is tinted with
  its own colour in the 3D View.
- `CHANGELOG.md`.

### Changed
- UV Editor: **W** activates the Move tool (it used to cycle Blender's select tools), like Q / E / R.
- UV Editor: **left-click selects** (it used to place the 2D cursor). The 2D cursor is placed with
  Shift+right-click (drag still moves it) or with D + V / C / F / G / X.
- UV Editor: **right-click** opens the UV marking menu (it used to select).

### Removed
- UV Editor: Ctrl+Tab select-mode popup (replaced by 1-4 / 5 and the marking menu).
- UV Editor: the broken "4" binding inherited from the old keymap.

## 0.1.0 — First release

- Maya navigation (Alt + mouse), QWER tools, right-click marking menu.
- Space bar: tap toggles perspective/orthographic, hold opens the view pie, with a view name label.
- Non-destructive smooth preview (1 / 2 / 3).
- Pivot editing with highlighted snap targets (D + V / C / F / G / X).
- Clipping Tool (Shift+C) with capping, preview, readout, in-tool undo and key hints.
- Axis indicator presets.
