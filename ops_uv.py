# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Editor workflow: smart click selection, select modes 1-4, auto-detach move, straighten,
and pivot (2D cursor) editing with snapping. UV Island mode in the 3D View lives in ops_uvisland.py.
"""

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, EnumProperty
from gpu_extras.batch import batch_for_shader

from . import ops_pivot as piv

MODES = (
    ('VERTEX', "Vertex", "Select UV vertices", 'UV_VERTEXSEL', 0),
    ('EDGE', "Edge", "Select UV edges", 'UV_EDGESEL', 1),
    ('FACE', "Face", "Select UV faces", 'UV_FACESEL', 2),
    ('ISLAND', "Island", "Select whole UV islands", 'UV_ISLANDSEL', 3),
    ('AUTO', "Auto", "Smart select: a click picks the vertex, edge or face closest to the mouse", 'RESTRICT_SELECT_OFF', 4),
)


def _prefs(context):
    return context.preferences.addons[__package__].preferences


def _wm_auto(context):
    return getattr(context.window_manager, "blaya_uv_auto", True)


# --------------------------------------------------------------------------- UV geometry helpers

def view_map(region):
    """(offset, scale) so that region_xy = offset + uv * scale (the UV view is a plain 2D transform)."""
    v2d = region.view2d
    x0, y0 = v2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = v2d.view_to_region(1.0, 1.0, clip=False)
    return np.array([x0, y0], float), np.array([x1 - x0, y1 - y0], float)


def to_region(region, uv):
    off, sc = view_map(region)
    return off + np.asarray(uv, float) * sc


def to_uv(region, xy):
    off, sc = view_map(region)
    return (np.asarray(xy, float) - off) / np.where(sc == 0, 1.0, sc)


def visible_faces(context, bm):
    sync = context.scene.tool_settings.use_uv_select_sync
    return [f for f in bm.faces if not f.hide and (sync or f.select)]


def gather_uv(context):
    """UV geometry of every mesh in Edit Mode, limited to faces shown in the UV Editor.

    Returns dict: verts (N,2) unique locations, edges (M,2,2), centers (K,2), faces (list of (K_i,2) arrays).
    """
    verts, edges, centers, faces = [], [], [], []
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        for f in visible_faces(context, bm):
            pts = np.array([tuple(l[uv].uv) for l in f.loops], float)
            faces.append(pts)
            verts.append(pts)
            edges.append(np.stack([pts, np.roll(pts, -1, axis=0)], axis=1))
            centers.append(pts.mean(axis=0))
    cat = lambda xs, shape: np.concatenate(xs) if xs else np.zeros(shape)
    v = cat(verts, (0, 2))
    if len(v):
        v = np.unique(np.round(v, 7), axis=0)
    return {"verts": v, "edges": cat(edges, (0, 2, 2)),
            "centers": np.array(centers) if centers else np.zeros((0, 2)), "faces": faces}


def _point_in_poly(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-12):
                inside = not inside
    return inside


def pick_element(region, geo, mouse, vert_px, edge_px):
    """What a smart click at `mouse` (region px) should select: 'VERTEX', 'EDGE', 'FACE' or None."""
    m = np.asarray(mouse, float)
    if len(geo["verts"]):
        d = np.linalg.norm(to_region(region, geo["verts"]) - m, axis=1)
        if d.min() <= vert_px:
            return 'VERTEX'
    if len(geo["edges"]):
        a = to_region(region, geo["edges"][:, 0])
        b = to_region(region, geo["edges"][:, 1])
        ab = b - a
        t = np.clip(np.sum((m - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0, 1)
        d = np.linalg.norm(a + ab * t[:, None] - m, axis=1)
        if d.min() <= edge_px:
            return 'EDGE'
    uvp = to_uv(region, m)
    for poly in geo["faces"]:
        if _point_in_poly(uvp, poly):
            return 'FACE'
    return None


def set_select_mode(context, mode):
    """Switch UV select mode (VERTEX / EDGE / FACE / ISLAND), honouring UV Sync Selection."""
    ts = context.scene.tool_settings
    if mode == 'ISLAND':
        ts.use_uv_select_island = True
        return
    ts.use_uv_select_island = False
    if ts.use_uv_select_sync:
        ts.mesh_select_mode = (mode == 'VERTEX', mode == 'EDGE', mode == 'FACE')
    else:
        ts.uv_select_mode = mode


# --------------------------------------------------------------------------- operators

def _uv_poll(context):
    return (context.mode == 'EDIT_MESH' and context.area is not None and context.area.type == 'IMAGE_EDITOR'
            and context.space_data.mode == 'UV')


class BLAYA_OT_uv_select_mode(bpy.types.Operator):
    """Set the UV select mode. Auto lets each click pick vertex, edge or face by proximity"""
    bl_idname = "blaya.uv_select_mode"
    bl_label = "UV Select Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Mode", items=MODES, default='VERTEX')

    @classmethod
    def poll(cls, context):
        return _uv_poll(context)

    def execute(self, context):
        wm = context.window_manager
        if self.mode == 'AUTO':
            wm.blaya_uv_auto = True
            context.scene.tool_settings.use_uv_select_island = False
            self.report({'INFO'}, "Smart UV selection")
        else:
            wm.blaya_uv_auto = False  # an explicit mode fixes the selection type
            set_select_mode(context, self.mode)
        return {'FINISHED'}


class BLAYA_OT_uv_click_select(bpy.types.Operator):
    """Select the UV element under the mouse. With smart selection the vertex, edge or face closest to
    the mouse is picked automatically"""
    bl_idname = "blaya.uv_click_select"
    bl_label = "Select UV"
    bl_options = {'REGISTER', 'UNDO'}

    toggle: BoolProperty(name="Toggle", default=False)

    @classmethod
    def poll(cls, context):
        return _uv_poll(context)

    def invoke(self, context, event):
        region = context.region
        mouse = (event.mouse_region_x, event.mouse_region_y)
        ts = context.scene.tool_settings
        if _wm_auto(context) and not ts.use_uv_select_island:
            ui = context.preferences.system.ui_scale
            kind = pick_element(region, gather_uv(context), mouse, 12 * ui, 8 * ui)
            if kind is not None:
                set_select_mode(context, kind)
        u, v = to_uv(region, mouse)
        return bpy.ops.uv.select(location=(float(u), float(v)), toggle=self.toggle,
                                 deselect_all=not self.toggle)


class BLAYA_OT_uv_move(bpy.types.Operator):
    """Move the selected UVs. In Face or Island mode the selection is split from the rest of its island
    first, so neighbouring faces don't stretch"""
    bl_idname = "blaya.uv_move"
    bl_label = "Move UVs (Auto Detach)"

    drag: BoolProperty(name="Drag", description="Confirm the move on mouse release (tool drag) "
                       "instead of with a click (G)", default=True)

    @classmethod
    def poll(cls, context):
        return _uv_poll(context)

    def invoke(self, context, event):
        global _move_hint
        maybe_detach(context)
        _move_hint = True  # a custom pivot follows this move
        bpy.ops.transform.translate('INVOKE_DEFAULT', release_confirm=self.drag)
        return {'FINISHED'}


