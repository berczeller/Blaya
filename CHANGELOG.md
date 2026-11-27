# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Empties hide and show like collections, however they were made: hiding an Empty (H, the Outliner eye) hides everything parented under it, nested Empties included, and showing it brings them back, except objects hidden on their own. Shift+H keeps the selected objects visible. Can be turned off in the preferences
- Empty to Collection in the marking menu, next to Set Empty: turns the selected Empties into collections with the same names, with their objects inside and in the same place
- UV Island mode in the marking menu, next to Vertex, Edge and Face, from Object or Edit Mode: in the 3D View the UV island under the mouse is highlighted, a click selects it whole (Shift toggles, Ctrl removes, Ctrl+Shift adds, a click on empty space clears), and box or lasso selections are rounded to whole islands

- Unity Export in the Ctrl+S pie (top-right) and the sidebar's Blaya tab: exports each root of an export list (an Empty, a mesh or a collection) to its own FBX for Unity, with Forward -Z, Up Y, rotation 0 and scale 1. Each root can be moved to the origin for the export and its LOD parts merged per level; moving parts keep their hinges. Each root remembers the folder, scale settings and object names of its first export, and a popup reports lowercase _lod, .001 names, renamed objects, unapplied transforms, material problems and scene units. Smooth Preview is left out, and the scene, Edit Mode and UV Island mode are put back afterwards
- Empty to Collection keeps an Empty's place in the export list, as a collection

### Changed
- Selected UV islands are only tinted in UV Island mode, and each selected island is outlined, so the whole mesh no longer turns blue when a few faces are selected
- Isolate moved from the marking menu's top-left slot to the first button of the toolbox below it, to make room for UV Island
- Reset Position also works on objects parented to a Set Empty group afterwards (a new part or LOD): they join the group with their rotation and scale kept

## [0.7.0] - 2026-11-25

### Added
- Set Empty in the marking menu (Object Mode): puts the selected objects under a Plain Axes Empty at the world center named after them without the _LOD suffix (an existing Empty with that name is reused, so no .001 copy), each with its pivot on the center and its transforms applied, ready for FBX export
- Reset Position next to it: puts a Set Empty group back in that neutral state after its objects or Empty were moved

## [0.6.0] - 2026-11-24

### Added
- Smart Vert on 4 in Edit Mode: merge at last / mouse / center, merge and connect vertex paths, vertex bevel, and Slide Extend (Shift+Alt+4) with edge and face snapping and flatten
- Save pie on Ctrl+S: open, save, save as, incremental save, previous / next file, most recent, revert, auto save, import / export, append / link, purge, reload libraries and clean out .blend, with an Image Editor variant
- Auto Save: a copy of the open file every 30 seconds while it has changes and after undo, in its own folder, keeping the newest 20 per project

### Changed
- The quick rotation box (hold E + X / Y / Z) always opens at 0 instead of the last angle used. The applied angle shows in the redo panel and is reused by Repeat Last

### Fixed
- Placing the pivot with several objects selected moved every origin by the active object's offset instead of onto the placed point, so the gizmo ended up somewhere in between. All selected origins now go to the placed point

## [0.5.1] - 2026-11-23

