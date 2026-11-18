# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-style pivot editing.

D + V / C / F / G / X starts pivot edit snapping to vertices / edges / face centers / grid / nothing.
Every point the pivot can snap to is highlighted; the one closest to the mouse lights up and the pivot
jumps to it when you click (or drag and release). V/C/F/G/X switch mode while editing; D, Enter,
Esc or right-click finish. Navigation (Alt + mouse, wheel, middle mouse) keeps working.

Works on the selected objects' origins (via Blender's own "Origin to 3D Cursor", so children, curves
and shared data behave as usual). Snap targets are the base meshes of all visible mesh objects,
including the object being edited.
"""

import math

import bpy
import gpu
import numpy as np
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, geometry

SNAP_ITEMS = (
    ('VERTEX', "Vertex", "Snap the pivot to vertices", 'SNAP_VERTEX', 0),
    ('EDGE', "Edge", "Snap the pivot anywhere along edges", 'SNAP_EDGE', 1),
    ('FACE', "Face Center", "Snap the pivot to the center of faces", 'SNAP_FACE_CENTER', 2),
    ('GRID', "Grid", "Snap the pivot to the grid", 'SNAP_GRID', 3),
    ('NONE', "Free", "Move the pivot without snapping", 'SNAP_OFF', 4),
)
_LABELS = {i[0]: i[1] for i in SNAP_ITEMS}
_MODE_KEYS = {'V': 'VERTEX', 'C': 'EDGE', 'F': 'FACE', 'G': 'GRID', 'X': 'NONE'}
_ORIGIN_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'ARMATURE', 'LATTICE', 'GREASEPENCIL', 'CURVES',
                 'POINTCLOUD'}

MAX_SNAP_POINTS = 400_000  # candidates gathered from visible meshes (selected meshes always included)
MAX_DRAW_POINTS = 40_000   # dots drawn; beyond this only those near the mouse are drawn
MAX_DRAW_EDGES = 30_000

COL_CANDIDATE = (0.35, 0.75, 1.0, 0.75)
COL_EDGE = (0.35, 0.75, 1.0, 0.35)
COL_HOT = (1.0, 0.85, 0.1, 1.0)
COL_PIVOT = (1.0, 0.45, 0.05, 1.0)
COL_TICK = (1.0, 1.0, 1.0, 0.9)
COL_MIDPOINT = COL_CANDIDATE[:3] + (1.0,)  # same blue as vertex snap points, fully opaque

_running = None  # the active pivot edit operator, if any


def _prefs(context):
    return context.preferences.addons[__package__].preferences


def in_pivot_edit():
    return _running is not None


# --------------------------------------------------------------------------- geometry helpers

def _np_matrix(m):
    return np.array([list(r) for r in m], dtype=np.float64)


def gather_candidates(objects, mode):
    """World-space snap data for `mode`.

    VERTEX: points (N,3). FACE: points (N,3) + normals (N,3). EDGE: segments (M,2,3).
    """
    pts, nors, segs = [], [], []
    total = 0
    for obj in objects:
        me = obj.data
        if me is None or obj.type != 'MESH':
            continue
        nv, nf, ne = len(me.vertices), len(me.polygons), len(me.edges)
        cost = {'VERTEX': nv, 'FACE': nf, 'EDGE': ne}.get(mode, 0)
        if cost == 0 or (total and total + cost > MAX_SNAP_POINTS):
            continue
        total += cost
        mw = _np_matrix(obj.matrix_world)
        rot, loc = mw[:3, :3], mw[:3, 3]
        if mode in {'VERTEX', 'EDGE'}:
            co = np.empty(nv * 3, np.float32)
            me.vertices.foreach_get("co", co)
            world = co.reshape(nv, 3).astype(np.float64) @ rot.T + loc
            if mode == 'VERTEX':
                pts.append(world)
            else:
                idx = np.empty(ne * 2, np.int32)
                me.edges.foreach_get("vertices", idx)
                segs.append(world[idx.reshape(ne, 2)])
        elif mode == 'FACE':
            cen = np.empty(nf * 3, np.float32)
            nor = np.empty(nf * 3, np.float32)
            me.polygons.foreach_get("center", cen)
            me.polygons.foreach_get("normal", nor)
            pts.append(cen.reshape(nf, 3).astype(np.float64) @ rot.T + loc)
            nrm = nor.reshape(nf, 3).astype(np.float64) @ np.linalg.inv(rot)  # inverse-transpose
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            nors.append(nrm)
    cat = lambda xs, shape: np.concatenate(xs) if xs else np.zeros(shape)
    return {
        "points": cat(pts, (0, 3)),
        "normals": cat(nors, (0, 3)),
        "segments": cat(segs, (0, 2, 3)),
    }


def project(rv3d, region, pts):
    """World points (N,3) -> region pixels (N,2), clip-space w (N,), visible mask (N,)."""
    if len(pts) == 0:
        return np.zeros((0, 2)), np.zeros(0), np.zeros(0, bool)
    pm = _np_matrix(rv3d.perspective_matrix)
    hom = pts @ pm[:, :3].T + pm[:, 3]
    w = hom[:, 3]
    ok = w > 1e-6
    safe_w = np.where(ok, w, 1.0)
    ndc = hom[:, :3] / safe_w[:, None]
    xy = np.empty((len(pts), 2))
    xy[:, 0] = (ndc[:, 0] + 1.0) * 0.5 * region.width
    xy[:, 1] = (ndc[:, 1] + 1.0) * 0.5 * region.height
    ok &= (np.abs(ndc[:, 2]) <= 1.0) & (xy[:, 0] >= 0) & (xy[:, 0] <= region.width) \
        & (xy[:, 1] >= 0) & (xy[:, 1] <= region.height)
    return xy, w, ok


def front_facing(rv3d, points, normals):
    """Mask of faces whose front side looks at the viewer (hides face centers on the far side)."""
    if len(points) == 0:
        return np.zeros(0, bool)
    vinv = _np_matrix(rv3d.view_matrix.inverted())
    if rv3d.is_perspective:
        to_face = points - vinv[:3, 3]
    else:
        to_face = np.broadcast_to(-vinv[:3, 2], points.shape)
    return np.einsum("ij,ij->i", normals, to_face) < 0.0


def nearest_point(xy, ok, mouse, radius):
    """Index of the visible screen point closest to `mouse` within `radius`, or None."""
    if not ok.any():
        return None
    d2 = np.sum((xy - mouse) ** 2, axis=1)
    d2[~ok] = np.inf
    i = int(np.argmin(d2))
    return i if d2[i] <= radius * radius else None


def quantize(s, step):
    """Snap an edge parameter (0..1) to multiples of `step`; both ends and the midpoint are always allowed."""
    if step <= 0.0:
        return s
    return min(edge_stops(step), key=lambda v: abs(v - s))


def edge_stops(step):
    """Edge parameters marked on the highlighted edge (empty when stepping is off).
    Always includes both ends and the midpoint (0.5)."""
    if step <= 0.0:
        return []
    return sorted({round(k * step, 9) for k in range(int(1.0 / step + 1e-9) + 1)} | {0.5, 1.0})


def nearest_on_edges(rv3d, region, segs, mouse, radius, step=0.0):
    """Closest point to the mouse along any edge (perspective-correct), optionally in `step` fractions
    of the edge length. Returns (edge_index, world point, edge parameter)."""
    if len(segs) == 0:
        return None
    a, wa, oka = project(rv3d, region, segs[:, 0])
    b, wb, okb = project(rv3d, region, segs[:, 1])
    ok = oka & okb
    if not ok.any():
        return None
    ab = b - a
    len2 = np.maximum(np.sum(ab * ab, axis=1), 1e-12)
    t = np.clip(np.sum((mouse - a) * ab, axis=1) / len2, 0.0, 1.0)
    d2 = np.sum((a + ab * t[:, None] - mouse) ** 2, axis=1)
    d2[~ok] = np.inf
    i = int(np.argmin(d2))
    if d2[i] > radius * radius:
        return None
    ti, wai, wbi = t[i], wa[i], wb[i]
    s = ti * wai / max(ti * wai + (1.0 - ti) * wbi, 1e-12)  # screen param -> 3D param
    s = quantize(s, step)
    return i, Vector(segs[i, 0] + (segs[i, 1] - segs[i, 0]) * s), s


def view_plane_point(region, rv3d, mouse, through, normal):
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
    hit = geometry.intersect_line_plane(origin, origin + direction, through, normal)
    return hit


def grid_snap(context, region, rv3d, mouse, ref):
    """Snap to the grid: on the ground plane in perspective views, on the view plane in ortho views."""
    view_dir = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
    if rv3d.is_perspective and abs(view_dir.z) > 0.2:
        normal = Vector((0.0, 0.0, 1.0))
    else:
        normal = view_dir
    hit = view_plane_point(region, rv3d, mouse, ref, normal)
    if hit is None:
        return None, None, None
    # Grid step: overlay grid scale times a power of 10 that keeps cells at least ~14 px apart.
    base = context.space_data.overlay.grid_scale if context.space_data else 1.0
    p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, hit)
    right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, hit + right * base)
    px = (p1 - p0).length if (p0 is not None and p1 is not None) else 100.0
    step = base
    if px > 0:
        step = base * 10.0 ** math.ceil(math.log10(max(14.0 / px, 1e-9)))
    axis = max(range(3), key=lambda k: abs(normal[k]))  # keep the plane's own axis
    snapped = Vector(hit)
    for k in range(3):
        if k != axis:
            snapped[k] = round(hit[k] / step) * step
    return snapped, step, axis


def set_origins(context, objects, delta):
    """Move the origin of each object by `delta` (world), keeping geometry where it is."""
    scene = context.scene
    view_layer = context.view_layer
    cursor = scene.cursor
    saved_cursor = cursor.location.copy()
    saved_sel = [o for o in context.selected_objects]
    saved_active = view_layer.objects.active
    try:
        for obj in objects:
            for o in saved_sel:
                o.select_set(False)
            obj.select_set(True)
            view_layer.objects.active = obj
            cursor.location = obj.matrix_world.translation + delta
            with context.temp_override(selected_editable_objects=[obj], active_object=obj, object=obj):
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    finally:
        cursor.location = saved_cursor
        for o in context.selected_objects:
            o.select_set(False)
        for o in saved_sel:
            o.select_set(True)
        view_layer.objects.active = saved_active


# --------------------------------------------------------------------------- operator

class BLAYA_OT_pivot_edit(bpy.types.Operator):
    """Edit the pivot (origin) of the selected objects with highlighted snap points.
    V vertex, C edge, F face center, G grid, X free. Click or drag to place. D, Enter, Esc or right-click finish"""
    bl_idname = "blaya.pivot_edit"
    bl_label = "Edit Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    snap: EnumProperty(name="Snap", items=SNAP_ITEMS, default='VERTEX')

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.area is not None and context.area.type == 'VIEW_3D'
                and any(o.type in _ORIGIN_TYPES for o in context.selected_objects))

    # -- state

    def _targets(self, context):
        return [o for o in context.selected_objects if o.type in _ORIGIN_TYPES]

    def _ref(self, context):
        act = context.active_object
        if act is not None and act in self._targets(context):
            return act.matrix_world.translation.copy()
        objs = self._targets(context)
        return objs[0].matrix_world.translation.copy() if objs else Vector()

    def _rebuild(self, context):
        if self.snap in {'VERTEX', 'EDGE', 'FACE'}:
            sel = [o for o in context.selected_objects if o.type == 'MESH']
            others = [o for o in context.visible_objects if o.type == 'MESH' and o not in sel]
            self._cand = gather_candidates(sel + others, self.snap)
        else:
            self._cand = {"points": np.zeros((0, 3)), "normals": np.zeros((0, 3)), "segments": np.zeros((0, 2, 3))}
        self._ref_pt = self._ref(context)
        self._update_target(context)

    def _status(self, context):
        label = _LABELS[self.snap]
        if self.snap == 'EDGE':
            step = _prefs(context).pivot_edge_step
            label += f" (every {step:g}%)" if step > 0 else " (free along edge)"
        text = (f"Pivot: {label}   |   V Vertex   C Edge   F Face Center   G Grid   X Free"
                f"   |   Click/drag: place   |   D / Enter / Esc: finish")
        context.workspace.status_text_set(text)
        if context.area:
            context.area.header_text_set(f"Edit Pivot - {label}")

    def _update_target(self, context):
        region, rv3d = self._region, self._region.data
        mouse = np.array(self._mouse, dtype=np.float64)
        mvec = Vector(self._mouse)
        radius = _prefs(context).pivot_snap_radius
        self._hot = None       # world point it would snap to
        self._hot_edge = None
        self._hot_t = None
        self._grid = None
        if self.snap in {'VERTEX', 'FACE'}:
            pts = self._cand["points"]
            xy, _w, ok = project(rv3d, region, pts)
            if self.snap == 'FACE':
                ok &= front_facing(rv3d, pts, self._cand["normals"])
            i = nearest_point(xy, ok, mouse, radius)
            if i is not None:
                self._hot = Vector(pts[i])
        elif self.snap == 'EDGE':
            step = _prefs(context).pivot_edge_step / 100.0
            res = nearest_on_edges(rv3d, region, self._cand["segments"], mouse, radius, step)
            if res is not None:
                self._hot_edge, self._hot, self._hot_t = res
        elif self.snap == 'GRID':
            pt, step, axis = grid_snap(context, region, rv3d, mvec, self._ref_pt)
            if pt is not None:
                self._hot = pt
                self._grid = (step, axis)
        # Free placement (no snap target nearby, or Free mode): follow the mouse on the view plane.
        if self._hot is None:
            normal = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
            self._free = view_plane_point(region, rv3d, mvec, self._ref_pt, normal)
        else:
            self._free = None

    def target(self):
        return self._hot if self._hot is not None else self._free

    # -- drawing

    def draw_px(self):
        context = bpy.context
        if context.region is None or context.region.as_pointer() != self._region_ptr:
            return
        region, rv3d = context.region, context.region_data
        prefs = _prefs(context)
        ui = context.preferences.system.ui_scale  # follows display DPI and the UI scale preference
        gpu.state.blend_set('ALPHA')
        pshader = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
        mouse = np.array(self._mouse, dtype=np.float64)

        def dots(xy, size, color):
            if len(xy) == 0:
                return
            gpu.state.point_size_set(size * ui)
            batch = batch_for_shader(pshader, 'POINTS', {"pos": np.asarray(xy, np.float32)})
            pshader.uniform_float("color", color)
            batch.draw(pshader)

        def lines(segs2d, width, color):
            if len(segs2d) == 0:
                return
            lshader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
            lshader.uniform_float("viewportSize", (region.width, region.height))
            lshader.uniform_float("lineWidth", width * ui)
            lshader.uniform_float("color", color)
            batch = batch_for_shader(lshader, 'LINES', {"pos": np.asarray(segs2d, np.float32).reshape(-1, 2)})
            batch.draw(lshader)

        if prefs.pivot_show_candidates:
            if self.snap in {'VERTEX', 'FACE'}:
                pts = self._cand["points"]
                xy, _w, ok = project(rv3d, region, pts)
                if self.snap == 'FACE':
                    ok &= front_facing(rv3d, pts, self._cand["normals"])
                xy = xy[ok]
                if len(xy) > MAX_DRAW_POINTS:
                    d2 = np.sum((xy - mouse) ** 2, axis=1)
                    xy = xy[np.argsort(d2)[:MAX_DRAW_POINTS]]
                dots(xy, 8.0 if self.snap == 'FACE' else 7.0, COL_CANDIDATE)
            elif self.snap == 'EDGE':
                segs = self._cand["segments"]
                if len(segs):
                    a, _wa, oka = project(rv3d, region, segs[:, 0])
                    b, _wb, okb = project(rv3d, region, segs[:, 1])
                    ok = oka & okb
                    a, b = a[ok], b[ok]
                    if len(a) > MAX_DRAW_EDGES:
                        mid = (a + b) * 0.5
                        keep = np.argsort(np.sum((mid - mouse) ** 2, axis=1))[:MAX_DRAW_EDGES]
                        a, b = a[keep], b[keep]
                    lines(np.stack([a, b], axis=1), 2.0, COL_EDGE)
                if self._hot_edge is not None:
                    seg = segs[self._hot_edge]
                    a, _w, ok = project(rv3d, region, seg)
                    if ok.all():
                        lines(a.reshape(1, 2, 2), 4.0, COL_HOT)
                    # Step marks along the highlighted edge (e.g. every 5% of its length).
                    stops = [s for s in edge_stops(prefs.pivot_edge_step / 100.0) if s != 0.5]
                    if stops:
                        pts = seg[0] + np.outer(stops, seg[1] - seg[0])
                        xy, _w, ok = project(rv3d, region, pts)
                        dots(xy[ok], 6.0, COL_TICK)
                    # The midpoint is the main mark: bigger, in the same blue as vertex snap points.
                    mid, _w, ok = project(rv3d, region, ((seg[0] + seg[1]) * 0.5)[None, :])
                    dots(mid[ok], 11.0, COL_MIDPOINT)
            elif self.snap == 'GRID' and self._grid is not None and self._hot is not None:
                step, axis = self._grid
                u, v = [k for k in range(3) if k != axis]
                around = []
                for i in range(-4, 5):
                    for j in range(-4, 5):
                        p = Vector(self._hot)
                        p[u] += i * step
                        p[v] += j * step
                        around.append(tuple(p))
                xy, _w, ok = project(rv3d, region, np.array(around))
                dots(xy[ok], 4.0, COL_CANDIDATE)

        # Current pivot, the snap target and a guide line between them.
        ref2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self._ref_pt)
        tgt = self.target()
        tgt2d = view3d_utils.location_3d_to_region_2d(region, rv3d, tgt) if tgt is not None else None
        if ref2d is not None and tgt2d is not None and self._dragging:
            lines(np.array([[ref2d, tgt2d]]), 1.5, COL_PIVOT)
        if ref2d is not None:
            dots([ref2d], 10.0, COL_PIVOT)
        if tgt2d is not None and self._hot is not None:
            dots([tgt2d], 16.0, COL_HOT)
        elif tgt2d is not None and self._dragging:
            dots([tgt2d], 10.0, COL_HOT)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')

    # -- lifecycle

    def invoke(self, context, event):
        global _running
        if _running is not None:
            # Already editing: just switch the snap mode.
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
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        _running = self
        self._status(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        # Non-interactive use (e.g. from a script): nothing to place without a mouse.
        return {'CANCELLED'}

    def finish(self, context):
        global _running
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
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
        objs = self._targets(context)
        if tgt is None or not objs:
            return
        delta = Vector(tgt) - self._ref_pt
        if delta.length < 1e-9:
            return
        set_origins(context, objs, delta)
        self._placed = True
        self._rebuild(context)

    def modal(self, context, event):
        if context.mode != 'OBJECT' or context.area is None:
            return self.finish(context)
        context.area.tag_redraw()
        typ, val = event.type, event.value
        mods = event.shift or event.ctrl or event.alt or event.oskey

        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            self._update_target(context)
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
            if typ in _MODE_KEYS:
                self.snap = _MODE_KEYS[typ]
                self._rebuild(context)
                self._status(context)
                return {'RUNNING_MODAL'}
            if typ in {'D', 'RET', 'NUMPAD_ENTER', 'ESC', 'RIGHTMOUSE'}:
                if self._dragging:  # cancel the drag only
                    self._dragging = False
                    return {'RUNNING_MODAL'}
                return self.finish(context)

        if typ in _MODE_KEYS or typ == 'D':
            return {'RUNNING_MODAL'}  # swallow key repeats / releases of our own keys
        return {'PASS_THROUGH'}  # navigation and everything else


class BLAYA_OT_pivot_exit(bpy.types.Operator):
    """Finish pivot editing (also turns off Blender's "Affect Only Origins" if it was left on)"""
    bl_idname = "blaya.pivot_exit"
    bl_label = "Finish Pivot Edit"

    def execute(self, context):
        if _running is not None:
            _running.finish(context)
        ts = context.scene.tool_settings
        if ts.use_transform_data_origin:
            ts.use_transform_data_origin = False
        return {'FINISHED'}


class BLAYA_OT_snap_vertex_toggle(bpy.types.Operator):
    """Toggle snapping, set to vertices when turning it on"""
    bl_idname = "blaya.snap_vertex_toggle"
    bl_label = "Toggle Vertex Snap"

    def execute(self, context):
        ts = context.scene.tool_settings
        ts.use_snap = not ts.use_snap
        if ts.use_snap:
            ts.snap_elements_base = {'VERTEX'}
        self.report({'INFO'}, "Vertex snap on" if ts.use_snap else "Snap off")
        return {'FINISHED'}


_classes = (BLAYA_OT_pivot_edit, BLAYA_OT_pivot_exit, BLAYA_OT_snap_vertex_toggle)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    global _running
    if _running is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_running._handle, 'WINDOW')
        except Exception:
            pass
        _running = None
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
