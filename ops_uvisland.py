# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Island selection mode for the 3D View, a component mode next to Vertex, Edge and Face.

While the mode is on, the UV island under the mouse is highlighted and a click selects whole islands:
click replaces the selection, Shift+click toggles, Ctrl+click removes, Ctrl+Shift+click adds, and a click
on empty space clears it. Box, lasso, select all and other selection tools are rounded to whole islands
afterwards. Selected islands are tinted and outlined, so each island stays readable even when most of
the mesh is selected. The UV Editor is left as it is.
"""

import time

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils.bvhtree import BVHTree

from .ops_uv import _modal_running, _prefs

MAX_FACES = 200_000      # bigger meshes are skipped (building their islands would stall the viewport)
UV_EPS = 1e-10           # squared UV distance under which two corners count as the same UV
SETTLE_DELAY = 0.25      # seconds without edits before islands are rebuilt
DEPTH_BIAS = 4e-6        # NDC depth bias that keeps the overlay in front of the mesh's own faces
TICK = 0.2               # seconds between the watcher's own checks (selection made from menus, timers)
ROUND_EVENTS = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER', 'TIMER_REPORT', 'NONE'}

_cache = {}          # object name -> islands of that edit mesh (see _build)
_dirty = set()       # geometry or UVs changed: islands are rebuilt once edits settle
_sel_dirty = set()   # selection changed: the selected-island overlay is rebuilt
_last_sel = {}       # object name -> face selection (bool array) after the last rounding
_hover = {"obj": None, "island": -1}
_state = {"watcher": None, "last_change": 0.0, "last_save": 0.0, "rebase": False}


def active(context=None):
    wm = (context or bpy.context).window_manager
    return bool(wm is not None and getattr(wm, "blaya_uv_island", False))


def _edit_objects(context):
    seen, out = set(), []
    for obj in context.view_layer.objects:
        if obj.type == 'MESH' and obj.mode == 'EDIT' and obj.data.name not in seen:
            seen.add(obj.data.name)
            out.append(obj)
    return out


def _tag_redraw(context=None):
    wm = (context or bpy.context).window_manager
    for win in (wm.windows if wm else ()):
        for area in win.screen.areas:
            if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:  # the UV Editor shows the new selection
                area.tag_redraw()


# --------------------------------------------------------------------------- islands of one mesh

def uv_islands(bm, uv):
    """Lists of faces per UV island (hidden faces left out)."""
    from bpy_extras.bmesh_utils import bmesh_linked_uv_islands
    islands = bmesh_linked_uv_islands(bm, uv)
    return [[f for f in isl if not f.hide] for isl in islands if any(not f.hide for f in isl)]


def _uv_border(loop, uv, face_island):
    """True if this face edge is on the outline of its island: no face of the same island shares the
    edge with the same UVs on the other side (a seam, a UV cut or the mesh border)."""
    island = face_island[loop.face.index]
    a0, b0 = loop[uv].uv, loop.link_loop_next[uv].uv
    r = loop.link_loop_radial_next
    while r is not loop:
        if not r.face.hide and face_island[r.face.index] == island:
            # The other face usually runs the edge the other way round.
            a, b = (r, r.link_loop_next) if r.vert is loop.vert else (r.link_loop_next, r)
            if (a[uv].uv - a0).length_squared < UV_EPS and (b[uv].uv - b0).length_squared < UV_EPS:
                return False
        r = r.link_loop_radial_next
    return True


def _build(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    entry = {"mesh": obj.data.name, "faces": len(bm.faces), "ok": False,
             "sel_key": None, "sel_batches": None, "hover_key": None, "hover_batches": None}
    uv = bm.loops.layers.uv.active
    if uv is None or not len(bm.faces) or len(bm.faces) > MAX_FACES:
        return entry
    bm.verts.index_update()
    bm.faces.index_update()
    islands = uv_islands(bm, uv)
    if not islands:
        return entry
    face_island = np.full(len(bm.faces), -1, np.int32)
    for i, isl in enumerate(islands):
        face_island[[f.index for f in isl]] = i
    co = np.array([v.co for v in bm.verts], np.float32)

    tris = bm.calc_loop_triangles()
    tri_face = np.array([t[0].face.index for t in tris], np.int32)
    keep = face_island[tri_face] >= 0
    tri_vert = np.array([[l.vert.index for l in t] for t in tris], np.int32)[keep]

    seg_vert, seg_island = [], []
    for isl in islands:
        for f in isl:
            for l in f.loops:
                if _uv_border(l, uv, face_island):
                    nxt = l.link_loop_next
                    seg_vert.append((l.vert.index, nxt.vert.index))
                    seg_island.append(face_island[f.index])

    visible = [f for isl in islands for f in isl]
    bvh = BVHTree.FromPolygons([v.co for v in bm.verts], [[v.index for v in f.verts] for f in visible])
    entry.update(
        ok=True,
        islands=[np.array([f.index for f in isl], np.int64) for isl in islands],
        face_island=face_island,
        visible=face_island >= 0,
        tri_pos=co[tri_vert],                                   # (T, 3, 3) object space
        tri_island=face_island[tri_face[keep]],
        seg_pos=co[np.array(seg_vert, np.int32).reshape(-1, 2)],  # (S, 2, 3)
        seg_island=np.array(seg_island, np.int32),
        bvh=bvh,
        bvh_face=np.array([f.index for f in visible], np.int64),
    )
    return entry


def _settled():
    return time.monotonic() - _state["last_change"] >= SETTLE_DELAY and not _modal_running()


def entry_for(obj, rebuild_ok=True):
    """Cached islands of an edit mesh; rebuilt when its geometry or UVs changed and edits have settled."""
    name = obj.name
    entry = _cache.get(name)
    stale = entry is None or entry["mesh"] != obj.data.name or (name in _dirty and rebuild_ok and _settled())
    if not stale and entry["ok"]:
        bm = bmesh.from_edit_mesh(obj.data)
        stale = len(bm.faces) != entry["faces"]
    if stale and (entry is None or rebuild_ok):
        entry = _cache[name] = _build(obj)
        _dirty.discard(name)
        _sel_dirty.add(name)
    return entry


def _face_selection(bm):
    return np.fromiter((f.select for f in bm.faces), bool, len(bm.faces))


def _write_selection(obj, bm, target):
    """Make exactly the faces in `target` (bool per face) selected, in the mesh and in the UVs."""
    faces = bm.faces
    faces.ensure_lookup_table()
    for f in faces:
        if f.select:
            f.select_set(False)
    for i in np.flatnonzero(target):
        faces[int(i)].select_set(True)
    bm.select_flush_mode()
    # UVs follow, each face's own UVs only, so the UV Editor shows the islands selected and neighbouring
    # islands sharing a mesh vertex across a seam stay unselected. Set per face: even with sticky
    # selection off, Blender's own calls also select the corners of unselected faces sharing a vertex.
    sync = bpy.context.scene.tool_settings.use_uv_select_sync
    if sync:
        bm.uv_select_sync_from_mesh(sticky_select_mode='DISABLED')  # makes a valid UV selection to edit
    for f in faces:
        if f.hide:
            continue
        on = bool(target[f.index])
        for l in f.loops:
            if l.uv_select_vert != on:
                l.uv_select_vert_set(on)
            if l.uv_select_edge != on:
                l.uv_select_edge_set(on)
        if f.uv_select != on:
            f.uv_select_set(on)
    if sync:
        bm.uv_select_sync_valid = True
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


# --------------------------------------------------------------------------- selecting islands

def selection_snapshot(context):
    """Face selection of every edit mesh, to apply a click to the selection from before the click."""
    return {obj.name: _face_selection(bmesh.from_edit_mesh(obj.data)) for obj in _edit_objects(context)}


def select_island(context, hit, mode, base=None):
    """Click on an island. hit = (object name, island index) or None (empty space).
    mode: 'REPLACE', 'TOGGLE', 'ADD' or 'REMOVE'. base: selection snapshot the click applies to (the
    select tool may already have changed the selection on press). Returns True if the selection changed."""
    changed = False
    for obj in _edit_objects(context):
        entry = entry_for(obj)
        if not entry["ok"]:
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        cur = _face_selection(bm)
        start = (base or {}).get(obj.name)
        target = (start if start is not None and len(start) == len(cur) else cur).copy()
        before = target.copy()
        if mode == 'REPLACE':
            target[:] = False
        if hit is not None and hit[0] == obj.name:
            faces = entry["islands"][hit[1]]
            if mode == 'TOGGLE':
                on = not before[faces].all()
            else:
                on = mode != 'REMOVE'
            target[faces] = on
        if not np.array_equal(target, cur):
            _write_selection(obj, bm, target)
            changed = True
        _last_sel[obj.name] = target
        _sel_dirty.add(obj.name)
    return changed


def round_to_islands(context):
    """Turn partly selected islands into whole ones after another tool changed the selection.

    An island that gained faces is selected whole (box or lasso over part of it); an island that only
    lost faces is deselected whole (Ctrl+box over part of it). Right after the mode starts there's
    nothing to compare with, so every touched island is selected whole, like Maya's conversion.
    """
    changed = False
    rebase, _state["rebase"] = _state["rebase"], False
    for obj in _edit_objects(context):
        entry = entry_for(obj)
        if not entry["ok"]:
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        cur = _face_selection(bm)
        if rebase:
            # After undo / redo the restored selection is taken as it is: rounding it would redo the
            # step that was just undone.
            _last_sel[obj.name] = cur
            _sel_dirty.add(obj.name)
            continue
        prev = _last_sel.get(obj.name)
        if prev is not None and len(prev) != len(cur):
            prev = None
        vis = entry["visible"]
        fs = entry["face_island"][vis]
        n = len(entry["islands"])
        total = np.bincount(fs, minlength=n)
        picked = np.bincount(fs, weights=cur[vis], minlength=n)
        partial = (picked > 0) & (picked < total)
        if partial.any():
            if prev is None:
                on = partial
            else:
                gained = np.bincount(fs, weights=(cur & ~prev)[vis], minlength=n) > 0
                on = partial & gained
            target = cur.copy()
            target[vis] = np.where(partial[fs], on[fs], cur[vis])
            _write_selection(obj, bm, target)
            cur = target
            changed = True
        _last_sel[obj.name] = cur
        _sel_dirty.add(obj.name)
    return changed


# --------------------------------------------------------------------------- picking

def _area_under(window, x, y):
    """(area, WINDOW region) under window coordinates x / y, or (None, None)."""
    def inside(r):
        return r.width > 1 and r.height > 1 and r.x <= x < r.x + r.width and r.y <= y < r.y + r.height

    for area in window.screen.areas:
        if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
            # Toolbar, sidebar and headers can sit on top of the canvas (region overlap).
            if any(r.type != 'WINDOW' and inside(r) for r in area.regions):
                return area, None
            return area, next((r for r in area.regions if r.type == 'WINDOW' and inside(r)), None)
    return None, None


def pick_3d(context, region, rv3d, coord):
    """(object name, island) of the face under a region pixel in a 3D View, nearest first."""
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    best = None
    for obj in _edit_objects(context):
        entry = entry_for(obj, rebuild_ok=False)
        if not entry["ok"]:
            continue
        mw = obj.matrix_world
        inv = mw.inverted_safe()
        o = inv @ origin
        d = (inv.to_3x3() @ direction).normalized()
        loc, _nrm, idx, _dist = entry["bvh"].ray_cast(o, d)
        if loc is None:
            continue
        dist = (mw @ loc - origin).length
        if best is None or dist < best[0]:
            best = (dist, obj.name, int(entry["face_island"][entry["bvh_face"][idx]]))
    return None if best is None else best[1:]


def pick(context, window, x, y):
    """(object name, island) under window coordinates in a 3D View and True, or (None, False) elsewhere
    (other editors, toolbars, headers): clicks there are left alone."""
    area, region = _area_under(window, x, y)
    if area is None or region is None or area.type != 'VIEW_3D':
        return None, False
    return pick_3d(context, region, region.data, (x - region.x, y - region.y)), True


# --------------------------------------------------------------------------- drawing

def _island_batches(entry, islands):
    """Fill and outline batches for a set of island indices (None if empty)."""
    if not islands:
        return None
    ids = np.fromiter(islands, np.int32)
    tmask = np.isin(entry["tri_island"], ids)
    smask = np.isin(entry["seg_island"], ids)
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    return {
        "fill": batch_for_shader(flat, 'TRIS', {"pos": entry["tri_pos"][tmask].reshape(-1, 3)}),
        "line": batch_for_shader(line, 'LINES', {"pos": entry["seg_pos"][smask].reshape(-1, 3)}),
    }


def _overlays(obj):
    """(selected batches, hover batches) for one edit object, rebuilt only when they changed."""
    entry = entry_for(obj)
    if not entry["ok"]:
        return None, None
    name = obj.name
    if name in _sel_dirty and name not in _dirty:
        bm = bmesh.from_edit_mesh(obj.data)
        if len(bm.faces) == entry["faces"]:
            cur = _face_selection(bm)
            vis = entry["visible"]
            sel = frozenset(np.unique(entry["face_island"][vis & cur]).tolist())
            if sel != entry["sel_key"]:
                entry["sel_key"] = sel
                entry["sel_batches"] = _island_batches(entry, sel)
        _sel_dirty.discard(name)
    hover = frozenset((_hover["island"],)) if _hover["obj"] == name and _hover["island"] >= 0 else frozenset()
    if hover != entry["hover_key"]:
        entry["hover_key"] = hover
        entry["hover_batches"] = _island_batches(entry, hover)
    return entry["sel_batches"], entry["hover_batches"]


def _draw(batches, color, alpha, width, region):
    if batches is None:
        return
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    flat.uniform_float("color", (*color, alpha))
    batches["fill"].draw(flat)
    line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    line.uniform_float("viewportSize", (region.width, region.height))
    line.uniform_float("lineWidth", width)
    line.uniform_float("color", (*color, 1.0))
    batches["line"].draw(line)


def _draw_3d():
    context = bpy.context
    if not active(context) or context.mode != 'EDIT_MESH':
        return
    prefs = _prefs(context)
    space = context.space_data
    if not prefs.uv_island_colors or space is None or not space.overlay.show_overlays:
        return
    ui = context.preferences.system.ui_scale
    items = []
    for obj in _edit_objects(context):
        sel, hov = _overlays(obj)
        if sel is not None or hov is not None:
            items.append((obj.matrix_world, sel, hov))
    if not items:
        return
    proj = gpu.matrix.get_projection_matrix().copy()
    proj[2] = proj[2] - proj[3] * DEPTH_BIAS  # ndc_z -= DEPTH_BIAS, in perspective and ortho
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    with gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(proj)
        for matrix, sel, hov in items:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(matrix)
                _draw(sel, prefs.uv_island_color, prefs.uv_island_alpha, 2.0 * ui, context.region)
                _draw(hov, prefs.uv_island_hover_color, prefs.uv_island_alpha * 0.8, 2.0 * ui, context.region)
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


# --------------------------------------------------------------------------- the mode

def enter(context):
    """Turn UV Island mode on (from the marking menu, in Object or Edit Mode)."""
    wm = context.window_manager
    ts = context.scene.tool_settings
    obj = context.active_object
    if context.mode != 'EDIT_MESH' and obj is not None and obj.type == 'MESH':
        bpy.ops.object.mode_set(mode='EDIT')
    if context.mode != 'EDIT_MESH':
        return False
    wm.blaya_uv_island = True
    ts.mesh_select_mode = (False, False, True)
    _last_sel.clear()
    _hover.update(obj=None, island=-1)
    _state["rebase"] = False
    round_to_islands(context)  # partly selected islands become whole ones
    _state["last_save"] = time.monotonic()
    if _state["watcher"] is None:
        bpy.ops.blaya.uv_island_watch('INVOKE_DEFAULT')
    _tag_redraw(context)
    return True


def leave(context=None):
    """Turn UV Island mode off."""
    context = context or bpy.context
    wm = context.window_manager
    if wm is None or not getattr(wm, "blaya_uv_island", False):
        return
    wm.blaya_uv_island = False
    _hover.update(obj=None, island=-1)
    _last_sel.clear()
    _tag_redraw(context)


class BLAYA_OT_uv_island_mode(bpy.types.Operator):
    """Select whole UV islands in the 3D View: the island under the mouse is highlighted and a click
    selects it (Shift toggles, Ctrl removes, Ctrl+Shift adds)"""
    bl_idname = "blaya.uv_island_mode"
    bl_label = "UV Island"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode in {'OBJECT', 'EDIT_MESH'}

    def execute(self, context):
        if not enter(context):
            return {'CANCELLED'}
        self.report({'INFO'}, "UV Island selection")
        return {'FINISHED'}


class BLAYA_OT_uv_island_watch(bpy.types.Operator):
    """Runs while UV Island mode is on: highlights the island under the mouse and handles clicks.
    Every other event passes through untouched"""
    bl_idname = "blaya.uv_island_watch"
    bl_label = "UV Island Watch"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if _state["watcher"] is not None or context.window is None:
            return {'CANCELLED'}
        _state["watcher"] = self
        self._window = context.window
        self._timer = context.window_manager.event_timer_add(TICK, window=context.window)
        self._pending = False
        self._press = None     # left press over a canvas: position, modifiers, selection before it
        self._deferred = None  # a press released without dragging, waiting to be applied
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if _state["watcher"] is self:
            _state["watcher"] = None
        try:
            context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        _hover.update(obj=None, island=-1)
        _tag_redraw(context)
        return {'FINISHED', 'PASS_THROUGH'}

    def _others_running(self):
        try:
            return any(op.bl_idname != "BLAYA_OT_uv_island_watch" for op in self._window.modal_operators)
        except (AttributeError, ReferenceError):
            return False

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception as exc:  # never trap events: drop out of the mode instead
            print("Blaya: UV Island mode stopped:", exc)
            leave(context)
            return self._finish(context)

    def _modal(self, context, event):
        if not active(context):
            return self._finish(context)
        ts = context.scene.tool_settings
        if context.mode != 'EDIT_MESH' or tuple(ts.mesh_select_mode) != (False, False, True):
            leave(context)  # left Edit Mode or switched to vertices / edges from the header
            return self._finish(context)

        if event.type not in ROUND_EVENTS:
            self._pending = True  # a key or button may have run a selection tool: check afterwards
        elif self._deferred is not None and not self._others_running():
            # A click the select tool took on press (no CLICK event came): apply it now that the tool is done.
            press, self._deferred = self._deferred, None
            self._pending = False
            self._click(context, press)
        elif self._pending and not self._others_running():
            self._pending = False
            # No undo step of its own: undo goes back past the box / lasso that made the selection.
            if round_to_islands(context):
                _tag_redraw(context)

        if event.type == 'TIMER':
            self._safety_save(context)
            return {'PASS_THROUGH'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} and not self._others_running():
            hit, _over = pick(context, self._window, event.mouse_x, event.mouse_y)
            new = hit if hit is not None else (None, -1)
            if (_hover["obj"], _hover["island"]) != new:
                _hover.update(obj=new[0], island=new[1])
                _tag_redraw(context)
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and not (event.alt or event.oskey):
            # Clicks are worked out from press + release: the select tool often takes the press itself,
            # and then Blender never sends a CLICK event. Presses and releases always pass through, so
            # box select, gizmos and tool drags keep working.
            if event.value == 'PRESS':
                _hit, over = pick(context, self._window, event.mouse_x, event.mouse_y)
                self._press = None if not over else {
                    "x": event.mouse_x, "y": event.mouse_y, "base": selection_snapshot(context),
                    "mode": ('ADD' if event.ctrl and event.shift else 'TOGGLE' if event.shift
                             else 'REMOVE' if event.ctrl else 'REPLACE')}
            elif event.value == 'RELEASE':
                press, self._press = self._press, None
                limit = max(3, context.preferences.inputs.drag_threshold_mouse)
                # A transform still running here was started by that press (a gizmo grabbed without
                # moving): not a click on an island.
                if press is not None and not _modal_running() and abs(event.mouse_x - press["x"]) <= limit \
                        and abs(event.mouse_y - press["y"]) <= limit:
                    self._deferred = press
            elif event.value == 'CLICK' and self._deferred is not None:
                press, self._deferred = self._deferred, None
                self._pending = False
                self._click(context, press)
                return {'RUNNING_MODAL'}  # the click is ours: no tool selects on top of it
        return {'PASS_THROUGH'}

    def _click(self, context, press):
        hit, _over = pick(context, self._window, press["x"], press["y"])
        if select_island(context, hit, press["mode"], base=press["base"]):
            bpy.ops.ed.undo_push(message="Select UV Island")
        _tag_redraw(context)

    def _safety_save(self, context):
        """Blender holds its own auto save back while any modal operator runs, and this one runs for as
        long as the mode is on. Take Blaya's auto save copy instead, unless Blaya Auto Save already runs."""
        wm = context.window_manager
        paths = context.preferences.filepaths
        if (not paths.use_auto_save_temporary_files or getattr(wm, "blaya_auto_save", False)
                or not bpy.data.is_dirty or self._others_running()):
            return
        interval = max(60.0, paths.auto_save_time * 60.0)
        if time.monotonic() - _state["last_save"] < interval:
            return
        _state["last_save"] = time.monotonic()
        from . import ops_save
        ops_save.auto_save(context)


