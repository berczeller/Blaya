# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-style pivot editing with a move gizmo.

D + V / C / F / G / X starts pivot edit snapping to vertices / edge midpoints / face centers / grid /
nothing. A move gizmo sits on the pivot: drag its white center to move the pivot on the view plane, or
one of its axes to move it along that axis only. While dragging, the pivot snaps to the highlighted
target under the mouse (projected onto the axis when an axis is dragged), or to the grid with G.
Ctrl turns snapping off for the drag. Clicking a highlighted snap point also puts the pivot right on it.
V/C/F/G/X switch mode while editing; D, Enter, Esc or right-click finish. Navigation keeps working.

Works on the selected objects' origins (via Blender's own "Origin to 3D Cursor", so children, curves
and shared data behave as usual). Only the origin moves: rotation, scale and the geometry stay put.
Snap targets are the base meshes of all visible mesh objects, including the object being edited.
"""

import math

import bpy
import gpu
import numpy as np
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, geometry

SNAP_ITEMS = (
    ('VERTEX', "Vertex", "Snap the pivot to vertices", 'SNAP_VERTEX', 0),
    ('EDGE', "Edge Midpoint", "Snap the pivot to the middle of edges", 'SNAP_MIDPOINT', 1),
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
COL_MIDPOINT = COL_CANDIDATE[:3] + (1.0,)  # same blue as vertex snap points, fully opaque
COL_CENTER = (1.0, 1.0, 1.0, 0.9)
COL_GHOST = (0.75, 0.75, 0.75, 0.6)

AXIS_HIDE_DOT = 0.97   # hide an axis that points (almost) straight at the viewer
CLICK_SLOP = 4.0       # pixels the mouse may move and still count as a click

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

    VERTEX: points (N,3). FACE: points (N,3) + normals (N,3). EDGE: midpoints (M,3) + segments (M,2,3).
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
                seg = world[idx.reshape(ne, 2)]
                segs.append(seg)
                pts.append(seg.mean(axis=1))
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


def nearest_point(xy, ok, mouse, radius, depth=None):
    """Index of the visible screen point closest to `mouse` within `radius`, or None.

    `depth` (distance along the view) breaks ties between points on the same pixel, like the front and
    back corners of a box in an orthographic view: the one closest to the viewer wins.
    """
    if not ok.any():
        return None
    d2 = np.sum((xy - mouse) ** 2, axis=1)
    d2[~ok] = np.inf
    i = int(np.argmin(d2))
    if d2[i] > radius * radius:
        return None
    if depth is not None:
        tied = np.flatnonzero(np.sqrt(d2) <= np.sqrt(d2[i]) + 1.0)
        i = int(tied[np.argmin(depth[tied])])
    return i


def view_depth(rv3d, pts):
    """Distance of world points along the view direction (smaller is closer to the viewer)."""
    if len(pts) == 0:
        return np.zeros(0)
    return pts @ np.array(view_direction(rv3d))


def nearest_edge(rv3d, region, segs, mouse, radius):
    """Index of the edge closest to the mouse on screen within `radius`, or None (front-most on ties)."""
    if len(segs) == 0:
        return None
    a, _wa, oka = project(rv3d, region, segs[:, 0])
    b, _wb, okb = project(rv3d, region, segs[:, 1])
    ok = oka & okb
    if not ok.any():
        return None
    ab = b - a
    t = np.clip(np.sum((mouse - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
    d2 = np.sum((a + ab * t[:, None] - mouse) ** 2, axis=1)
    d2[~ok] = np.inf
    i = int(np.argmin(d2))
    if d2[i] > radius * radius:
        return None
    tied = np.flatnonzero(np.sqrt(d2) <= np.sqrt(d2[i]) + 1.0)
    return int(tied[np.argmin(view_depth(rv3d, segs[tied].mean(axis=1)))])


def view_direction(rv3d):
    return (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()


def view_plane_point(region, rv3d, mouse, through, normal):
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
    return geometry.intersect_line_plane(origin, origin + direction, through, normal)


def axis_param(region, rv3d, mouse, through, axis):
    """Parameter t of the point on the line `through + t * axis` closest to the mouse ray, or None
    when the axis points along the ray."""
    o = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    d = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse).normalized()
    u = axis.normalized()
    w0 = through - o
    b = u.dot(d)
    den = 1.0 - b * b
    if den < 1e-9:
        return None
    return (b * d.dot(w0) - u.dot(w0)) / den


def grid_step(context, region, rv3d, at):
    """Overlay grid scale times a power of 10 that keeps grid cells at least ~14 px apart at `at`."""
    space = context.space_data
    base = space.overlay.grid_scale if space is not None and space.type == 'VIEW_3D' else 1.0
    p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, at)
    right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, at + right * base)
    px = (p1 - p0).length if (p0 is not None and p1 is not None) else 100.0
    if px <= 0:
        return base
    return base * 10.0 ** math.ceil(math.log10(max(14.0 / px, 1e-9)))


def snap_round(value, step):
    return round(value / step) * step


def gizmo_matrix(context, rv3d, obj):
    """Orientation of the gizmo axes (columns), from the header's Transform Orientation."""
    slot = context.scene.transform_orientation_slots[0]
    kind = slot.type
    if kind in {'LOCAL', 'NORMAL', 'GIMBAL', 'PARENT'} and obj is not None:
        mw = obj.matrix_world if kind != 'PARENT' or obj.parent is None else obj.parent.matrix_world
        return mw.to_quaternion().to_matrix()
    if kind == 'VIEW':
        return rv3d.view_rotation.to_matrix()
    if kind == 'CURSOR':
        return context.scene.cursor.matrix.to_quaternion().to_matrix()
    custom = getattr(slot, "custom_orientation", None)
    if custom is not None:
        return custom.matrix.to_quaternion().to_matrix()
    return Matrix.Identity(3)