def maybe_detach(context):
    """Split the selection from its island when moving faces/islands (no-op for vertices/edges). Returns True if split."""
    ts = context.scene.tool_settings
    if not _prefs(context).uv_auto_detach or ts.use_uv_select_sync:
        return False
    if _wm_auto(context) and not ts.use_uv_select_island:
        # Smart selection: the mode is whatever the last click picked (a box select keeps it),
        # so look at the selection itself: whole faces selected = moving faces.
        face_like = selection_has_faces(context)
    else:
        face_like = ts.use_uv_select_island or ts.uv_select_mode == 'FACE'
    if face_like:
        bpy.ops.uv.select_split()
        return True
    return False


def _face_split_wanted(context):
    """Face-like selection where faces should come loose from their island when moved."""
    ts = context.scene.tool_settings
    if ts.use_uv_select_sync or not _prefs(context).uv_auto_detach:
        return False
    return ts.use_uv_select_island or ts.uv_select_mode == 'FACE'


SPLIT_MAX_FACES = 20_000  # above this, only Blaya's own moves (Move tool drag, G) split


def split_face_selection(context):
    """Like uv.select_split, but without an operator (no undo step, safe from a timer): UVs that
    only belong to partly selected faces are deselected, so ANY move (gizmo, G, tool) takes just the
    selected faces and leaves their neighbours alone. Returns True if something changed."""
    changed = False
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        faces = visible_faces(context, bm)
        if len(faces) > SPLIT_MAX_FACES:
            continue
        if not any(f.uv_select for f in faces):
            continue  # nothing face-selected: leave vertex/edge picks alone
        dirty = False
        for f in faces:
            if f.uv_select:
                continue
            for l in f.loops:
                if l.uv_select_vert or l.uv_select_edge:
                    l.uv_select_vert_set(False)
                    l.uv_select_edge_set(False)
                    dirty = True
        if dirty:
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            changed = True
    return changed