# --------------------------------------------------------------------------- bookkeeping

@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    if not _cache:
        return
    for upd in depsgraph.updates:
        if not isinstance(upd.id, (bpy.types.Object, bpy.types.Mesh)):
            continue
        name = upd.id.name
        for obj_name in list(_cache):
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.name == name or (obj.data is not None and obj.data.name == name):
                _sel_dirty.add(obj_name)
                if upd.is_updated_geometry:
                    _dirty.add(obj_name)
                    _state["last_change"] = time.monotonic()
                    if not bpy.app.timers.is_registered(_settle_timer):
                        bpy.app.timers.register(_settle_timer, first_interval=SETTLE_DELAY + 0.01)


def _settle_timer():
    if not _dirty:
        return None
    wait = SETTLE_DELAY - (time.monotonic() - _state["last_change"])
    if wait > 0:
        return wait + 0.01
    if _modal_running():
        return 0.1
    _tag_redraw()
    return None


@bpy.app.handlers.persistent
def _on_undo(*_args):
    # Undo swaps the edit mesh: face counts may match while the islands don't.
    _dirty.update(_cache)
    _sel_dirty.update(_cache)
    _state["rebase"] = True


@bpy.app.handlers.persistent
def _on_load(*_args):
    _cache.clear()
    _dirty.clear()
    _sel_dirty.clear()
    _last_sel.clear()
    _state["watcher"] = None  # modal handlers don't survive loading a file
    try:
        bpy.context.window_manager.blaya_uv_island = False
    except Exception:
        pass


_classes = (BLAYA_OT_uv_island_mode, BLAYA_OT_uv_island_watch)
_handles = []
_handlers = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph), (bpy.app.handlers.undo_post, _on_undo),
             (bpy.app.handlers.redo_post, _on_undo), (bpy.app.handlers.load_post, _on_load))


def register():
    bpy.types.WindowManager.blaya_uv_island = BoolProperty(
        name="UV Island Mode", description="Select whole UV islands", default=False)
    for cls in _classes:
        bpy.utils.register_class(cls)
    _handles.append((bpy.types.SpaceView3D, bpy.types.SpaceView3D.draw_handler_add(
        _draw_3d, (), 'WINDOW', 'POST_VIEW')))
    for handlers, fn in _handlers:
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    watcher = _state["watcher"]
    _state["watcher"] = None
    if watcher is not None:
        try:
            bpy.context.window_manager.event_timer_remove(watcher._timer)
        except Exception:
            pass
    for space, handle in _handles:
        space.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    for handlers, fn in _handlers:
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(_settle_timer):
        bpy.app.timers.unregister(_settle_timer)
    _cache.clear()
    _dirty.clear()
    _sel_dirty.clear()
    _last_sel.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.blaya_uv_island
