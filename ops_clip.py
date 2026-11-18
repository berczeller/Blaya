# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Clipping tool (Shift+C in Object Mode), modeled on the Hammer / s&box Clipping Tool.

Drag with the left mouse button to draw a clip line; its ends snap to vertices of the selected
objects or to the grid. The cut plane is that line extended along the view direction (orthographic
views) or through the camera (perspective views), so what you see is what gets cut.

Keys while active: drag LMB draw line / move an end, Shift+X cycle keep mode (side A, side B, both),
C toggle capping, Enter apply, Space apply and keep cutting, Esc / right-click cancel.
Navigation (Alt + mouse, wheel, numpad, F / Home) keeps working.
"""

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import ops_pivot as piv

KEEP_ITEMS = (
    ('A', "Keep Side A", "Keep the side marked A, delete the other", 'TRIA_LEFT', 0),
    ('B', "Keep Side B", "Keep the side marked B, delete the other", 'TRIA_RIGHT', 1),
    ('BOTH', "Keep Both", "Keep both sides as separate objects", 'MOD_BOOLEAN', 2),
)
_KEEP_LABEL = {'A': "Keep A", 'B': "Keep B", 'BOTH': "Keep Both (split)"}
_KEEP_CYCLE = {'A': 'B', 'B': 'BOTH', 'BOTH': 'A'}

COL_LINE = (1.0, 1.0, 1.0, 1.0)
COL_EXT = (1.0, 1.0, 1.0, 0.35)
COL_REMOVED = (0.95, 0.25, 0.2, 0.45)
COL_SPLIT_B = (0.25, 0.6, 1.0, 0.35)
COL_OUTLINE = (0.35, 0.75, 1.0, 0.9)
COL_HANDLE = (1.0, 1.0, 1.0, 1.0)
COL_HOT = piv.COL_HOT
COL_LABEL = (1.0, 1.0, 1.0, 0.9)
COL_READOUT_BG = (0.0, 0.0, 0.0, 0.6)

_NAV_TYPES = {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
              'MOUSEROTATE', 'MOUSESMARTZOOM', 'NDOF_MOTION', 'HOME', 'F'}


_running = None  # the active Clipping Tool, if any


def _prefs(context):
    return context.preferences.addons[__package__].preferences


# --------------------------------------------------------------------------- cut geometry

def cut_plane(region, rv3d, w0, w1):
    """Plane (point, unit normal) through the clip line, following the view.

    The normal is oriented so side A (left of the line as drawn on screen, start -> end) is positive.
    Returns None when the line is degenerate.
    """
    view_dir = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
    if rv3d.is_perspective:
        eye = rv3d.view_matrix.inverted().translation
        n = (w0 - eye).cross(w1 - eye)
    else:
        n = (w1 - w0).cross(view_dir)
    if n.length < 1e-9:
        return None
    n.normalize()
    a = view3d_utils.location_3d_to_region_2d(region, rv3d, w0)
    b = view3d_utils.location_3d_to_region_2d(region, rv3d, w1)
    if a is not None and b is not None and (b - a).length > 1e-3:
        d = (b - a).normalized()
        left = Vector((-d.y, d.x))
        probe = view3d_utils.region_2d_to_location_3d(region, rv3d, (a + b) * 0.5 + left * 40.0, w0)
        if (probe - w0).dot(n) < 0.0:
            n = -n
    return w0.copy(), n


def _signed_distances(obj, co, no):
    me = obj.data
    nv = len(me.vertices)
    if nv == 0:
        return np.zeros(0)
    buf = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", buf)
    mw = np.array([list(r) for r in obj.matrix_world], dtype=np.float64)
    world = buf.reshape(nv, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]
    return (world - np.array(co)) @ np.array(no)


def _clip_mesh(obj, co, no, keep_positive, cap):
    """Cut obj's mesh with the world plane, keeping the positive or negative side. Optionally cap."""
    me = obj.data
    inv = obj.matrix_world.inverted()
    co_l = inv @ co
    no_l = (obj.matrix_world.to_3x3().transposed() @ no).normalized()  # plane normal into object space
    bm = bmesh.new()
    bm.from_mesh(me)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=co_l, plane_no=no_l,
                                 clear_inner=keep_positive, clear_outer=not keep_positive)
    if cap:
        cut_edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge) and e.is_valid and e.is_boundary]
        if cut_edges:
            filled = bmesh.ops.holes_fill(bm, edges=cut_edges, sides=0)
            outward = -no_l if keep_positive else no_l  # caps face the removed side
            for f in filled["faces"]:
                f.normal_update()
                if f.normal.dot(outward) < 0.0:
                    f.normal_flip()
                # Match the material of a neighbouring face.
                for e in f.edges:
                    others = [lf for lf in e.link_faces if lf is not f]
                    if others:
                        f.material_index = others[0].material_index
                        f.smooth = others[0].smooth
                        break
    bm.to_mesh(me)
    bm.free()
    me.update()