def gizmo_layout(region, rv3d, origin, axes, size):
    """Screen geometry of the gizmo: center (2,), center radius, and per axis (start, tip) or None."""
    c = view3d_utils.location_3d_to_region_2d(region, rv3d, origin)
    if c is None:
        return None
    radius = size * 0.2
    view = view_direction(rv3d)
    arrows = []
    for k in range(3):
        u = axes.col[k].normalized()
        if abs(u.dot(view)) > AXIS_HIDE_DOT:
            arrows.append(None)
            continue
        # Screen direction of the axis at the pivot (perspective-correct for a short step).
        eps = max(rv3d.view_distance, 1e-3) * 1e-3
        p = view3d_utils.location_3d_to_region_2d(region, rv3d, origin + u * eps)
        if p is None or (p - c).length < 1e-9:
            arrows.append(None)
            continue
        d = (p - c).normalized()
        arrows.append((c + d * radius * 1.4, c + d * size))
    return c, radius, arrows


def pick_handle(layout, mouse, tolerance):
    """'CENTER', an axis index 0-2, or None for the gizmo part under the mouse."""
    if layout is None:
        return None
    c, radius, arrows = layout
    m = Vector(mouse)
    best, best_d = None, tolerance
    for k, arr in enumerate(arrows):
        if arr is None:
            continue
        a, b = arr
        ab = b - a
        t = max(0.0, min(1.0, (m - a).dot(ab) / max(ab.length_squared, 1e-9)))
        d = (a + ab * t - m).length
        if d < best_d:
            best, best_d = k, d
    if best is not None:
        return best
    return 'CENTER' if (m - c).length <= radius + tolerance else None


