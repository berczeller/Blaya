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
- **Marking menu (RMB):** component modes (with UV Island), object mode, isolate, shading, selection, create, freeze/reset transforms and pivot tools.
- **Set Empty / Reset Position / To Collection (marking menu, object mode):** put the selected objects under an Empty at the world center with neutral transforms, ready for FBX export, put them back after moving them around, or turn Empties into collections.
- **Empties hide like collections:** hiding an Empty hides everything parented under it.
- **Space bar:** tap toggles perspective/orthographic, hold opens a view pie (ortho views, Quad View, splits, camera) with a label showing the view name and axis.
- **Quad View, Maya style:** leaving Quad View maximizes the pane under the mouse.
- **Smooth preview (1 / 2 / 3):** non-destructive, uses its own modifiers and never touches your mesh data or your Subdivision modifiers.
- **Pivot editing (D + V / C / F / G / X):** a move gizmo on the pivot. Drag its center or one of its axes, snapping to vertices, edge midpoints, face centers or the grid, with every target highlighted.
- **Clipping Tool (Shift+C):** draw a line in any view to cut the selected meshes, keep one side or split them, with capping, live preview, length/angle readout and in-tool undo.
- **Smart Vert (4 in Edit Mode):** merge at the last vertex or the one under the mouse, at the center, along two paths, connect paths, and Slide Extend with edge / face snapping.
- **Save pie (Ctrl+S):** save, incremental save, previous / next file, most recent, revert, auto save, import / export, append / link, purge and clean out, in one pie.
- **Unity Export (Ctrl+S, sidebar):** one FBX per Empty, mesh or collection in an export list, with Unity's axes, rotation 0 and scale 1, each moved to the origin for the export and checked for common problems first.
- **UV Editor workflow:** QWER tools, smart click selection, 1 to 5 select modes, a UV marking menu, moving faces without stretching their neighbours, Shift+W straighten and D-key pivot placement.
- **UV Island mode:** a component mode in the marking menu: in the 3D View the UV island under the mouse lights up and a click selects it whole.
- **Axis indicator presets** for Blender's navigation gizmo.
- **No DRM, no network access, no telemetry.**

## Requirements

- Blender 5.2 or newer (developed and tested on 5.3).

## Install