PRE_SUFFIX = ".blaya_precut"


def _swap_in_copy(obj, record):
    """Give `obj` a copy of its mesh to cut, keeping the original intact for undo.

    The copy takes over the original's name (when only this object used it), so names don't drift.
    """
    orig = obj.data
    name = orig.name
    sole_user = orig.users == 1
    if sole_user:
        orig.name = name + PRE_SUFFIX
    new = orig.copy()
    if sole_user:
        new.name = name
    orig.use_fake_user = True  # keep it alive while it has no users
    obj.data = new
    record["swaps"].append((obj, orig, name if sole_user else None))


def undo_record(record):
    """Restore the geometry saved by clip_objects(record=...) and delete objects it created."""
    for obj in record["created"]:
        me = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    for obj, orig, name in reversed(record["swaps"]):
        cut = obj.data
        obj.data = orig
        orig.use_fake_user = False
        if cut is not None and cut.users == 0:
            bpy.data.meshes.remove(cut)
        if name is not None:
            orig.name = name


def discard_record(record):
    """Forget a record for good: free the saved original meshes nothing uses any more."""
    for _obj, orig, _name in record["swaps"]:
        if orig.name not in bpy.data.meshes:
            continue
        orig.use_fake_user = False
        if orig.users == 0:
            bpy.data.meshes.remove(orig)
        elif orig.name.endswith(PRE_SUFFIX):  # still used elsewhere: drop the temporary suffix
            orig.name = orig.name[: -len(PRE_SUFFIX)]


def clip_objects(context, objects, co, no, keep='A', cap=True, record=None):
    """Apply the cut to mesh `objects`. Returns (changed objects, new objects, skipped names).

    With `record` (dict with "swaps" and "created" lists), the pre-cut meshes are kept so the cut
    can be reverted with undo_record() or finalized with discard_record().
    """
    changed, created, skipped = [], [], []
    for obj in objects:
        if obj.type != 'MESH':
            continue
        d = _signed_distances(obj, co, no)
        if len(d) == 0:
            continue
        has_pos, has_neg = bool((d > 1e-6).any()), bool((d < -1e-6).any())
        if not (has_pos and has_neg):
            # Not crossed by the plane: keep it whole unless it lies entirely on the side being removed.
            only_removed = (keep == 'A' and not has_pos) or (keep == 'B' and not has_neg)
            skipped.append(obj.name + (" (entirely on the removed side, left untouched)" if only_removed else ""))
            continue
        if record is not None:
            _swap_in_copy(obj, record)  # also protects linked duplicates
        elif obj.data.users > 1:
            obj.data = obj.data.copy()  # don't cut linked duplicates behind the user's back
        if keep == 'BOTH':
            other = obj.copy()
            other.data = obj.data.copy()
            for coll in obj.users_collection:
                coll.objects.link(other)
            _clip_mesh(obj, co, no, keep_positive=True, cap=cap)
            _clip_mesh(other, co, no, keep_positive=False, cap=cap)
            other.select_set(True)
            created.append(other)
            if record is not None:
                record["created"].append(other)
        else:
            _clip_mesh(obj, co, no, keep_positive=(keep == 'A'), cap=cap)
        changed.append(obj)
    return changed, created, skipped