SPLIT_INTERVAL = 0.2


def _any_uv_editor(context):
    """Like _uv_editor_open, but for timers (which have no screen in their context)."""
    wm = context.window_manager
    return any(a.type == 'IMAGE_EDITOR' and a.spaces.active.mode == 'UV'
               for win in (wm.windows if wm else ()) for a in win.screen.areas)


def _face_split_watch():
    """Keep face selections split while a UV Editor is open (gizmo drags can't be intercepted)."""
    try:
        context = bpy.context
        if (context.mode == 'EDIT_MESH' and _running is None and not _modal_running()
                and _any_uv_editor(context) and _face_split_wanted(context)):
            if split_face_selection(context):
                if _custom_pivot is not None:
                    _custom_pivot["sig"], _custom_pivot["co"] = selection_state(context)
                for win in context.window_manager.windows:
                    for area in win.screen.areas:
                        if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                            area.tag_redraw()
    except Exception:
        pass
    return SPLIT_INTERVAL


def selection_has_faces(context):
    """True if any face shown in the UV Editor has all of its UVs selected."""
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        for f in visible_faces(context, bm):
            if getattr(f, "uv_select", False) or all(_loop_uv_selected(l, uv) for l in f.loops):
                return True
    return False


def _loop_uv_selected(loop, uv):
    sel = getattr(loop, "uv_select_vert", None)
    return loop[uv].select if sel is None else sel


class BLAYA_OT_uv_straighten(bpy.types.Operator):
    """Line up the selected UVs on their average: a mostly horizontal selection gets the same V,
    a mostly vertical one the same U"""
    bl_idname = "blaya.uv_straighten"
    bl_label = "Straighten UVs (Average)"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name="Axis", items=(
        ('ALIGN_AUTO', "Auto", "Pick the axis the selection is closest to being aligned on"),
        ('ALIGN_X', "Align X", "Same U for all (vertical line)"),
        ('ALIGN_Y', "Align Y", "Same V for all (horizontal line)"),
    ), default='ALIGN_AUTO')

    @classmethod
    def poll(cls, context):
        return _uv_poll(context)

    def execute(self, context):
        return bpy.ops.uv.align(axis=self.axis, position_mode='MEAN')


# --------------------------------------------------------------------------- pivot (2D cursor) editing

SNAP_KEYS = {'V': 'VERTEX', 'C': 'EDGE', 'F': 'FACE', 'G': 'GRID', 'X': 'NONE'}
_running = None


def in_uv_pivot_edit():
    return _running is not None


