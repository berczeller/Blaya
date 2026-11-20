# Blaya

### Maya-style navigation, hotkeys and modeling tools for Blender 5.2+.

![Blender](https://img.shields.io/badge/Blender-5.2%2B-7fd3ff?style=flat-square) ![Type](https://img.shields.io/badge/Blender-extension-ff8fa3?style=flat-square) ![Python](https://img.shields.io/badge/language-Python-c4a7ff?style=flat-square) ![Version](https://img.shields.io/github/v/release/berczeller/Blaya?style=flat-square&label=version&color=ffc36b) ![License](https://img.shields.io/badge/license-GPL--3.0--or--later-6fd6a0?style=flat-square)

---

Blaya makes Blender feel like Maya without fighting it: Alt + mouse navigation, QWER tools, a right-click marking menu, D-key pivot editing and a Maya-style UV Editor. The hotkeys are a small patch on top of Blender's current default keymap, so new Blender shortcuts keep working after upgrades. It also adds a few tools Maya doesn't have, like a Hammer-style Clipping Tool. Plain Python, no online checks, no telemetry.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Install](#install)
- [Commands](#commands)
- [Preferences](#preferences)
- [Known limitations](#known-limitations)
- [Why Blaya?](#why-blaya)
- [Building from source](#building-from-source)
- [Credits](#credits)
- [License](#license)

## Features

- **Maya navigation:** Alt+LMB orbit, Alt+MMB pan, Alt+RMB dolly, Alt+wheel zoom, F to frame.
- **QWER tools:** select, move, rotate, scale.
- **Quick rotation (hold E + X / Y / Z):** type an angle in a small box at the mouse and the selected objects turn by it, live, each around its own origin.
- **Marking menu (RMB):** component modes, object mode, isolate, shading, selection, create, freeze/reset transforms and pivot tools.
- **Space bar:** tap toggles perspective/orthographic, hold opens a view pie (ortho views, Quad View, splits, camera) with a label showing the view name and axis.
- **Quad View, Maya style:** leaving Quad View maximizes the pane under the mouse.
- **Smooth preview (1 / 2 / 3):** non-destructive, uses its own modifiers and never touches your mesh data or your Subdivision modifiers.
- **Pivot editing (D + V / C / F / G / X):** a move gizmo on the pivot. Drag its center or one of its axes, snapping to vertices, edge midpoints, face centers or the grid, with every target highlighted.
- **Clipping Tool (Shift+C):** draw a line in any view to cut the selected meshes, keep one side or split them, with capping, live preview, length/angle readout and in-tool undo.
- **UV Editor workflow:** QWER tools, smart click selection, 1 to 5 select modes, a UV marking menu, moving faces without stretching their neighbours, Shift+W straighten and D-key pivot placement.
- **Selected UV islands in 3D:** while a UV Editor is open, the selected UV islands are tinted in the 3D View.
- **Axis indicator presets** for Blender's navigation gizmo.
- **No DRM, no network access, no telemetry.**

## Requirements

- Blender 5.2 or newer (developed and tested on 5.3).

## Install

1. Download `Blaya-<version>.zip` (for example `Blaya-0.4.1.zip`) from [Releases](https://github.com/berczeller/Blaya/releases).
2. In Blender, open **Edit > Preferences > Get Extensions**, click the dropdown in the top right, pick **Install from Disk** and select the zip.
3. Enable **Blaya**, open its preferences and click **Activate Blaya Keymap** (or pick *Blaya* in **Preferences > Keymap**).

> [!NOTE]
> GitHub's automatic "Source code" archives are not installable extensions. Use the `Blaya-<version>.zip` asset.

Blaya writes one file outside its own folder, `scripts/presets/keyconfig/Blaya.py`, so the keymap shows up in Blender's keymap list.

## Commands

The Blender column is Blender 5.3's default keymap (left-click select). The Maya column is Maya's default hotkeys. A `-` means there is no default binding.

### Navigation and views

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Orbit | Alt+LMB | MMB | Alt+LMB | Same as Maya |
| Pan | Alt+MMB | Shift+MMB | Alt+MMB | Same as Maya |
| Dolly / zoom | Alt+RMB, Alt+wheel, wheel | Ctrl+MMB, wheel | Alt+RMB, wheel | Alt+wheel also zooms in Blaya |
| Frame selected | F (all Quad View panes), Alt+F (this pane) | Numpad . | F | |
| Frame everything | Shift+F, Home | Home, Shift+C | A | Shift+F also resets the 3D cursor (Blender's old Shift+C) |
| Persp / ortho | Space (tap) | Numpad 5 | - | Maya uses Space tap for the panel layout |
| View pie (front, top, left, quad, splits) | Space (hold) | ` / Numpad | Space (hold: hotbox) | Pie instead of a hotbox, shows a name and axis label |
| Quad View | View pie, or Space tap (option) | Ctrl+Alt+Q | Space (tap) | Leaving it maximizes the hovered pane, like Maya |
| Isolate selection | Alt+E or marking menu | Numpad / | Ctrl+1 | |
| Shading pie | Z | Z | 4 / 5 / 6 | Blender's own pie |

### Selection and transforms

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Select / Move / Rotate / Scale tool | Q / W / E / R | W (cycle), G / R / S (modal) | Q / W / E / R | Same as Maya |
| Marking menu | RMB | Context menu on RMB | RMB (over object) | Component modes, isolate, shading, tools |
| Context menu | Ctrl+RMB | RMB | - | Blender's object / mesh context menu |
| Component tools menu (edit mode) | Shift+RMB | - | Shift+RMB | Vertex / edge / face tools for the current mode |
| Grow / shrink selection | Shift+. / Shift+, | Ctrl+Numpad + / Ctrl+Numpad - | > / < | |
| Loop select (edit mode) | Double-click | Alt+click | Double-click | |
| Toggle vertex snapping | Ctrl+V | Shift+Tab (snap) | Hold V | Toggle instead of hold |
| Rotate by a typed angle (object mode) | Hold E + X / Y / Z | R, X / Y / Z, angle, Enter | - | Box at the mouse, see below |

#### Quick rotation (hold E + X / Y / Z, object mode)

Hold E (the Rotate tool key) and tap X, Y or Z. A box opens next to the cursor with the last angle used (90 the first time), already selected:

| Key | Action |
|---|---|
| Digits, `-`, `.` or `,` | type the angle; `-` flips the sign |
| Enter, click | apply (Enter right away repeats the last angle) |
| Esc, right-click | cancel and restore |
| X / Y / Z | switch the axis |
| Backspace / Ctrl+Backspace | delete a character / clear |
| Alt + mouse, wheel | navigate |

The selection turns live while you type, each object around its own origin, along the axis of the header's Transform Orientation (Global, Local, ...). Releasing E after the box opens doesn't matter. Each rotation is one undo step, and angles a hair off a whole degree are rounded, so four -90 turns end at exactly 0.

### Modeling

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Smooth preview off / on / smooth | 1 / 2 / 3 | 1 / 2 / 3 = select modes (edit) | 1 / 2 / 3 | Non-destructive, optional smooth shading via modifier |
| Delete components (edit mode) | X | X (menu) | Delete | Deletes by the current select mode, no menu |
| Extrude along normals | Ctrl+E, Ctrl+double-click | E / Alt+E | Ctrl+E | |
| Fill / make face | G | F | - | |
| Merge | Alt+M | M (menu) | - | |
| Proportional editing | O, Alt+O (connected) | O | B (soft select) | |
| Clipping Tool (object mode) | Shift+C | - | - | From Hammer and s&box, see below |

### Pivot editing

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Snap pivot to vertices | D+V | Ctrl+. (Affect Only Origins) + snapping | Hold D + hold V | Snap targets are highlighted |
| Snap pivot to edge midpoints | D+C | - | Hold D + hold C (curves) | Midpoints only |
| Snap pivot to face centers | D+F | - | - | Blaya addition |
| Snap pivot to the grid | D+G | - | Hold D + hold X | |
| Move pivot freely | D+X | - | Hold D | |
| Finish pivot editing | D, Enter, Esc, RMB | Ctrl+. again | Release D | Toggle instead of hold |

While editing the pivot, a move gizmo sits on it:

- Drag the white center to move the pivot on the view plane. In orthographic views the depth coordinate never changes.
- Drag an axis arrow to move it along that axis only. The arrows follow the Transform Orientation in the header (Global, Local, View, Cursor), and an axis pointing at you is hidden.
- While dragging, the pivot snaps to the highlighted target under the mouse (an axis drag takes the target's position along that axis) or to the grid with G. Hold Ctrl to drag without snapping, Esc or RMB cancels the drag.
- Click a highlighted point to put the pivot right on it. When points overlap on screen, the one closest to you wins.
- V / C / F / G / X switch the snap target, the header shows the pivot's coordinates, and navigation keeps working.

Only the origin moves: rotation, scale and the geometry stay where they are, so Mirror and other modifiers that use the origin pick up the exact position.

### Clipping Tool (Shift+C, object mode)

| Key | Action |
|---|---|
| Drag LMB | Draw the cut line, or drag one of its ends |
| Shift+X | Keep side A / side B / both (split into two objects) |
| C | Cap the cut on / off |
| Enter | Apply and exit |
| Space | Apply and keep cutting |
| Ctrl+Z | Undo the last cut of this session |
| Esc / RMB | Exit |
| Alt + mouse, wheel | Navigate |

The line snaps to vertices of the selected meshes or to the grid. In orthographic views the cut plane follows the view direction; in perspective it goes through the camera, so what you see is what gets cut. A readout shows the line's length and angle, and a cheat sheet sits in the bottom-left corner. After you leave the tool, the whole session is a single Ctrl+Z step.

### UV Editor

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Select / Move / Rotate / Scale tool | Q / W / E / R | W (cycle select tools), G / R / S | Q / W / E / R | Same as the 3D View |
| Select | Click | Click | Click | Smart selection picks the vertex, edge or face closest to the mouse |
| Toggle selection | Shift+click | Shift+click | Shift+click | |
| Select an island | Double-click, or 4 then click | L / Ctrl+L | UV Shell (marking menu) | |
| Select modes | 1 vertex, 2 edge, 3 face, 4 island, 5 smart | 1 / 2 / 3 + island toggle | Marking menu / F9 to F11 | A fixed mode turns smart selection off until 5 |
| Marking menu | RMB | Context menu | RMB | Modes, unwrap, split, stitch, straighten, align, seams, pack, pivot |
| Move faces without stretching | Drag (Face / Island mode) | Y (split), then move | Cut / extract, then move | Auto-detach, can be turned off |
| Straighten on the average | Shift+W | UV > Align | Align / Straighten (UV Toolkit) | Picks horizontal or vertical automatically |
| Place the 2D cursor | Shift+RMB (drag to move it) | Shift+RMB | - | Left-click no longer moves the cursor |
| Edit the pivot with snapping | D+V / D+C / D+F / D+G / D+X | - | Hold D (+ V / C / X) | Places the 2D cursor and uses it as pivot, key hints in the bottom-right corner |

While a UV Editor is open in Edit Mode, the selected UV islands are tinted with a single colour in the 3D View (colour, opacity and on/off in the preferences). With UV Sync Selection on, an island counts as selected when one of its faces is.

### Other

| Action | Blaya | Blender default | Maya default |
|---|---|---|---|
| Quick Favorites | Shift+Q | Q | - |
| Key location / rotation / scale | Shift+W / Shift+E / Shift+R | I (keying set), K (menu) | Shift+W / Shift+E / Shift+R |
| Insert keyframe menu | I | K | S (set key) |
| Move to collection | M, Ctrl+G | M | Ctrl+G (group) |
| Toggle 3D cursor overlay | Ctrl+D | - | - |
| New file | Ctrl+N | Ctrl+N (menu) | Ctrl+N |

Every keymap change lives in [`keymap_patch.py`](keymap_patch.py). It's plain data and safe to edit.

## Preferences

| Section | Settings |
|---|---|
| Space Bar | Tap action (perspective/orthographic or Quad View), pie menu delay, view name label (on/off, duration, rounding, border, shadow, colours) |
| Viewport | Axis indicator preset: Blender Default, Large Gizmo, Simple Axes, Bold Simple Axes or Don't Change |
| Pivot Edit | Snap radius, highlight snap points |
| Clipping Tool | Starting keep mode, capping, vertex snap radius, key hints |
| UV Editor | Smart selection, auto-detach on move, selected island tint in 3D (colour and opacity), key hints |
| Smooth Preview | Shade the preview smooth (through a temporary modifier, never on the mesh) |

## Known limitations

- The Clipping Tool cuts the base mesh (modifiers are re-evaluated afterwards) and cap faces have no UVs.
- Pivot snapping uses the base meshes of visible objects, not their evaluated result.
- Blaya changes hotkeys in the 3D View, the UV Editor and a few animation editors. Other editors keep Blender's defaults.

## Why Blaya?

I came to Blender from Maya, and for years **Maya Config Pro** by Form Affinity was how I made Blender feel like home. Blaya wouldn't exist without it as inspiration.

Version 2.4 added a license check that contacts Gumroad every time Blender starts. When the check fails or you're offline, the side panels, quad view, object-to-object selection and other tools are switched off until the next successful check. I paid for it and I'm glad I supported it, but I don't think basic navigation should depend on a server, especially in a free, GPL application that never asks you to be online.

There were technical reasons too. MCP 2.4 ships a frozen copy of Blender 4.3's keymap, so in Blender 5.x dozens of shortcuts point to operators that no longer exist and newer Blender shortcuts quietly disappear. Its 1/2/3 smooth preview also removed the first Subdivision modifier it found and rewrote the mesh's shading.

So I wrote my own, keeping the parts of the Maya workflow I actually use and layering them on Blender's own keymap. Blaya isn't meant to be a 1:1 Maya clone: Maya is the starting point, and it keeps growing with quality-of-life tools I want while modeling. Ideas and issues are welcome.

## Building from source

Blender 5.2 or newer on PATH. From the repo folder:

```
blender --command extension validate
blender --command extension build --output-dir release
```

The zip lands in `release/`.

## Credits

**Author:** Tom Berczeller

- Navigation and hotkeys inspired by Autodesk Maya's defaults.
- Inspired by Maya Config Pro by Form Affinity. Blaya is an independent implementation written from scratch; its hotkey layout mirrors the one I got used to, rebuilt as a patch on Blender's default keymap.
- Clipping Tool inspired by the clipping tool in Valve's Hammer editor and in s&box.

## License

Released under the [GNU General Public License v3.0 or later](LICENSE) (GPL-3.0-or-later), © 2026 Tom Berczeller.