def drag_target(context, region, rv3d, handle, start, axes, grab, mouse, snap, hot):
    """Where the pivot goes for a drag of `handle` that started at `start`.

    grab: the view-plane point (CENTER) or axis parameter (axis) under the mouse when the drag began.
    hot: world point of the snap target under the mouse, or None. snap: current snap mode, or None
    when snapping is off for this drag.
    """
    if handle == 'CENTER':
        if hot is not None and snap in {'VERTEX', 'EDGE', 'FACE'}:
            return Vector(hot)
        hit = view_plane_point(region, rv3d, mouse, start, view_direction(rv3d))
        if hit is None:
            return start.copy()
        new = start + (hit - grab)
        if snap == 'GRID':
            # Keep the coordinate along the view's main axis, round the two that move on screen.
            view = view_direction(rv3d)
            keep = max(range(3), key=lambda k: abs(view[k]))
            step = grid_step(context, region, rv3d, new)
            for k in range(3):
                new[k] = start[k] if k == keep else snap_round(new[k], step)
        return new
    u = axes.col[handle].normalized()
    if hot is not None and snap in {'VERTEX', 'EDGE', 'FACE'}:
        return start + u * u.dot(Vector(hot) - start)
    t = axis_param(region, rv3d, mouse, start, u)
    if t is None:
        return start.copy()
    disp = t - grab
    if snap == 'GRID':
        step = grid_step(context, region, rv3d, start + u * disp)
        world_axis = max(range(3), key=lambda k: abs(u[k]))
        if abs(abs(u[world_axis]) - 1.0) < 1e-6:
            # Axis is a world axis: land on the absolute grid, not just whole steps from the start.
            sign = 1.0 if u[world_axis] > 0 else -1.0
            disp = (snap_round(start[world_axis] + sign * disp, step) - start[world_axis]) * sign
        else:
            disp = snap_round(disp, step)
    return start + u * disp


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
    """Edit the pivot (origin) of the selected objects with a move gizmo and highlighted snap points.
    V vertex, C edge midpoint, F face center, G grid, X free. Drag the gizmo center or an axis;
    click a highlighted point to jump there. D, Enter, Esc or right-click finish"""
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

    def _ref_object(self, context):
        act = context.active_object
        objs = self._targets(context)
        if act is not None and act in objs:
            return act
        return objs[0] if objs else None

    def _rebuild(self, context):
        if self.snap in {'VERTEX', 'EDGE', 'FACE'}:
            sel = [o for o in context.selected_objects if o.type == 'MESH']
            others = [o for o in context.visible_objects if o.type == 'MESH' and o not in sel]
            self._cand = gather_candidates(sel + others, self.snap)
        else:
            self._cand = {"points": np.zeros((0, 3)), "normals": np.zeros((0, 3)), "segments": np.zeros((0, 2, 3))}
        obj = self._ref_object(context)
        self._pivot = obj.matrix_world.translation.copy() if obj is not None else Vector()
        self._axes = gizmo_matrix(context, self._region.data, obj)
        self._update_hover(context)

    def _size(self, context):
        prefs = context.preferences
        return prefs.view.gizmo_size * prefs.system.ui_scale

    def _layout(self, context, at=None):
        return gizmo_layout(self._region, self._region.data, self._pivot if at is None else at,
                            self._axes, self._size(context))

    def _find_hot(self, context):
        """(world point, edge index) of the snap target under the mouse for V / C / F, or (None, None)."""
        if self.snap not in {'VERTEX', 'EDGE', 'FACE'}:
            return None, None
        region, rv3d = self._region, self._region.data
        mouse = np.array(self._mouse, dtype=np.float64)
        radius = _prefs(context).pivot_snap_radius
        pts = self._cand["points"]
        if self.snap == 'EDGE':
            i = nearest_edge(rv3d, region, self._cand["segments"], mouse, radius)
            return (Vector(pts[i]), i) if i is not None else (None, None)
        xy, _w, ok = project(rv3d, region, pts)
        if self.snap == 'FACE':
            ok &= front_facing(rv3d, pts, self._cand["normals"])
        i = nearest_point(xy, ok, mouse, radius, view_depth(rv3d, pts))
        return (Vector(pts[i]), None) if i is not None else (None, None)

    def _update_hover(self, context):
        self._hover = None
        if self._drag is None:
            ui = context.preferences.system.ui_scale
            self._hover = pick_handle(self._layout(context), self._mouse, 8.0 * ui)
        self._hot, self._hot_edge = self._find_hot(context)
        if self._hover is not None:
            self._hot, self._hot_edge = None, None  # the gizmo wins over snap points under it

    def _status(self, context, extra=""):
        label = _LABELS[self.snap]
        text = (f"Pivot: {label}   |   V Vertex   C Edge Midpoint   F Face Center   G Grid   X Free"
                f"   |   Drag gizmo center / axis   Click point: snap   Ctrl: no snap"
                f"   |   D / Enter / Esc: finish")
        context.workspace.status_text_set(text)
        if context.area:
            p = self._pivot_preview if self._drag is not None else self._pivot
            head = f"Edit Pivot - {label}   X {p.x:.4f}  Y {p.y:.4f}  Z {p.z:.4f}"
            context.area.header_text_set(head + extra)

    # -- dragging (kept separate from modal() so it can be driven directly)

    def begin_drag(self, context, handle):
        region, rv3d = self._region, self._region.data
        if handle == 'CENTER':
            grab = view_plane_point(region, rv3d, Vector(self._mouse), self._pivot, view_direction(rv3d))
        else:
            grab = axis_param(region, rv3d, Vector(self._mouse), self._pivot, self._axes.col[handle])
        if grab is None:
            return False
        self._drag = (handle, self._pivot.copy(), grab)
        self._pivot_preview = self._pivot.copy()
        self._hover = None
        return True

    def update_drag(self, context, ctrl=False):
        handle, start, grab = self._drag
        self._hot, self._hot_edge = (None, None) if ctrl else self._find_hot(context)
        snap = None if ctrl else self.snap
        self._pivot_preview = drag_target(context, self._region, self._region.data, handle, start, self._axes,
                                          grab, Vector(self._mouse), snap, self._hot)
        self._status(context)

    def end_drag(self, context, apply=True):
        handle, start, _grab = self._drag
        target = self._pivot_preview
        self._drag = None
        if apply:
            self.move_pivot(context, target)
        self._update_hover(context)
        self._status(context)

    def move_pivot(self, context, target):
        objs = self._targets(context)
        delta = Vector(target) - self._pivot
        if not objs or delta.length < 1e-9:
            return False
        set_origins(context, objs, delta)
        self._placed = True
        self._rebuild(context)
        return True

    # -- drawing

    def draw_px(self):
        context = bpy.context
        if context.region is None or context.region.as_pointer() != self._region_ptr:
            return
        region, rv3d = context.region, context.region_data
        prefs = _prefs(context)
        ui = context.preferences.system.ui_scale
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

        def tris(pts2d, color):
            sh = gpu.shader.from_builtin('UNIFORM_COLOR')
            sh.uniform_float("color", color)
            batch_for_shader(sh, 'TRIS', {"pos": np.asarray(pts2d, np.float32)}).draw(sh)

        if prefs.pivot_show_candidates:
            pts = self._cand["points"]
            if self.snap in {'VERTEX', 'FACE'}:
                xy, _w, ok = project(rv3d, region, pts)
                if self.snap == 'FACE':
                    ok &= front_facing(rv3d, pts, self._cand["normals"])
                xy = xy[ok]
                if len(xy) > MAX_DRAW_POINTS:
                    xy = xy[np.argsort(np.sum((xy - mouse) ** 2, axis=1))[:MAX_DRAW_POINTS]]
                dots(xy, 8.0 if self.snap == 'FACE' else 7.0, COL_CANDIDATE)
            elif self.snap == 'EDGE':
                segs = self._cand["segments"]
                if len(segs):
                    a, _wa, oka = project(rv3d, region, segs[:, 0])
                    b, _wb, okb = project(rv3d, region, segs[:, 1])
                    ok = oka & okb
                    a, b = a[ok], b[ok]
                    if len(a) > MAX_DRAW_EDGES:
                        keep = np.argsort(np.sum(((a + b) * 0.5 - mouse) ** 2, axis=1))[:MAX_DRAW_EDGES]
                        a, b = a[keep], b[keep]
                    lines(np.stack([a, b], axis=1), 2.0, COL_EDGE)
                    dots((a + b) * 0.5, 7.0, COL_CANDIDATE)
                if self._hot_edge is not None:
                    seg, _w, ok = project(rv3d, region, segs[self._hot_edge])
                    if ok.all():
                        lines(seg.reshape(1, 2, 2), 3.0, COL_HOT)
            elif self.snap == 'GRID':
                at = self._pivot_preview if self._drag is not None else self._pivot
                step = grid_step(context, region, rv3d, at)
                view = view_direction(rv3d)
                keep = max(range(3), key=lambda k: abs(view[k]))
                u, v = [k for k in range(3) if k != keep]
                base = Vector(at)
                base[u], base[v] = snap_round(base[u], step), snap_round(base[v], step)
                around = []
                for i in range(-4, 5):
                    for j in range(-4, 5):
                        p = Vector(base)
                        p[u] += i * step
                        p[v] += j * step
                        around.append(tuple(p))
                xy, _w, ok = project(rv3d, region, np.array(around))
                dots(xy[ok], 4.0, COL_CANDIDATE)

        if self._hot is not None:
            hot2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self._hot)
            if hot2d is not None:
                dots([hot2d], 14.0, COL_HOT)

        theme = context.preferences.themes[0].user_interface
        axis_cols = [tuple(theme.axis_x) + (1.0,), tuple(theme.axis_y) + (1.0,), tuple(theme.axis_z) + (1.0,)]

        at = self._pivot
        if self._drag is not None:
            handle, start, _grab = self._drag
            at = self._pivot_preview
            s2d = view3d_utils.location_3d_to_region_2d(region, rv3d, start)
            if s2d is not None:
                dots([s2d], 8.0, COL_GHOST)  # where the pivot was
            if handle != 'CENTER':
                # The constraint line through the start, like Blender's own axis constraint.
                u = self._axes.col[handle].normalized()
                ends = []
                for sign in (-1.0, 1.0):
                    # In perspective a far end can fall behind the camera: shorten it until it projects.
                    far = max(rv3d.view_distance, 1.0) * 50.0
                    end = None
                    while end is None and far > 1e-3:
                        end = view3d_utils.location_3d_to_region_2d(region, rv3d, start + u * (sign * far))
                        far *= 0.5
                    ends.append(end)
                if ends[0] is not None and ends[1] is not None:
                    lines(np.array([ends]), 1.0, axis_cols[handle][:3] + (0.55,))

        layout = gizmo_layout(region, rv3d, at, self._axes, self._size(context))
        if layout is not None:
            c, radius, arrows = layout
            active = self._drag[0] if self._drag is not None else self._hover
            for k, arr in enumerate(arrows):
                if arr is None:
                    continue
                a, b = arr
                col = axis_cols[k]
                if active == k:
                    col = tuple(min(1.0, x * 0.5 + 0.5) for x in col[:3]) + (1.0,)
                width = 3.0 if active == k else 2.0
                d = (b - a).normalized()
                n = Vector((-d.y, d.x))
                head = 11.0 * ui
                base_pt = b - d * head
                lines(np.array([[a, base_pt]]), width, col)
                tris([b, base_pt + n * head * 0.45, base_pt - n * head * 0.45], col)
            ring = [c + Vector((math.cos(i * math.tau / 32), math.sin(i * math.tau / 32))) * radius
                    for i in range(33)]
            center_col = COL_HOT if active == 'CENTER' else COL_CENTER
            lines(np.array([[ring[i], ring[i + 1]] for i in range(32)]), 2.5 if active == 'CENTER' else 1.6,
                  center_col)
            dots([c], 6.0, COL_PIVOT)
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
        self._drag = None
        self._press = None
        self._placed = False
        self._pivot_preview = Vector()
        self._rebuild(context)
        # Blender's own tool gizmo would sit on top of ours: hide it while editing the pivot.
        space = context.space_data
        self._space = space
        self._tool_gizmo = space.show_gizmo_tool
        space.show_gizmo_tool = False
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
        try:
            self._space.show_gizmo_tool = self._tool_gizmo
        except (AttributeError, ReferenceError):
            pass
        context.workspace.status_text_set(None)
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        if _running is self:
            _running = None
        self._result = {'FINISHED'} if self._placed else {'CANCELLED'}
        return self._result

    def modal(self, context, event):
        if getattr(self, "_result", None) is not None:
            return self._result  # already finished (e.g. driven from a script): just let Blender drop it
        if context.mode != 'OBJECT' or context.area is None:
            return self.finish(context)
        context.area.tag_redraw()
        typ, val = event.type, event.value
        mods = event.shift or event.ctrl or event.alt or event.oskey

        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            if self._press is not None and self._drag is None:
                handle, at = self._press
                if handle is not None and (Vector(self._mouse) - Vector(at)).length > CLICK_SLOP:
                    saved = self._mouse
                    self._mouse = at  # grab where the press happened, so the pivot doesn't jump
                    ok = self.begin_drag(context, handle)
                    self._mouse = saved
                    if not ok:
                        self._press = None
            if self._drag is not None:
                self.update_drag(context, ctrl=event.ctrl)
                return {'RUNNING_MODAL'}
            self._update_hover(context)
            return {'PASS_THROUGH'}

        if typ == 'LEFTMOUSE' and not event.alt:
            if val == 'PRESS':
                self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
                self._update_hover(context)
                self._press = (self._hover, self._mouse)
                return {'RUNNING_MODAL'}
            if val == 'RELEASE':
                press, self._press = self._press, None
                if self._drag is not None:
                    self.end_drag(context, apply=True)
                elif press is not None and press[0] is None and self._hot is not None:
                    self.move_pivot(context, self._hot)  # click on a highlighted point
                    self._status(context)
                return {'RUNNING_MODAL'}

        if typ in {'LEFT_CTRL', 'RIGHT_CTRL'} and self._drag is not None:
            self.update_drag(context, ctrl=(val == 'PRESS'))
            return {'RUNNING_MODAL'}

        if val == 'PRESS' and not event.is_repeat and not mods:
            if typ in _MODE_KEYS:
                self.snap = _MODE_KEYS[typ]
                self._rebuild(context)
                if self._drag is not None:
                    self.update_drag(context)
                self._status(context)
                return {'RUNNING_MODAL'}
            if typ in {'D', 'RET', 'NUMPAD_ENTER', 'ESC', 'RIGHTMOUSE'}:
                if self._drag is not None or self._press is not None:  # cancel the drag only
                    self._press = None
                    if self._drag is not None:
                        self.end_drag(context, apply=False)
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
        try:
            _running._space.show_gizmo_tool = _running._tool_gizmo
        except Exception:
            pass
        _running = None
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
