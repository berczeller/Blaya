# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/berczeller/Blaya/compare/0.3.0...HEAD
[0.3.0]: https://github.com/berczeller/Blaya/releases/tag/0.3.0
[0.2.1]: https://github.com/berczeller/Blaya/releases/tag/0.2.1
[0.2.0]: https://github.com/berczeller/Blaya/releases/tag/0.2.0
[0.1.0]: https://github.com/berczeller/Blaya/releases/tag/0.1.0