1. Download `Blaya-<version>.zip` (for example `Blaya-0.8.0.zip`) from [Releases](https://github.com/berczeller/Blaya/releases).
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
| Pan in node editors (Shader, Geometry Nodes, Compositor) | Alt+MMB, MMB | MMB | Alt+MMB | Alt+RMB is left to Node Wrangler; zoom with the wheel or Ctrl+MMB |
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

Hold E (the Rotate tool key) and tap X, Y or Z. A box opens next to the cursor with 0 selected, so typing replaces it:

| Key | Action |
|---|---|
| Digits, `-`, `.` or `,` | type the angle; `-` flips the sign |
| Enter, click | apply (Enter on 0 just closes the box) |
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
| Smart Vert (edit mode) | 4 and Shift / Alt / Ctrl+Alt / Shift+Alt + 4 | - | - | See below |

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

Only the origin moves: rotation, scale and the geometry stay where they are, so Mirror and other modifiers that use the origin pick up the exact position. With several objects selected, all their origins go to the placed point, so the gizmo and group moves, rotations and scales use it.

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

### UV Island mode (3D View)

A component mode for whole UV islands, in the marking menu's top-left slot next to Vertex, Edge and Face. It works from Object Mode or Edit Mode, like the other component modes (from Object Mode it enters Edit Mode). Picking Vertex, Edge, Face or Multi, another select mode in the header, or leaving Edit Mode turns it off. Isolate moved to the first button of the toolbox below the pie.

| Action | UV Island mode |
|---|---|
| Hover | The island under the mouse is highlighted |
| Click | Select that island (a click on empty space clears the selection) |
| Shift+click | Toggle the island |
| Ctrl+click | Remove the island |
| Ctrl+Shift+click | Add the island |
| Box, lasso, Select All | Rounded to whole islands: an island that gained faces is selected whole, one that only lost faces is deselected |

Selected islands are tinted and outlined (colours and opacity in the preferences). The UV Editor keeps working as usual and shows the islands selected. While the mode is on, Blender's own auto save waits (it never saves while a tool is running), so while Blender's auto save is on, Blaya takes an auto save copy instead at the same interval, unless Blaya's Auto Save is already running.

### Set Empty, Reset Position and To Collection (marking menu, object mode)

Three buttons at the bottom of the right-click marking menu's toolbox, under Smooth. They are greyed out until there is something to work on.

- **Set Empty:** creates a Plain Axes Empty at the world center and puts the selected objects inside it. Each object is moved so its own pivot sits on the world center, then its location, rotation and scale are applied, so it ends at 0 / 0 / 1 with its shape unchanged around the pivot. The Empty takes the name of the first selected object in the Outliner without its `_LOD<n>` suffix: `Chair_A_LOD0` ... `Chair_A_LOD3` give `Chair_A`. If an Empty with that name already exists, it is used (and moved to the world center) instead of making a `.001` copy; if another kind of object has the name, the new Empty gets Blender's `.001` suffix and a warning says why. Objects that share mesh data with others get their own copy first. Running it again on the same group reuses its Empty.
- **Reset Position:** after moving objects or their Empty around (to test modules side by side, say), puts the selected objects' groups back: every object at 0 / 0 / 1 inside its Empty and the Empty on the world center, even if an object was taken out of it. Objects parented to the group later (a new part or LOD) join it too, with their rotation and scale applied like Set Empty does.
- **To Collection:** turns the selected Empties into collections with the same names, inside the collection the Empty was in. Their objects move into the collection, keep their place in the world and are no longer parented. Nested Empties that are also selected become nested collections.

**Empties hide like collections:** hiding any Empty (H, the Outliner eye), however it was made, hides everything parented under it, nested Empties included, and showing it shows them again. Objects you hid on their own stay hidden. Shift+H keeps the selected objects visible even when their Empty gets hidden. Turn it off in the preferences.

### Smart Vert (edit mode)

| Keys | Action |
|---|---|
| 4 | Merge at the last selected vertex. After a box select: at the vertex nearest the mouse. One vertex: vertex bevel |
| Shift+4 | Merge at the center |
| Alt+4 | Merge paths: select 4 vertices in order, the path 1st-2nd merges onto the path 4th-3rd |
| Ctrl+Alt+4 | Connect paths: same selection, connects the two paths |
| Shift+Alt+4 | Slide Extend: the selected vertices slide along their edge towards the last one (past it extends) |

In Face or Edge select mode, 4 and Shift+4 merge each face island or edge chain on its own. During Slide Extend: Ctrl snaps to the edge or face under the mouse (any object), Alt with Ctrl projects on the snapped edge, F flattens the end face when possible, click or Space confirms, Esc or right-click cancels. Alt + mouse still navigates.

### Save pie (Ctrl+S)

| Slot | Contents |
|---|---|
| Left / Right / Bottom | Open, Save, Save As (Alt: save a copy) |
| Bottom-left / Bottom-right | New, Incremental Save (`name_009` -> `name_010`, otherwise `_001`; Alt: `name_01` branch) |
| Top | Most Recent, All Recent, Open Current / Temp folder, Revert, Auto Save; export rows (OBJ, Plasticity, FBX, USD by default); Previous / Next .blend in the folder (Ctrl: include .blend1, Alt: keep the UI); Append, Link, external data, Purge (Alt: recursive, Shift: Blender's dialog), Reload libraries, Clean out .blend |

**Auto Save** keeps a copy of the open file every 30 seconds while it has changes, and after each undo. Copies go to a "Blaya Autosave" folder in Blender's temporary directory (or a folder you pick) as `<date>_<file>-autosave.blend`, and only the newest 20 of each project are kept. It turns off when another file is opened; Alt-click the button to open a copy, Ctrl-click to open the folder.

In the Image Editor, the top of the pie switches to image open, save, pack and clear.

### Unity Export (Ctrl+S top-right, sidebar Blaya tab)

Exports each root in an export list to its own FBX, named after the root, set up for Unity: Forward -Z, Up Y, Apply Scalings FBX All and Apply Transform, so objects arrive with rotation 0,0,0 and scale 1, and a model facing -Y in Blender faces +Z (the blue arrow) in Unity. Animation, cameras and lights are left out. Static props only: a root with a rig or animation is skipped.

| Root | What its FBX holds |
|---|---|
| Empty (a Set Empty group, say) | Everything parented under it, not the Empty itself, so the LODs sit at the top of the file and Unity builds the LOD Group from their `_LOD0`, `_LOD1` names |
| Mesh | The mesh itself and its children, for meshes kept as their own file (`_COL`, `_shadowproxy`, `_guide`) |
| Collection | Its objects |

- **Pie:** Export All, Export Selected (the roots of the selected objects), Add (the roots of the selected objects: their Set Empty group or the top of their parent chain; a selected Empty is added itself; with nothing selected, the active collection), a folder preset menu, and Manage, which opens the full panel.
- **Panel** (sidebar, Blaya tab): the list, the folder for new roots and its presets, Move to 0,0,0, Merge per LOD, and Export All / Active / Selected.
- **Move to 0,0,0** (on by default): each root is exported as if it stood at the world origin and is put back afterwards. Only its position moves.
- **Merge per LOD** (off by default): joins the meshes of each LOD level into one (`Chair_LOD0_seat` + `Chair_LOD0_legs` give `Chair_LOD0`); parts without an LOD suffix join into one named after the root. Objects with children, like a door on its hinge, stay separate.
- **What stays out:** objects with Disable in Renders on (the camera icon, for helpers and reference meshes), cameras, lights and anything that isn't a mesh. Empties between the root and a mesh are kept, so moving parts keep their pivots and hierarchy. Hidden objects are exported.
- **Each root remembers its first export:** the folder, the scale settings and the object names. Later exports go to the same file at the same size even if the preferences change, and a lock icon shows in the list. Forget (the unlock button) clears it.
- **Nothing is renamed or changed for you.** Smooth Preview is left out of the FBX, Edit Mode and UV Island mode come back after the export, and a read-only FBX (not checked out) is reported instead of overwritten.

Before writing, each root is checked and a popup lists what may come out wrong in Unity:

- lowercase `_lod` (Unity builds no LOD Group from it)
- `.001` suffixes
- names that changed since the last export (Unity loses the meshes it referenced)
- rotation or scale not applied (Ctrl+A), zero or negative scale
- an Empty root with rotation or scale
- material names with `.001` or shared with an object
- material slots that differ from LOD0
- scene units other than metres at Unit Scale 1

**In Unity**, Blender can't set the import settings. For a static prop, check:

| Setting | For a static prop |
|---|---|
| Scale Factor / Convert Units | A one-metre object measures one unit |
| Rig > Animation Type | None |
| Import Animation | Off |
| Normals | Import |
| Tangents | To match the normal maps (Calculate Mikktspace for maps baked in MikkTSpace) |
| Generate Colliders | Off when the prefab has its own colliders |
| Materials | Each slot remapped to the right material |

Then place the model in a test scene: right size, facing +Z, pivots in place, LOD Group present, no extra objects or Animator.

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
| UV Editor | Smart selection, auto-detach on move, UV Island highlight in the 3D View (on/off, selected and hover colours, opacity), key hints |
| Smooth Preview | Shade the preview smooth (through a temporary modifier, never on the mesh) |
| Empties | Empties hide and show their objects like a collection |
| Save Pie | Export formats shown, FBX scale for Unity, auto save interval, how many copies to keep, save on undo / redo panel, auto save folder |
| Unity Export | Apply Scalings and Apply Transform for roots exported for the first time, triangulate, tangents, folder presets |

## Known limitations

- The Clipping Tool cuts the base mesh (modifiers are re-evaluated afterwards) and cap faces have no UVs.
- Pivot snapping uses the base meshes of visible objects, not their evaluated result.
- Blaya changes hotkeys in the 3D View, the UV Editor, the node editors (Alt+MMB pan) and a few animation editors. Other editors keep Blender's defaults.

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
