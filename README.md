# Blaya

Maya-inspired navigation for Blender with some personal spice on top: familiar
Alt+mouse controls, QWER tools, a marking menu and snapping pivot editing, plus quality-of-life
features from my own workflow. Free, open source and DRM-free.

- Blender **5.2+** (developed and tested on 5.3)
- License: **GPL-3.0-or-later**
- Author: **Tom Berczeller**

---

## Why Blaya exists

I came to Blender from Maya, and for years my go-to way of making Blender feel like home was
**Maya Config Pro** (MCP) by Form Affinity. It set up the navigation, hotkeys and marking menus I was used to,
and Blaya would not exist without it as inspiration.

Version **2.4** changed that for me. It added a license check that contacts Gumroad's servers **every
time Blender starts**. If there's no internet connection, or the check fails, the tools I rely on
(the side panels, quad view, object-to-object selection and more) are switched off until the next
successful check, and every launch can wait a few seconds for it. The license key also ends up stored as
plain text in the config folder.

I don't think DRM belongs in a Blender add-on. Blender is free and open source, its add-on ecosystem is
built on the GPL, and a big part of what makes it great is that you can open any tool, read it, learn
from it and bend it to your own workflow. Locking basic navigation behind an online check, inside an
application that never asks you to be online, goes against that spirit. I paid for the config and I'm
glad I supported it, but I didn't want my viewport to depend on a server somewhere.

There were technical reasons too. MCP 2.4 ships a full, frozen copy of Blender **4.3's** keymap. In
Blender 5.x that meant dozens of shortcuts pointing to operators that no longer exist, and newer Blender
shortcuts (tree view navigation, rename, delete…) silently disappearing. Its 1/2/3 smooth preview also
removed whichever Subdivision modifier it found first and rewrote the mesh's shading.

So I wrote my own. Blaya keeps the parts of the Maya workflow I actually use and drops the rest
(shelves, extra sidebar tabs). Everything is plain Python you can read and change, there are no online
checks, and the hotkeys are layered as a small patch on top of **Blender's current default keymap**, so
new Blender shortcuts keep working after upgrades.

## A living add-on

Blaya isn't meant to be a 1:1 Maya clone. Maya is the starting point; from there it grows with my
workflow. I'll keep adding quality-of-life features and tools I find myself wanting while modeling
(the Hammer-style clipping tool is a good example), and polishing what's already there. Ideas and
issues are welcome.

---

## Features

- **Maya navigation:** Alt+LMB orbit, Alt+MMB pan, Alt+RMB dolly, Alt+wheel zoom, F to frame.
- **QWER tools:** select, move, rotate, scale.
- **Marking menu (RMB):** vertex / edge / face / multi component modes, object mode, isolate, flat /
  smooth shading, plus quick selection, create, freeze/reset transforms, modes and pivot tools.
- **Space bar:** tap to toggle perspective/orthographic, hold for a view pie (orthographic views,
  Quad View, splits, camera tools). Picking a view shows a small label with its name and axis.
- **Quad View, Maya style:** leaving Quad View maximizes the pane under the mouse (optional tap action).
- **Smooth preview (1 / 2 / 3):** non-destructive, uses its own modifiers and never touches your mesh
  data or your own Subdivision modifiers.
- **Pivot editing (D + V / C / F / G / X):** every snap target is highlighted; the pivot jumps to the
  closest vertex, edge point (in adjustable steps, midpoint always available), face center or grid point.
- **Clipping Tool (Shift+C):** draw a line in any view to cut the selected meshes, keep one side or split
  into two objects, with capping, live preview, length/angle readout and in-tool undo. Inspired by the
  Hammer / s&box clipping tool.
- **Axis indicator presets** for Blender's navigation gizmo / simple axes.
- **No DRM, no network access, no telemetry.**

## Commands

Blender column = Blender 5.3 default keymap (left-click select). Maya column = Maya default hotkeys.