### Added
- Alt + middle mouse pans in the Shader, Geometry Nodes and Compositor editors, like in the 3D View (it replaces Blender's "move backdrop image" on that input; Alt + right mouse stays with Node Wrangler)

### Fixed
- Middle mouse no longer panned in the node editors and other 2D editors (Graph Editor, Dope Sheet, Timeline, Sequencer): a leftover from Blaya's original keymap removed Blender's default middle-mouse pan

## [0.5.0] - 2026-11-20

### Added
- Quick rotation: in Object Mode, hold E and tap X, Y or Z to rotate the selected objects by a typed angle. A box at the mouse opens with the last angle selected (Enter repeats it), the rotation previews live, each object turns around its own origin along the header's Transform Orientation, Enter or a click applies and Esc restores

### Fixed
- Pivot editing ends cleanly if it was finished from a script, instead of waiting for further input

## [0.4.1] - 2026-11-19

### Fixed
- Blaya no longer reads its old keymap items when it loads. Right after Blaya is turned off and on, those items still point at the removed operators, and reading them can crash Blender (it did when the add-on was reloaded from a script). Blaya now rebuilds its keymap after loading instead of inspecting it, which also covers turning it off and on

## [0.4.0] - 2026-11-19

### Changed
- Pivot editing (D + V / C / F / G / X) uses a move gizmo: drag its center to move the pivot on the view plane, or an axis to move it along that axis only. Snapping applies while dragging (along the axis for axis drags), Ctrl turns it off, and clicking a highlighted point still jumps to it. The drag-anywhere placement with the orange guide line is gone
- The pivot gizmo follows the Transform Orientation in the header and shows the pivot's coordinates in the header
- Edge snapping (D+C, in the 3D View and the UV Editor) only snaps to edge midpoints; the Edge Snap Step preference is removed

### Fixed
- After restarting Blender, 1 / 2 / 3 all set smooth preview level 2, D+C / F / G / X all started pivot edit in Vertex mode and the UV Editor's 1 to 5 ignored their modes. Blender builds the keymap before Blaya registers its operators, so those items lost their settings; Blaya now rebuilds its keymap once the operators exist
- Moving the pivot in a perspective view slid it along a camera-facing plane, shifting it on every axis at once and throwing off Mirror modifiers
- Snap points that overlap on screen (front and back corners in orthographic views) now pick the one closest to the viewer

## [0.3.0] - 2026-11-19

### Added
- Island Colour preference for the tint of selected UV islands

### Changed
- Only the selected UV islands are tinted in the 3D View, all with one colour, instead of every island in its own colour
- Island Colour Opacity defaults to 0.25 (was 0.35)
- The add-on page in Blender links to the GitHub repo and has a shorter tagline
- Listed under the Modeling and UV categories in Blender's extension browser

### Fixed
- The UV island tint no longer z-fights with the mesh when the camera is far from it

## [0.2.1] - 2026-11-19

### Fixed
- Moving UV islands on dense meshes no longer lags or freezes Blender: island colours in the 3D View now update once after you stop editing, and the rebuild is several times faster
- Auto-detach now works with smart selection: moving whole faces splits them from their neighbours
- Face and Island selections are split as soon as they're made, so the gizmo, G and the Move tool drag all move only the selected faces (G also runs the auto-detach move)
- D+V in the UV Editor snaps the pivot to vertices instead of running Stitch

### Changed
- A UV pivot placed with D + V / C / F / G / X belongs to the selection it was placed for, like Maya: select something else and the pivot goes back to the previous one
- Moving the selection carries its custom UV pivot along; rotating or scaling around it leaves it in place

## [0.2.0] - 2026-11-19

### Added
- Smart UV selection: a click selects the vertex, edge or face closest to the mouse. Keys 1 to 4 fix a mode (vertex, edge, face, island), 5 goes back to smart, double-click selects an island
- UV marking menu (RMB) with the select modes in the same slots as the 3D one, plus unwrap, split, stitch, straighten, align X / Y, seams, pack, average island scale, UV sync, sticky selection and pivot placement
- Auto-detach on move: in Face or Island mode, moving splits the selection from the rest of its island so neighbours don't stretch (toggle in the preferences)
- Straighten (Shift+W): lines up the selected UVs on their average, horizontal or vertical picked automatically
- UV pivot editing (D + V / C / F / G / X) with highlighted snap targets and key hints
- UV island colours in the 3D View while a UV Editor is open in Edit Mode

### Changed
- UV Editor: W activates the Move tool instead of cycling select tools
- UV Editor: left-click selects; the 2D cursor moves to Shift+right-click and D + V / C / F / G / X
- UV Editor: right-click opens the UV marking menu

### Removed
- UV Editor: the Ctrl+Tab select-mode popup (replaced by 1 to 5 and the marking menu)
- UV Editor: a broken "4" binding inherited from the old keymap

## [0.1.0] - 2026-11-18

### Added
- Maya navigation (Alt + mouse), QWER tools and a right-click marking menu
- Space bar: tap toggles perspective/orthographic, hold opens the view pie with a view name label
- Non-destructive smooth preview (1 / 2 / 3)
- Pivot editing with highlighted snap targets (D + V / C / F / G / X)
- Clipping Tool (Shift+C) with capping, preview, readout, in-tool undo and key hints
- Axis indicator presets

[Unreleased]: https://github.com/berczeller/Blaya/compare/0.7.0...HEAD
[0.7.0]: https://github.com/berczeller/Blaya/releases/tag/0.7.0
[0.6.0]: https://github.com/berczeller/Blaya/releases/tag/0.6.0
[0.5.1]: https://github.com/berczeller/Blaya/releases/tag/0.5.1
[0.5.0]: https://github.com/berczeller/Blaya/releases/tag/0.5.0
[0.4.1]: https://github.com/berczeller/Blaya/releases/tag/0.4.1
[0.4.0]: https://github.com/berczeller/Blaya/releases/tag/0.4.0
[0.3.0]: https://github.com/berczeller/Blaya/releases/tag/0.3.0
[0.2.1]: https://github.com/berczeller/Blaya/releases/tag/0.2.1
[0.2.0]: https://github.com/berczeller/Blaya/releases/tag/0.2.0
[0.1.0]: https://github.com/berczeller/Blaya/releases/tag/0.1.0