class BLAYA_OT_uv_pivot_edit(bpy.types.Operator):
    """Place the 2D cursor (used as pivot) with highlighted snap points.
    V vertex, C edge, F face center, G grid, X free. Click or drag to place. D, Enter, Esc or right-click finish"""
    bl_idname = "blaya.uv_pivot_edit"
    bl_label = "Edit UV Pivot"

    snap: EnumProperty(name="Snap", items=piv.SNAP_ITEMS, default='VERTEX')

    @classmethod
    def poll(cls, context):
        return _uv_poll(context)

    def _rebuild(self, context):
        self._geo = gather_uv(context)
        self._update(context)

    def _grid_step(self, region):
        _off, sc = view_map(region)
        px = max(abs(sc[0]), 1e-6)
        step = 1.0
        while step * px > 28.0:  # halve until cells are close to ~14-28 px
            step /= 2.0
        return step

    def _update(self, context):
        region = self._region
        prefs = _prefs(context)
        mouse = np.array(self._mouse, float)
        radius = prefs.pivot_snap_radius
        self._hot = self._hot_edge = None
        geo = self._geo
        if self.snap in {'VERTEX', 'FACE'}:
            pts = geo["verts"] if self.snap == 'VERTEX' else geo["centers"]
            if len(pts):
                xy = to_region(region, pts)
                i = piv.nearest_point(xy, np.ones(len(xy), bool), mouse, radius)
                if i is not None:
                    self._hot = pts[i].copy()
        elif self.snap == 'EDGE' and len(geo["edges"]):
            a = to_region(region, geo["edges"][:, 0])
            b = to_region(region, geo["edges"][:, 1])
            ab = b - a
            t = np.clip(np.sum((mouse - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0, 1)
            d = np.linalg.norm(a + ab * t[:, None] - mouse, axis=1)
            i = int(np.argmin(d))
            if d[i] <= radius:
                e = geo["edges"][i]
                self._hot_edge = i
                self._hot = (e[0] + e[1]) * 0.5  # edges snap to their midpoint only
        elif self.snap == 'GRID':
            step = self._grid_step(region)
            self._hot = np.round(to_uv(region, mouse) / step) * step
        self._free = to_uv(region, mouse) if self._hot is None else None

    def target(self):
        return self._hot if self._hot is not None else self._free

    def _status(self, context):
        label = dict((i[0], i[1]) for i in piv.SNAP_ITEMS)[self.snap]
        context.workspace.status_text_set(
            f"UV Pivot: {label}   |   V Vertex   C Edge   F Face Center   G Grid   X Free"
            f"   |   Click/drag: place   |   D / Enter / Esc: finish")
        if context.area:
            context.area.header_text_set(f"Edit UV Pivot - {label}")

    def hint_lines(self):
        label = dict((i[0], i[1]) for i in piv.SNAP_ITEMS)[self.snap]
        return [
            ("V / C / F / G / X", f"snap: vertex / edge / face / grid / free  ({label})"),
            ("Click / drag", "place the pivot (2D cursor)"),
            ("D / Enter / Esc", "finish"),
            ("Alt + mouse, wheel", "navigate"),
        ]

    def draw_px(self):
        import blf
        context = bpy.context
        region = context.region
        if region is None or region.as_pointer() != self._region_ptr:
            return
        prefs = _prefs(context)
        ui = context.preferences.system.ui_scale
        mouse = np.array(self._mouse, float)
        gpu.state.blend_set('ALPHA')
        pts = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')

        def dots(xy, size, color):
            if len(xy):
                gpu.state.point_size_set(size * ui)
                pts.uniform_float("color", color)
                batch_for_shader(pts, 'POINTS', {"pos": np.asarray(xy, np.float32)}).draw(pts)

        def lines(segs, width, color):
            if len(segs):
                sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
                sh.uniform_float("viewportSize", (region.width, region.height))
                sh.uniform_float("lineWidth", width * ui)
                sh.uniform_float("color", color)
                batch_for_shader(sh, 'LINES', {"pos": np.asarray(segs, np.float32).reshape(-1, 2)}).draw(sh)

        geo = self._geo
        if prefs.pivot_show_candidates:
            if self.snap == 'VERTEX' and len(geo["verts"]):
                dots(to_region(region, geo["verts"]), 7.0, piv.COL_CANDIDATE)
            elif self.snap == 'FACE' and len(geo["centers"]):
                dots(to_region(region, geo["centers"]), 8.0, piv.COL_CANDIDATE)
            elif self.snap == 'EDGE' and len(geo["edges"]):
                a = to_region(region, geo["edges"][:, 0])
                b = to_region(region, geo["edges"][:, 1])
                lines(np.stack([a, b], axis=1), 2.0, piv.COL_EDGE)
                if self._hot_edge is not None:
                    e = geo["edges"][self._hot_edge]
                    ea, eb = to_region(region, e)
                    lines(np.array([[ea, eb]]), 4.0, piv.COL_HOT)
                    dots([(ea + eb) / 2], 11.0, piv.COL_MIDPOINT)
            elif self.snap == 'GRID' and self._hot is not None:
                step = self._grid_step(region)
                g = [self._hot + np.array([i * step, j * step]) for i in range(-4, 5) for j in range(-4, 5)]
                dots(to_region(region, np.array(g)), 4.0, piv.COL_CANDIDATE)
        cur = to_region(region, np.array(context.space_data.cursor_location))
        dots([cur], 10.0, piv.COL_PIVOT)
        tgt = self.target()
        if tgt is not None:
            t2 = to_region(region, tgt)
            if self._hot is not None:
                dots([t2], 16.0, piv.COL_HOT)
            elif self._dragging:
                dots([t2], 10.0, piv.COL_HOT)
            if self._dragging:
                lines(np.array([[cur, t2]]), 1.5, piv.COL_PIVOT)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')
        if prefs.uv_show_hints:
            draw_hints_right(context, region, "UV Pivot", self.hint_lines())

    def invoke(self, context, event):
        global _running
        if _running is not None:
            _running.snap = self.snap
            _running._rebuild(context)
            _running._status(context)
            return {'CANCELLED'}
        self._region = context.region
        self._region_ptr = context.region.as_pointer()
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._dragging = False
        self._placed = False
        self._rebuild(context)
        self._handle = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        _running = self
        self._status(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish(self, context):
        global _running
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        if _running is self:
            _running = None
        return {'FINISHED'} if self._placed else {'CANCELLED'}

    def place(self, context):
        tgt = self.target()
        if tgt is None:
            return
        space = context.space_data
        space.cursor_location = (float(tgt[0]), float(tgt[1]))
        claim_custom_pivot(context, space)
        self._placed = True

    def modal(self, context, event):
        if not _uv_poll(context):
            return self.finish(context)
        context.area.tag_redraw()
        typ, val = event.type, event.value
        mods = event.shift or event.ctrl or event.alt or event.oskey
        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            self._update(context)
            return {'PASS_THROUGH'}
        if typ == 'LEFTMOUSE' and not event.alt:
            if val == 'PRESS':
                self._dragging = True
                return {'RUNNING_MODAL'}
            if val == 'RELEASE' and self._dragging:
                self._dragging = False
                self.place(context)
                return {'RUNNING_MODAL'}
        if val == 'PRESS' and not event.is_repeat and not mods:
            if typ in SNAP_KEYS:
                self.snap = SNAP_KEYS[typ]
                self._rebuild(context)
                self._status(context)
                return {'RUNNING_MODAL'}
            if typ in {'D', 'RET', 'NUMPAD_ENTER', 'ESC', 'RIGHTMOUSE'}:
                if self._dragging:
                    self._dragging = False
                    return {'RUNNING_MODAL'}
                return self.finish(context)
        if typ in SNAP_KEYS or typ == 'D':
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


# A placed pivot belongs to the selection it was placed for, like Maya: once the UV selection
# changes, the UV Editor goes back to its previous pivot (bounding box center by default).
# While the selection only moves (a plain translation), the pivot travels with it, also like Maya.
_custom_pivot = None  # {"prev": pivot_point to restore, "sig": selection signature, "co": (N,2) UVs}
WATCH_INTERVAL = 0.15
FOLLOW_EPS = 1e-6  # UV units: how evenly every selected UV must have moved to count as a translation


def selection_state(context):
    """(signature, coords): which UVs are selected, and where they are (same order)."""
    sig, co = [], []
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        sel = [l for f in visible_faces(context, bm) for l in f.loops if _loop_uv_selected(l, uv)]
        sig.append((obj.name, hash(tuple((l.face.index, l.vert.index) for l in sel))))
        co.extend(tuple(l[uv].uv) for l in sel)
    return tuple(sig), np.array(co, float).reshape(-1, 2)


def selection_signature(context):
    """Cheap fingerprint of which UVs are selected (not where they are)."""
    return selection_state(context)[0]


def translation_between(old, new):
    """The common offset if every point moved by the same amount, else None (rotated, scaled...)."""
    if old.shape != new.shape or not len(old):
        return None
    d = new - old
    mean = d.mean(axis=0)
    if np.abs(d - mean).max() > max(FOLLOW_EPS, 1e-4 * np.abs(mean).max()):
        return None
    return mean


def claim_custom_pivot(context, space):
    global _custom_pivot
    if _custom_pivot is None:
        prev = space.pivot_point if space.pivot_point != 'CURSOR' else 'BOUNDING_BOX_CENTER'
    else:
        prev = _custom_pivot["prev"]
    space.pivot_point = 'CURSOR'
    sig, co = selection_state(context)
    _custom_pivot = {"prev": prev, "sig": sig, "co": co}
    if not bpy.app.timers.is_registered(_watch_custom_pivot):
        bpy.app.timers.register(_watch_custom_pivot, first_interval=WATCH_INTERVAL)


def release_custom_pivot(context=None):
    """Give the UV Editors their previous pivot back."""
    global _custom_pivot
    if _custom_pivot is None:
        return
    prev = _custom_pivot["prev"]
    _custom_pivot = None
    wm = (context or bpy.context).window_manager
    for win in (wm.windows if wm else ()):
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sp = area.spaces.active
                if sp.pivot_point == 'CURSOR':
                    sp.pivot_point = prev
                area.tag_redraw()


def _watch_custom_pivot():
    if _custom_pivot is None:
        return None
    if _running is not None:
        return WATCH_INTERVAL  # still placing it
    global _move_hint
    if _modal_running():
        # Remember which kind of drag this is (a cancelled move must not leave the hint on for a rotate).
        _move_hint = _modal_running(("TRANSFORM_OT_translate",))
        return WATCH_INTERVAL  # mid-drag: follow once the move is confirmed
    context = bpy.context
    try:
        if context.mode != 'EDIT_MESH':
            release_custom_pivot(context)
            return None
        sig, co = selection_state(context)
        if sig != _custom_pivot["sig"]:
            release_custom_pivot(context)
            return None
        offset = translation_between(_custom_pivot["co"], co)
        changed = not np.array_equal(_custom_pivot["co"], co)
        if offset is not None and np.abs(offset).max() > FOLLOW_EPS and (_move_hint or _last_op_was_move(context)):
            follow_custom_pivot(context, offset)
        if changed:
            _move_hint = False
        _custom_pivot["co"] = co
    except Exception:
        release_custom_pivot(context)
        return None
    return WATCH_INTERVAL


MOVE_OPS = {"TRANSFORM_OT_translate", "BLAYA_OT_uv_move"}
_move_hint = False  # a move drag was seen since the last check (Move tool drag or a translate modal)


def _last_op_was_move(context):
    """Only a move drags the pivot along: rotating or scaling a single vertex around the pivot
    also shifts it evenly, but the pivot must stay put then."""
    ops = context.window_manager.operators
    return bool(len(ops)) and ops[-1].bl_idname in MOVE_OPS


def follow_custom_pivot(context, offset):
    wm = context.window_manager
    for win in (wm.windows if wm else ()):
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sp = area.spaces.active
                if sp.pivot_point == 'CURSOR':
                    c = sp.cursor_location
                    sp.cursor_location = (c[0] + float(offset[0]), c[1] + float(offset[1]))
                    area.tag_redraw()


class BLAYA_OT_uv_pivot_exit(bpy.types.Operator):
    """Finish UV pivot editing"""
    bl_idname = "blaya.uv_pivot_exit"
    bl_label = "Finish UV Pivot Edit"

    def execute(self, context):
        if _running is not None:
            _running.finish(context)
        return {'FINISHED'}


def draw_hints_right(context, region, title, rows):
    """Subtle key cheat sheet in the bottom-right corner (right of the UV sidebar if it overlaps)."""
    import blf
    ui = context.preferences.system.ui_scale
    right = 14 * ui
    area = context.area
    if area is not None and context.preferences.system.use_region_overlap:
        right += sum(r.width for r in area.regions if r.type == 'UI' and r.width > 1)
    font = 0
    blf.size(font, 11 * ui)
    line_h = blf.dimensions(font, "Xg")[1] + 5 * ui
    key_w = max(blf.dimensions(font, k)[0] for k, _ in rows) + 10 * ui
    act_w = max(blf.dimensions(font, a)[0] for _, a in rows)
    x = max(8 * ui, region.width - right - key_w - act_w)  # never off the left edge in narrow editors
    y = 14 * ui
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.6)
    blf.shadow_offset(font, 1, -1)
    for key, action in reversed(rows):
        blf.position(font, x, y, 0)
        blf.color(font, 1.0, 1.0, 1.0, 0.75)
        blf.draw(font, key)
        blf.position(font, x + key_w, y, 0)
        blf.color(font, 1.0, 1.0, 1.0, 0.45)
        blf.draw(font, action)
        y += line_h
    blf.position(font, x, y + 2 * ui, 0)
    blf.color(font, 1.0, 1.0, 1.0, 0.75)
    blf.draw(font, title)
    blf.disable(font, blf.SHADOW)


# --------------------------------------------------------------------------- helpers for timers


def _modal_running(prefixes=("TRANSFORM_OT", "transform.")):
    """True while a transform (grab/rotate/scale drag) is running in any window."""
    wm = bpy.context.window_manager
    if wm is None:
        return False
    for win in wm.windows:
        try:
            ops = win.modal_operators
        except AttributeError:
            return False
        if any(op.bl_idname.startswith(prefixes) for op in ops):
            return True
    return False


# --------------------------------------------------------------------------- registration

_classes = (BLAYA_OT_uv_select_mode, BLAYA_OT_uv_click_select, BLAYA_OT_uv_move, BLAYA_OT_uv_straighten,
            BLAYA_OT_uv_pivot_edit, BLAYA_OT_uv_pivot_exit)


def _init_auto():
    try:
        bpy.context.window_manager.blaya_uv_auto = _prefs(bpy.context).uv_smart_select
    except Exception:
        pass
    return None


def register():
    bpy.types.WindowManager.blaya_uv_auto = BoolProperty(
        name="Smart UV Selection", description="A click picks the vertex, edge or face closest to the mouse",
        default=True)
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.app.timers.register(_init_auto, first_interval=0.1)
    bpy.app.timers.register(_face_split_watch, first_interval=SPLIT_INTERVAL, persistent=True)


def unregister():
    global _running
    if _running is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_running._handle, 'WINDOW')
        except Exception:
            pass
        _running = None
    release_custom_pivot()
    for timer in (_init_auto, _watch_custom_pivot, _face_split_watch):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.blaya_uv_auto