### Navigation and views

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Orbit | Alt+LMB | MMB | Alt+LMB | Same as Maya |
| Pan | Alt+MMB | Shift+MMB | Alt+MMB | Same as Maya |
| Dolly / zoom | Alt+RMB, Alt+wheel, wheel | Ctrl+MMB, wheel | Alt+RMB, wheel | Alt+wheel also zooms in Blaya |
| Frame selected | F (all Quad View panes), Alt+F (this pane) | Numpad . | F | |
| Frame everything | Shift+F, Home | Home, Shift+C | A | Shift+F also resets the 3D cursor (Blender's old Shift+C) |
| Persp / ortho | Space (tap) | Numpad 5 | — | Maya uses Space tap for the panel layout |
| View pie (front, top, left… quad, splits) | Space (hold) | ` / Numpad | Space (hold: hotbox) | Pie instead of a hotbox; shows a name + axis label |
| Quad View | View pie, or Space tap (option) | Ctrl+Alt+Q | Space (tap) | Leaving it maximizes the hovered pane, like Maya |
| Isolate selection | Alt+E or marking menu | Numpad / | Ctrl+1 | |
| Shading pie | Z | Z | 4 / 5 / 6 | Blender's own pie |

### Selection and transforms

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Select / Move / Rotate / Scale tool | Q / W / E / R | W (cycle), G / R / S (modal) | Q / W / E / R | Same as Maya |
| Marking menu | RMB | Context menu on RMB | RMB (over object) | Component modes, isolate, shading, tools |
| Context menu | Ctrl+RMB | RMB | — | Blender's object / mesh context menu kept here |
| Component tools menu (edit mode) | Shift+RMB | — | Shift+RMB | Vertex / edge / face tools for the current mode |
| Grow / shrink selection | Shift+. / Shift+, | Ctrl+Numpad + / − | > / < | |
| Loop select (edit mode) | Double-click | Alt+click | Double-click | |
| Toggle vertex snapping | Ctrl+V | Shift+Tab (snap) | Hold V | Toggle instead of hold |

### Modeling

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Smooth preview off / on / smooth | 1 / 2 / 3 | 1 / 2 / 3 = select modes (edit) | 1 / 2 / 3 | Non-destructive; optional smooth shading via modifier |
| Delete components (edit mode) | X | X (menu) | Delete | Deletes by the current select mode, no menu |
| Extrude along normals | Ctrl+E, Ctrl+double-click | E / Alt+E | Ctrl+E | |
| Fill / make face | G | F | — | |
| Merge | Alt+M | M (menu) | — | |
| Proportional editing | O, Alt+O (connected) | O | B (soft select) | |
| Clipping Tool (object mode) | Shift+C | — | — | From Hammer / s&box, see below |

### Pivot editing

| Action | Blaya | Blender default | Maya default | Notes |
|---|---|---|---|---|
| Edit pivot, snapping to vertices | D+V | Ctrl+. (Affect Only Origins) + snapping | Hold D + hold V | Snap targets are highlighted |
| … to edges | D+C | — | Hold D + hold C (curves) | Steps along the edge (5% by default), midpoint always available |
| … to face centers | D+F | — | — | Blaya addition |
| … to the grid | D+G | — | Hold D + hold X | |
| … freely | D+X | — | Hold D | |
| Finish pivot editing | D, Enter, Esc, RMB | Ctrl+. again | Release D | Toggle instead of hold |

Inside pivot editing: V / C / F / G / X switch the snap target, click or drag to place the pivot,
navigation keeps working.

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

The line snaps to vertices of the selected meshes or to the grid. In orthographic views the cut plane
follows the view direction; in perspective it goes through the camera, so what you see is what gets cut.
A small readout shows the line's length and angle, and a subtle cheat sheet sits in the bottom-left corner.
After leaving the tool, the whole session is a single Ctrl+Z step.

### Other

| Action | Blaya | Blender default | Maya default |
|---|---|---|---|
| Quick Favorites | Shift+Q | Q | — |
| Key location / rotation / scale | Shift+W / Shift+E / Shift+R | I (keying set), K (menu) | Shift+W / Shift+E / Shift+R |
| Insert keyframe menu | I | K | S (set key) |
| Move to collection | M, Ctrl+G | M | Ctrl+G (group) |
| Toggle 3D cursor overlay | Ctrl+D | — | — |
| New file | Ctrl+N | Ctrl+N (menu) | Ctrl+N |

The full list of changes lives in [`keymap_patch.py`](keymap_patch.py) (plain data, safe to edit).

## Install

1. Download the latest release `.zip` (or build one with
   `blender --command extension build --source-dir <this folder>`).
2. In Blender: **Edit > Preferences > Get Extensions > ⌄ > Install from Disk…** and pick the zip.
3. Enable **Blaya**, open its preferences and click **Activate Blaya Keymap**
   (or pick *Blaya* in **Preferences > Keymap**).

Blaya writes one small file, `scripts/presets/keyconfig/Blaya.py`, so the keymap appears in Blender's
keymap list. That's the only file it writes outside its own folder.

## Preferences

- **Space Bar:** tap action (perspective/orthographic or Quad View), pie menu delay, view name label
  (on/off, duration, rounding from rectangle to capsule, border, drop shadow, colours and transparency).
- **Viewport:** axis indicator preset (Blender Default, Large Gizmo, Simple Axes, Bold Simple Axes,
  or Don't Change).
- **Pivot Edit:** snap radius, edge step, highlight snap points.
- **Clipping Tool:** starting keep mode, capping, vertex snap radius, key hints.
- **Smooth Preview:** show the preview shaded smooth (done with a temporary modifier, never on the mesh).

## Known limitations

- The Clipping Tool cuts the base mesh (modifiers are re-evaluated afterwards) and cap faces have no UVs.
- Pivot snapping uses the base meshes of visible objects, not their evaluated (modified) result.
- Blaya changes hotkeys in the 3D View and a few animation editors; other editors keep Blender's defaults.

## Credits

- Inspired by Autodesk Maya's default navigation and hotkeys.
- Inspired by **Maya Config Pro** by Form Affinity, which I used for years. Blaya is an independent,
  from-scratch implementation; its hotkey layout mirrors the one I had grown used to, rebuilt as a patch
  on Blender's own default keymap.
- Clipping Tool inspired by Valve's Hammer / Facepunch's s&box editor.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