def format_length(context, value):
    """A length in the scene's units (e.g. '2.37 m', '237 cm'), or plain numbers without a unit system."""
    us = context.scene.unit_settings
    if us.system == 'NONE':
        return f"{value:.3f}"
    return bpy.utils.units.to_string(us.system, 'LENGTH', value * us.scale_length, precision=3,
                                     split_unit=us.use_separate)


def line_angle(rv3d, w0, w1):
    """Angle of the line as seen in the view, in degrees from the view's horizontal (0-180)."""
    import math
    v = w1 - w0
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))
    ang = math.degrees(math.atan2(v.dot(up), v.dot(right))) % 180.0
    return 0.0 if abs(ang - 180.0) < 1e-6 else ang


def line_readout(context, rv3d, w0, w1):
    return f"{format_length(context, (w1 - w0).length)}   {line_angle(rv3d, w0, w1):.1f}°"


# --------------------------------------------------------------------------- screen helpers

def _half_plane(rect, a, b, positive):
    """Clip a convex polygon (list of 2D points) to one side of the infinite line a-b."""
    ab = (b[0] - a[0], b[1] - a[1])

    def side(p):
        s = ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])
        return s if positive else -s

    out = []
    n = len(rect)
    for i in range(n):
        p, q = rect[i], rect[(i + 1) % n]
        sp, sq = side(p), side(q)
        if sp >= 0:
            out.append(p)
        if (sp >= 0) != (sq >= 0):
            t = sp / (sp - sq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _fan(poly):
    return [v for i in range(1, len(poly) - 1) for v in (poly[0], poly[i], poly[i + 1])]


def _hull(points):
    """Convex hull (monotone chain) of 2D points, counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


MAX_HULL_POINTS = 4000


def screen_hulls(region, rv3d, objects):
    """Screen-space convex outline of each mesh (sampled for big meshes)."""
    hulls = []
    for obj in objects:
        me = obj.data
        nv = len(me.vertices)
        if nv == 0:
            continue
        buf = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", buf)
        co = buf.reshape(nv, 3).astype(np.float64)
        if nv > MAX_HULL_POINTS:
            co = co[np.linspace(0, nv - 1, MAX_HULL_POINTS).astype(int)]
        mw = np.array([list(r) for r in obj.matrix_world], dtype=np.float64)
        world = co @ mw[:3, :3].T + mw[:3, 3]
        xy, w, _ok = piv.project(rv3d, region, world)
        front = w > 1e-6  # points in front of the camera, even if outside the region
        if not front.any():
            continue
        h = _hull([(round(x, 1), round(y, 1)) for x, y in xy[front]])
        if len(h) >= 3:
            hulls.append(h)
    return hulls


# --------------------------------------------------------------------------- operator

class BLAYA_OT_clip_tool(bpy.types.Operator):
    """Cut the selected meshes with a line drawn in the view, like Hammer's Clipping Tool.
    Drag to draw, Shift+X keep mode, C cap, Enter apply, Space apply and continue, Esc cancel"""
    bl_idname = "blaya.clip_tool"
    bl_label = "Clipping Tool"

    keep: EnumProperty(name="Keep", items=KEEP_ITEMS, default='A')
    cap: BoolProperty(name="Cap New Surfaces", default=True)

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.area is not None and context.area.type == 'VIEW_3D'
                and any(o.type == 'MESH' for o in context.selected_objects))

    # -- helpers

    def _objects(self, context):
        return [o for o in context.selected_objects if o.type == 'MESH']

    def _ref(self, context):
        objs = self._objects(context)
        if not objs:
            return Vector()
        return sum((o.matrix_world.translation for o in objs), Vector()) / len(objs)

    def _rebuild_snap(self, context):
        self._verts = piv.gather_candidates(self._objects(context), 'VERTEX')["points"]

    def _snap(self, context, mouse):
        """World point for a mouse position: nearest vertex in range, else the grid. Sets self._hot."""
        region, rv3d = self._region, self._region.data
        radius = _prefs(context).clip_snap_radius
        xy, _w, ok = piv.project(rv3d, region, self._verts)
        i = piv.nearest_point(xy, ok, np.array(mouse, dtype=np.float64), radius)
        if i is not None:
            self._hot = Vector(self._verts[i])
            return Vector(self._verts[i])
        self._hot = None
        pt, _step, _axis = piv.grid_snap(context, region, rv3d, Vector(mouse), self._ref(context))
        if pt is None:
            pt = view3d_utils.region_2d_to_location_3d(region, rv3d, Vector(mouse), self._ref(context))
        return pt

    def _status(self, context):
        cap = "On" if self.cap else "Off"
        context.workspace.status_text_set(
            f"Clip: {_KEEP_LABEL[self.keep]}  Cap {cap}   |   Drag LMB: draw line / move end   Shift+X: keep mode"
            f"   C: cap   Enter: apply   Space: apply & continue   Ctrl+Z: undo cut ({len(self._stack)})   Esc: exit")
        if context.area:
            context.area.header_text_set(f"Clipping Tool - {_KEEP_LABEL[self.keep]} - Cap {cap}")

    def _screen(self, w):
        return view3d_utils.location_3d_to_region_2d(self._region, self._region.data, w)

    # -- drawing

    def draw_px(self):
        context = bpy.context
        if context.region is None or context.region.as_pointer() != self._region_ptr:
            return
        region = context.region
        ui = context.preferences.system.ui_scale
        gpu.state.blend_set('ALPHA')
        flat = gpu.shader.from_builtin('UNIFORM_COLOR')
        pts = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')

        def tris(verts, color):
            if len(verts) >= 3:
                flat.uniform_float("color", color)
                batch_for_shader(flat, 'TRIS', {"pos": verts}).draw(flat)

        def lines(segs, width, color):
            if not segs:
                return
            sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
            sh.uniform_float("viewportSize", (region.width, region.height))
            sh.uniform_float("lineWidth", width * ui)
            sh.uniform_float("color", color)
            batch_for_shader(sh, 'LINES', {"pos": [p for s in segs for p in s]}).draw(sh)

        def dots(points, size, color):
            if points:
                gpu.state.point_size_set(size * ui)
                pts.uniform_float("color", color)
                batch_for_shader(pts, 'POINTS', {"pos": points}).draw(pts)

        a = self._screen(self._w0) if self._w0 is not None else None
        b = self._screen(self._w1) if self._w1 is not None else None
        hulls = screen_hulls(region, context.region_data, self._objects(context))
        has_line = a is not None and b is not None and (b - a).length > 1.0
        if has_line:
            # Like Hammer: tint only the part of each selected mesh that goes away (or the B half when splitting).
            a2, b2 = (a.x, a.y), (b.x, b.y)
            for h in hulls:
                if self.keep == 'A':
                    tris(_fan(_half_plane(h, a2, b2, positive=False)), COL_REMOVED)
                elif self.keep == 'B':
                    tris(_fan(_half_plane(h, a2, b2, positive=True)), COL_REMOVED)
                else:
                    tris(_fan(_half_plane(h, a2, b2, positive=False)), COL_SPLIT_B)
        # Outline of the selection (the original shape stays visible as a blue outline).
        lines([(h[i], h[(i + 1) % len(h)]) for h in hulls for i in range(len(h))], 1.5, COL_OUTLINE)
        if has_line:
            d = (b - a).normalized()
            far = max(region.width, region.height) * 2.0
            lines([((a - d * far).to_tuple(), (b + d * far).to_tuple())], 1.0, COL_EXT)
            lines([(a.to_tuple(), b.to_tuple())], 2.5, COL_LINE)
            # A / B side markers next to the middle of the line.
            mid = (a + b) * 0.5
            left = Vector((-d.y, d.x)) * 22.0 * ui
            self._draw_label(context, "A", mid + left)
            self._draw_label(context, "B", mid - left)
            # Length / angle readout next to the end being moved (or the middle of the line).
            anchor = b if self._drag == 1 else a if self._drag == 0 else mid
            self._draw_readout(context, flat, line_readout(context, context.region_data, self._w0, self._w1),
                               anchor + Vector((18.0, 18.0)) * ui)
        if _prefs(context).clip_show_hints:
            self._draw_hints(context, flat)
        handles = [p.to_tuple() for p in (a, b) if p is not None]
        dots(handles, 9.0, COL_HANDLE)
        if self._hot is not None:
            h = self._screen(self._hot)
            if h is not None:
                dots([h.to_tuple()], 14.0, COL_HOT)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')

    def hint_lines(self):
        """(key, action) rows for the bottom-left cheat sheet, with the live state of the toggles."""
        keep = {'A': "keep A", 'B': "keep B", 'BOTH': "keep both"}[self.keep]
        return [
            ("Drag LMB", "draw the cut line / move an end"),
            ("Shift+X", f"keep A / B / both  ({keep})"),
            ("C", f"cap new faces  ({'on' if self.cap else 'off'})"),
            ("Enter", "apply and exit"),
            ("Space", "apply and keep cutting"),
            ("Ctrl+Z", f"undo last cut  ({len(self._stack)})"),
            ("Esc / RMB", "exit"),
            ("Alt + mouse", "navigate"),
        ]

    def _draw_hints(self, context, flat):
        """Subtle key cheat sheet in the bottom-left corner of the viewport."""
        import blf
        ui = context.preferences.system.ui_scale
        region = context.region
        left = 12 * ui
        area = context.area
        if area is not None and context.preferences.system.use_region_overlap:
            left += sum(r.width for r in area.regions if r.type == 'TOOLS' and r.width > 1)
        font = 0
        blf.size(font, 11 * ui)
        rows = self.hint_lines()
        line_h = blf.dimensions(font, "Xg")[1] + 5 * ui
        key_w = max(blf.dimensions(font, k)[0] for k, _ in rows) + 10 * ui
        y = 14 * ui
        blf.enable(font, blf.SHADOW)  # soft shadow keeps the text readable on light geometry
        blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.6)
        blf.shadow_offset(font, 1, -1)
        for key, action in reversed(rows):
            blf.position(font, left, y, 0)
            blf.color(font, 1.0, 1.0, 1.0, 0.75)
            blf.draw(font, key)
            blf.position(font, left + key_w, y, 0)
            blf.color(font, 1.0, 1.0, 1.0, 0.45)
            blf.draw(font, action)
            y += line_h
        blf.position(font, left, y + 2 * ui, 0)
        blf.color(font, 1.0, 1.0, 1.0, 0.75)
        blf.draw(font, "Clipping Tool")
        blf.disable(font, blf.SHADOW)

    def _draw_readout(self, context, flat, text, pos):
        import blf
        ui = context.preferences.system.ui_scale
        blf.size(0, 12 * ui)
        w, h = blf.dimensions(0, text)
        pad = 5 * ui
        x0, y0, x1, y1 = pos.x - pad, pos.y - pad, pos.x + w + pad, pos.y + h + pad
        flat.uniform_float("color", COL_READOUT_BG)
        batch_for_shader(flat, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]}).draw(flat)
        blf.position(0, pos.x, pos.y, 0)
        blf.color(0, *COL_LABEL)
        blf.draw(0, text)

    def _draw_label(self, context, text, pos):
        import blf
        ui = context.preferences.system.ui_scale
        blf.size(0, 14 * ui)
        w, h = blf.dimensions(0, text)
        blf.position(0, pos.x - w / 2, pos.y - h / 2, 0)
        blf.color(0, *COL_LABEL)
        blf.draw(0, text)

    # -- lifecycle

    def invoke(self, context, event):
        global _running
        if _running is not None:
            return {'CANCELLED'}
        # Housekeeping: saved pre-cut meshes nothing uses (e.g. left by an interrupted session).
        for me in [m for m in bpy.data.meshes if m.name.endswith(PRE_SUFFIX) and m.users <= int(m.use_fake_user)]:
            bpy.data.meshes.remove(me)
        prefs = _prefs(context)
        self.keep = prefs.clip_keep_default
        self.cap = prefs.clip_cap_default
        self._region = context.region
        self._region_ptr = context.region.as_pointer()
        self._w0 = self._w1 = None
        self._drag = None  # 0 or 1: which end is being dragged
        self._hot = None
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._applied = 0
        self._stack = []  # one record per applied cut, for Ctrl+Z inside the tool
        self._rebuild_snap(context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        _running = self
        self._status(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        return {'CANCELLED'}  # interactive only

    def undo_last(self, context):
        if not self._stack:
            self.report({'INFO'}, "Nothing to undo in this Clipping Tool session")
            return
        undo_record(self._stack.pop())
        self._applied -= 1
        self._rebuild_snap(context)
        self.report({'INFO'}, f"Cut undone ({len(self._stack)} left in this session)")

    def finish(self, context):
        global _running
        if _running is self:
            _running = None
        # Keep the cuts: free the saved pre-cut meshes, and make the whole session one Ctrl+Z step.
        for record in self._stack:
            discard_record(record)
        if self._stack:
            self._stack.clear()
            bpy.ops.ed.undo_push(message="Blaya Clip")
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        return {'FINISHED'} if self._applied else {'CANCELLED'}

    def apply(self, context):
        if self._w0 is None or self._w1 is None:
            self.report({'WARNING'}, "Draw a clip line first")
            return False
        plane = cut_plane(self._region, self._region.data, self._w0, self._w1)
        if plane is None:
            self.report({'WARNING'}, "The clip line is too short or points straight at the view")
            return False
        record = {"swaps": [], "created": []}
        changed, created, skipped = clip_objects(context, self._objects(context), *plane,
                                                 keep=self.keep, cap=self.cap, record=record)
        if not changed:
            self.report({'WARNING'}, "The line does not cross any selected mesh")
            return False
        self._stack.append(record)
        self._applied += 1
        msg = f"Clipped {len(changed)} object(s)" + (f", {len(created)} new" if created else "")
        if skipped:
            msg += f"; untouched: {', '.join(skipped)}"
        self.report({'INFO'}, msg)
        self._w0 = self._w1 = None
        self._rebuild_snap(context)
        return True

    def modal(self, context, event):
        if context.mode != 'OBJECT' or context.area is None:
            return self.finish(context)
        context.area.tag_redraw()
        typ, val = event.type, event.value

        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            w = self._snap(context, self._mouse)
            if self._drag == 0:
                self._w0 = w
            elif self._drag == 1:
                self._w1 = w
            return {'RUNNING_MODAL'}

        if (event.alt or typ in _NAV_TYPES or typ.startswith("NDOF_")
                or (typ.startswith("NUMPAD_") and typ != 'NUMPAD_ENTER')):
            return {'PASS_THROUGH'}  # navigation

        if typ == 'LEFTMOUSE':
            if val == 'PRESS':
                grab_px = 12.0 * context.preferences.system.ui_scale
                mouse = Vector(self._mouse)
                for i, w in enumerate((self._w0, self._w1)):
                    p = self._screen(w) if w is not None else None
                    if p is not None and (p - mouse).length <= grab_px:
                        self._drag = i
                        return {'RUNNING_MODAL'}
                self._w0 = self._snap(context, self._mouse)
                self._w1 = self._w0.copy()
                self._drag = 1
            elif val == 'RELEASE':
                self._drag = None
                if self._w0 is not None and self._w1 is not None and (self._w1 - self._w0).length < 1e-9:
                    self._w0 = self._w1 = None  # a click without dragging clears the line
            return {'RUNNING_MODAL'}

        if typ == 'Z' and val == 'PRESS' and (event.ctrl or event.oskey) and not event.shift:
            self.undo_last(context)  # repeats allowed: hold Ctrl+Z to step back through cuts
            self._status(context)
            return {'RUNNING_MODAL'}

        if val == 'PRESS' and not event.is_repeat:
            if typ == 'X' and event.shift:
                self.keep = _KEEP_CYCLE[self.keep]
                self._status(context)
            elif typ == 'C' and not (event.shift or event.ctrl):
                self.cap = not self.cap
                self._status(context)
            elif typ in {'RET', 'NUMPAD_ENTER'}:
                if self.apply(context):
                    return self.finish(context)
            elif typ == 'SPACE':
                self.apply(context)
                self._status(context)
            elif typ in {'ESC', 'RIGHTMOUSE'}:
                if self._drag is not None:
                    self._drag = None
                    self._w0 = self._w1 = None
                    return {'RUNNING_MODAL'}
                return self.finish(context)
        return {'RUNNING_MODAL'}


_classes = (BLAYA_OT_clip_tool,)


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
        for record in getattr(_running, "_stack", []):
            discard_record(record)  # keep the cuts, free the saved originals
        _running = None
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
