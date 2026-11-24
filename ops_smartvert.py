# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smart Vert: context-aware vertex merging, path merging / connecting and Slide Extend (Edit Mode).

4            merge at the last selected vertex (or the one nearest the mouse); one vertex: vertex bevel
Shift+4      merge at the center
Alt+4        merge two vertex paths (select 4 vertices: path 1 = 1st to 2nd, path 2 = 4th to 3rd)
Ctrl+Alt+4   connect two vertex paths
Shift+Alt+4  Slide Extend: slide the selected vertices along their edges / towards the last one,
             Ctrl snaps to edges and faces, Alt projects on the snapped edge, F flattens the end face

In Face and Edge select modes, merging works per face island / per edge chain.
"""

import heapq
import math

import blf
import bmesh
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, geometry
from mathutils.bvhtree import BVHTree

VERT_ONLY = (True, False, False)
EDGE_ONLY = (False, True, False)
FACE_ONLY = (False, False, True)

COL_SLIDE = (0.3, 1.0, 0.3, 0.5)
COL_SNAP = (1.0, 0.25, 0.2, 1.0)
COL_SNAP_FAINT = (1.0, 0.25, 0.2, 0.25)
COL_ORTHO = (1.0, 0.6, 0.1, 0.6)
COL_FACE = (1.0, 0.25, 0.2, 0.1)


# --------------------------------------------------------------------------- selection helpers

def select_mode(context):
    return tuple(context.tool_settings.mesh_select_mode)


def components(items, neighbours):
    """Connected groups of `items` (sets), largest first. `neighbours(item)` yields connected items."""
    todo, groups = set(items), []
    while todo:
        seed = todo.pop()
        group, stack = {seed}, [seed]
        while stack:
            for n in neighbours(stack.pop()):
                if n in todo:
                    todo.discard(n)
                    group.add(n)
                    stack.append(n)
        groups.append(group)
    return sorted(groups, key=len, reverse=True)


def face_islands(faces):
    faces = set(faces)
    return components(faces, lambda f: (o for e in f.edges for o in e.link_faces if o in faces))


def edge_chains(edges):
    edges = set(edges)
    return components(edges, lambda e: (o for v in e.verts for o in v.link_edges if o in edges))


def nearest_to_mouse(verts, mw, region, rv3d, mouse):
    """The vertex closest to the mouse ray, measured in object space at each vertex's own depth."""
    if region is None or rv3d is None or mouse is None:
        return None
    inv = mw.inverted_safe()
    best, best_d = None, math.inf
    for v in verts:
        world = mw @ v.co
        p = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, world)
        d = (inv @ p - v.co).length
        if d < best_d:
            best, best_d = v, d
    return best


def shortest_path(bm, start, end, by_length):
    """Vertex path from `start` to `end` over the mesh edges (Dijkstra), or [] if none."""
    dist, prev = {start: 0.0}, {}
    heap, count = [(0.0, 0, start)], 1
    while heap:
        d, _n, v = heapq.heappop(heap)
        if v is end:
            break
        if d > dist.get(v, math.inf):
            continue
        for e in v.link_edges:
            o = e.other_vert(v)
            nd = d + (e.calc_length() if by_length else 1.0)
            if nd < dist.get(o, math.inf):
                dist[o], prev[o] = nd, v
                heapq.heappush(heap, (nd, count, o))
                count += 1
    if end not in dist:
        return []
    path, v = [end], end
    while v is not start:
        v = prev[v]
        path.append(v)
    return list(reversed(path))


# --------------------------------------------------------------------------- operator

class BLAYA_OT_smart_vert(bpy.types.Operator):
    bl_idname = "blaya.smart_vert"
    bl_label = "Smart Vert"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Mode", items=(('MERGE', "Merge", ""), ('CONNECT', "Connect Paths", "")),
                       default='MERGE')
    mergetype: EnumProperty(name="Merge", items=(('LAST', "Last", ""), ('CENTER', "Center", ""),
                                                ('PATHS', "Paths", "")), default='LAST')
    merge_center_paths: BoolProperty(name="in Center", description="Merge the paths halfway between them",
                                     default=False)
    pathtype: EnumProperty(name="Shortest Path", items=(('TOPO', "Topo", "Fewest edges"),
                                                       ('LENGTH', "Length", "Shortest distance")), default='TOPO')
    merge_uvs: BoolProperty(name="Merge UVs", default=True)
    slideoverride: BoolProperty(name="Slide Extend", default=False, options={'SKIP_SAVE'})
    # The mouse position is stored, so a mouse merge can be redone from the redo panel.
    mouse_x: IntProperty(options={'HIDDEN', 'SKIP_SAVE'}, default=-1)
    mouse_y: IntProperty(options={'HIDDEN', 'SKIP_SAVE'}, default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (context.mode == 'EDIT_MESH' and obj is not None and obj.type == 'MESH'
                and obj.data.total_vert_sel > 0)

    @classmethod
    def description(cls, context, properties):
        if properties.slideoverride:
            return "Slide Extend: slide the selected vertices towards their target. Ctrl snaps, F flattens"
        if properties.mode == 'CONNECT':
            return "Connect Paths: select 4 vertices, connects the path 1st-2nd with the path 4th-3rd"
        return {'LAST': "Vertex Bevel (1 vertex) / Merge at Last / Merge at Mouse",
                'CENTER': "Merge at Center",
                'PATHS': "Merge Paths: select 4 vertices, merges the path 1st-2nd onto the path 4th-3rd"}[
            properties.mergetype]

    def draw(self, context):
        layout = self.layout
        if self.slideoverride:
            layout.label(text="Mode: Slide Extend")
            return
        layout.row().prop(self, "mode", expand=True)
        if self.mode == 'MERGE':
            row = layout.row(align=True)
            row.prop(self, "mergetype", expand=True)
            if self.mergetype == 'PATHS':
                row.prop(self, "merge_center_paths", toggle=True)
            elif getattr(self, "_can_merge_uvs", False):
                layout.prop(self, "merge_uvs")
        if self.mode == 'CONNECT' or self.mergetype == 'PATHS':
            layout.row().prop(self, "pathtype", expand=True)

    # -- invoke / execute

    def invoke(self, context, event):
        if self.slideoverride:
            return SlideExtend.start(self, context, event)
        self.mouse_x, self.mouse_y = event.mouse_region_x, event.mouse_region_y
        self._invoked = True
        if (self.mode == 'MERGE' and self.mergetype in {'LAST', 'CENTER'}) or select_mode(context) == VERT_ONLY:
            return self.execute(context)
        return {'CANCELLED'}  # paths / connect need vertex select mode

    def modal(self, context, event):
        return self._slide.modal(self, context, event)

    def execute(self, context):
        if self.slideoverride:
            return {'CANCELLED'}
        done = self.work(context)
        self._invoked = False
        return {'FINISHED'} if done else {'CANCELLED'}

    def _mouse(self, context):
        if self.mouse_x < 0 or context.region is None or context.region.type != 'WINDOW':
            return None, None, None
        return context.region, context.region_data, Vector((self.mouse_x, self.mouse_y))

    def work(self, context):
        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        sel = [v for v in bm.verts if v.select]
        mode = select_mode(context)
        self._can_merge_uvs = False

        if len(sel) == 1 and mode == VERT_ONLY:
            if getattr(self, "_invoked", False):
                bpy.ops.mesh.bevel('INVOKE_DEFAULT', affect='VERTICES')
            return True
        if self.mode == 'MERGE' and self.mergetype in {'LAST', 'CENTER'}:
            return self.merge_last_center(context, obj, bm, sel, mode)
        if mode != VERT_ONLY:
            return False
        return self.paths(context, obj, bm, sel)

    def merge_last_center(self, context, obj, bm, sel, mode):
        me, mw = obj.data, obj.matrix_world
        region, rv3d, mouse = self._mouse(context)
        last = self.mergetype == 'LAST'

        def merge_groups(groups):
            used = set()
            for verts in groups:
                verts = [v for v in verts if v not in used and v.is_valid]
                if len(verts) < 2:
                    continue
                if last:
                    target = nearest_to_mouse(verts, mw, region, rv3d, mouse) or verts[-1]
                    co = target.co.copy()
                else:
                    co = sum((v.co for v in verts), Vector()) / len(verts)
                used.update(verts)
                bmesh.ops.pointmerge(bm, verts=verts, merge_co=co)
            bmesh.update_edit_mesh(me)

        if mode == FACE_ONLY:
            faces = [f for f in bm.faces if f.select]
            merge_groups([[v for f in isl for v in f.verts] for isl in face_islands(faces)])
            return True
        if mode == EDGE_ONLY and any(e.select for e in bm.edges):
            chains = edge_chains([e for e in bm.edges if e.select])
            merge_groups([list({v for e in ch for v in e.verts}) for ch in chains])
            return True
        if len(sel) < 2:
            return True
        if last and not bm.select_history:
            merge_groups([sel])  # box / circle select: merge at the vertex nearest the mouse
            return True
        self._can_merge_uvs = True
        bpy.ops.mesh.merge(type='LAST' if last else 'CENTER', uvs=self.merge_uvs)
        return True

    def get_paths(self, bm, sel):
        hist = [h for h in bm.select_history if isinstance(h, bmesh.types.BMVert)]
        if len(sel) != 4 or len(hist) != 4 or set(hist) != set(sel):
            return None
        by_length = self.pathtype == 'LENGTH'
        p1 = shortest_path(bm, hist[0], hist[1], by_length)
        p2 = shortest_path(bm, hist[3], hist[2], by_length)
        if set(p1) & set(p2):
            # The paths touch: try the other kind of shortest path.
            by_length = not by_length
            p1 = shortest_path(bm, hist[0], hist[1], by_length)
            p2 = shortest_path(bm, hist[3], hist[2], by_length)
            self.pathtype = 'LENGTH' if by_length else 'TOPO'
        if not p1 or not p2:
            return None
        for v in p1 + p2:
            v.select = True
        return p1, p2

    def paths(self, context, obj, bm, sel):
        res = self.get_paths(bm, sel)
        if res is None:
            return False
        p1, p2 = res
        pairs = list(zip(p1, p2))
        if self.mode == 'CONNECT':
            for a, b in pairs:
                if a is not b and not any(e.other_vert(a) is b for e in a.link_edges):
                    try:
                        bmesh.ops.connect_vert_pair(bm, verts=[a, b])
                    except (ValueError, RuntimeError):
                        pass  # only works when the two share a face
        else:
            targetmap = {}
            for a, b in pairs:
                if a is b:
                    continue
                if self.merge_center_paths:
                    b.co = (a.co + b.co) / 2
                targetmap[a] = b
            bmesh.ops.weld_verts(bm, targetmap=targetmap)
        bm.select_flush(True)
        bmesh.update_edit_mesh(obj.data)
        return True


# --------------------------------------------------------------------------- Slide Extend (modal)

class SlideExtend:
    """State and event handling of Slide Extend, run as the Smart Vert operator's modal."""

    current = None  # the running slide (kept so tests and tools can reach it)
    result = None

    @staticmethod
    def popup(context, title, text):
        context.window_manager.popup_menu(lambda m, _c: m.layout.label(text=text), title=title, icon='ERROR')

    @classmethod
    def start(cls, op, context, event):
        mode = select_mode(context)
        if mode == FACE_ONLY:
            return {'CANCELLED'}
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        mw = obj.matrix_world
        region, rv3d = context.region, context.region_data
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        slides = {}  # vert -> target vert
        if mode[0]:  # vertex select mode (also when mixed with edge mode)
            sel = [v for v in bm.verts if v.select]
            hist = [h for h in bm.select_history if isinstance(h, bmesh.types.BMVert)]
            if len(sel) < 2:
                cls.popup(context, "Slide Extend", "Select more than 1 vertex.")
                return {'CANCELLED'}
            if not hist:
                cls.popup(context, "Slide Extend", "Select the last vertex without Box or Circle Select.")
                return {'CANCELLED'}
            if len(sel) > 3 and len(sel) % 2 == 0 and set(hist) == set(sel):
                for a, b in zip(hist[0::2], hist[1::2]):
                    slides[a] = b
            else:
                last = hist[-1]
                for v in sel:
                    if v is not last:
                        slides[v] = last
        else:  # edge select mode: the end of each edge nearest the mouse slides towards the other end
            for e in (e for e in bm.edges if e.select):
                a, b = e.verts
                center = mw @ ((a.co + b.co) / 2)
                p = mw.inverted_safe() @ view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, center)
                near, far = (a, b) if (a.co - p).length <= (b.co - p).length else (b, a)
                if near not in slides:
                    slides[near] = far
        if not slides:
            return {'CANCELLED'}

        st = op._slide = cls()
        st.obj, st.bm, st.mw = obj, bm, mw.copy()
        st.inv = mw.inverted_safe()
        st.slides = slides
        st.init = {v: v.co.copy() for v in slides}
        st.dirs = {v: (t.co - v.co).normalized() if (t.co - v.co).length > 1e-12 else Vector()
                   for v, t in slides.items()}
        origin = sum((mw @ v.co for v in slides), Vector()) / len(slides)
        target = sum((mw @ t.co for t in slides.values()), Vector()) / len(slides)
        if (target - origin).length < 1e-9:
            cls.popup(context, "Ambiguous Direction", "Try to position the view and mouse in a way, that "
                      "clearly indicates the direction you want to slide towards")
            return {'CANCELLED'}
        st.origin, st.target = origin, target
        st.flatten_setup(bm, slides)
        st.flatten = False
        st.snap = None          # ('EDGE', world a, world b) / ('FACE', world co, world normal, tris)
        st.snap_label = ""
        st.warning = ""
        st.tree = None
        st.distance = st.base_distance = 0.0
        st.init_point = st.line_point(region, rv3d, mouse)
        st.rebase = False
        st.ctrl = st.alt = False
        st.region_ptr = region.as_pointer()
        st.mouse = mouse
        st.handles = (bpy.types.SpaceView3D.draw_handler_add(st.draw_view, (), 'WINDOW', 'POST_VIEW'),
                      bpy.types.SpaceView3D.draw_handler_add(st.draw_hud, (), 'WINDOW', 'POST_PIXEL'))
        context.window_manager.modal_handler_add(op)
        SlideExtend.current = st
        st.status(context)
        return {'RUNNING_MODAL'}

    # -- geometry

    def line_point(self, region, rv3d, mouse):
        """Point on the origin-to-target line closest to the mouse ray (world)."""
        o = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
        d = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
        res = geometry.intersect_line_line(self.origin, self.target, o, o + d)
        return res[0] if res else self.origin.copy()

    def flatten_setup(self, bm, slides):
        """Flatten is possible with one sliding vertex on one selected edge whose other two edges share
        exactly one face with more than 3 vertices: that end face can be made planar."""
        self.can_flatten, self.flat_moves = False, []
        sel_edges = [e for e in bm.edges if e.select]
        if len(slides) != 1 or len(sel_edges) != 1:
            return
        v = next(iter(slides))
        others = [e for e in v.link_edges if e is not sel_edges[0]]
        if len(others) != 2:
            return
        shared = set(others[0].link_faces) & set(others[1].link_faces)
        if len(shared) != 1:
            return
        face = shared.pop()
        if len(face.verts) <= 3:
            return
        plane_verts = [v, others[0].other_vert(v), others[1].other_vert(v)]
        for fv in face.verts:
            if fv in plane_verts:
                continue
            edge = next((e for e in fv.link_edges if e not in face.edges), None)
            if edge is None:
                return
            self.flat_moves.append((fv, fv.co.copy(), edge.other_vert(fv).co.copy()))
        self.plane_verts = plane_verts
        self.can_flatten = True

    def apply_flatten(self):
        a, b, c = (v.co for v in self.plane_verts)
        normal = (b - a).cross(c - a)
        for fv, co, other in self.flat_moves:
            hit = geometry.intersect_line_plane(co, other, a, normal) if normal.length > 1e-12 else None
            fv.co = hit if hit is not None else co

    def raycast(self, context, region, rv3d, mouse):
        """(world hit, world normal, hit object, face info) of the surface under the mouse, the edited mesh
        included. Face info: list of world vertex positions of the hit face."""
        o = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
        d = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
        best = None
        # The edited mesh itself, from its edit-mode data (moving vertices excluded from the hit test).
        inv = self.inv
        lo, ld = inv @ o, (inv.to_3x3() @ d).normalized()
        if self.tree is None:  # built once; faces of the sliding vertices are ignored below anyway
            self.tree = BVHTree.FromBMesh(self.bm)
        loc, nor, index, _dist = self.tree.ray_cast(lo, ld)
        if loc is not None:
            self.bm.faces.ensure_lookup_table()
            face = self.bm.faces[index]
            if not any(v in self.slides for v in face.verts):
                w = self.mw @ loc
                best = ((w - o).length, w, face.verts, True)
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, nor, index, ob, _m = context.scene.ray_cast(depsgraph, o, d)
        if hit and ob is not None and ob.original is not self.obj and ob.display_type not in {'WIRE', 'BOUNDS'}:
            dist = (loc - o).length
            if best is None or dist < best[0]:
                me = ob.data
                poly = me.polygons[index]
                verts = [ob.matrix_world @ me.vertices[i].co for i in poly.vertices]
                best = (dist, loc, verts, False)
        if best is None:
            return None
        _dist, loc, verts, own = best
        coords = [self.mw @ v.co for v in verts] if own else verts
        return loc, coords

    def pick_snap(self, hit, coords):
        """Face or one of its edges, whichever is closer to the hit point."""
        center = sum(coords, Vector()) / len(coords)
        best = ('FACE', (center - hit).length / 25.0)
        best_edge = None
        for i in range(len(coords)):
            a, b = coords[i], coords[(i + 1) % len(coords)]
            length = (b - a).length
            if length < 1e-12:
                continue
            on_line, _t = geometry.intersect_point_line(hit, a, b)
            score = (hit - on_line).length * (hit - (a + b) / 2).length / length
            if score < best[1]:
                best, best_edge = ('EDGE', score), (a, b)
        if best[0] == 'EDGE':
            return ('EDGE', best_edge[0], best_edge[1])
        normal = geometry.normal(coords) if len(coords) >= 3 else Vector((0, 0, 1))
        return ('FACE', center, normal, coords)

    # -- update

    def update(self, context, event):
        region, rv3d = context.region, context.region_data
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse = mouse
        self.ctrl, self.alt = event.ctrl, event.alt
        point = self.line_point(region, rv3d, mouse)
        if self.rebase:
            self.base_distance, self.init_point, self.rebase = self.distance, point, False
        move = self.inv.to_3x3() @ (point - self.init_point)
        sign = 1.0 if (self.target - self.origin).dot(point - self.init_point) >= 0 else -1.0
        self.distance = self.base_distance + sign * move.length
        for v, co in self.init.items():
            v.co = co + self.dirs[v] * self.distance
        self.snap, self.snap_label, self.warning = None, "None", ""
        if event.ctrl:
            res = self.raycast(context, region, rv3d, mouse)
            if res is not None:
                self.snap = self.pick_snap(*res)
                self.snap_label = self.snap[0]
                self.apply_snap()
        if self.flatten and self.can_flatten:
            self.apply_flatten()
        elif self.can_flatten:
            for fv, co, _o in self.flat_moves:
                fv.co = co
        bmesh.update_edit_mesh(self.obj.data)

    def apply_snap(self):
        inv, mw = self.inv, self.mw
        if self.snap[0] == 'EDGE':
            _k, a, b = self.snap
            edge_dir = (b - a).normalized()
            for v, co in self.init.items():
                wco = mw @ co
                wdir = (mw.to_3x3() @ self.dirs[v]).normalized()
                if abs(wdir.dot(edge_dir)) > 0.999:
                    v.co = co
                    self.warning = "Skipping Parallel Edge!"
                    continue
                res = geometry.intersect_line_line(wco, wco + wdir, a, b)
                if res:
                    v.co = inv @ (res[1] if self.alt else res[0])
        else:
            _k, center, normal, _coords = self.snap
            any_hit = False
            for v, co in self.init.items():
                wco = mw @ co
                wdir = mw.to_3x3() @ self.dirs[v]
                hit = geometry.intersect_line_plane(wco, wco + wdir, center, normal)
                if hit is not None:
                    v.co = inv @ hit
                    any_hit = True
            if not any_hit:
                self.warning = "Skipping Face!"

    def restore(self):
        for v, co in self.init.items():
            v.co = co
        if self.can_flatten:
            for fv, co, _o in self.flat_moves:
                fv.co = co

    def finish(self, context, op, confirm):
        for h in self.handles:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
        context.workspace.status_text_set(None)
        if confirm:
            if self.snap is not None:
                moved = [(v.co - co).length for v, co in self.init.items()]
                avg = sum(moved) / len(moved) if moved else 0.0
                if avg > 0:
                    bmesh.ops.dissolve_degenerate(self.bm, edges=self.bm.edges[:], dist=avg / 100)
        else:
            self.restore()
        bmesh.update_edit_mesh(self.obj.data)
        context.area.tag_redraw()
        self.result = {'FINISHED'} if confirm else {'CANCELLED'}
        if SlideExtend.current is self:
            SlideExtend.current = None
        return self.result

    def status(self, context):
        text = "Smart Vert | Slide Extend"
        if self.ctrl and self.snap is not None:
            text += f" | Snap to {self.snap[0].title()}"
        text += "   |   LMB / Space: confirm   RMB / Esc: cancel   Ctrl: snap"
        if self.ctrl and self.snap is not None and self.snap[0] == 'EDGE':
            text += "   Alt: project on edge"
        if self.can_flatten:
            text += "   F: flatten"
        context.workspace.status_text_set(text)

    def modal(self, op, context, event):
        if self.result is not None:
            return self.result  # already finished (e.g. driven from a script): just let Blender drop it
        context.area.tag_redraw()
        typ, val = event.type, event.value
        if typ in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or (event.alt and typ in {'LEFTMOUSE', 'RIGHTMOUSE'}):
            self.rebase = True  # navigate, then continue the slide from where it was
            return {'PASS_THROUGH'}
        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT'}:
            self.update(context, event)
            self.status(context)
            return {'RUNNING_MODAL'}
        if typ == 'F' and val == 'PRESS' and self.can_flatten:
            self.flatten = not self.flatten
            self.update(context, event)
            self.status(context)
            return {'RUNNING_MODAL'}
        if typ in {'LEFTMOUSE', 'SPACE'} and val == 'PRESS':
            return self.finish(context, op, True)
        if typ in {'RIGHTMOUSE', 'ESC'} and val == 'PRESS':
            return self.finish(context, op, False)
        return {'RUNNING_MODAL'}

    # -- drawing

    def draw_view(self):
        if bpy.context.region is None or bpy.context.region.as_pointer() != self.region_ptr:
            return
        mw = self.mw
        sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        region = bpy.context.region
        gpu.state.blend_set('ALPHA')

        def lines(pts, width, color):
            if pts:
                sh.uniform_float("viewportSize", (region.width, region.height))
                sh.uniform_float("lineWidth", width)
                sh.uniform_float("color", color)
                batch_for_shader(sh, 'LINES', {"pos": pts}).draw(sh)

        lines([p for v, t in self.slides.items() for p in (mw @ v.co, mw @ t.co)], 2.0, COL_SLIDE)
        if self.snap is not None and self.snap[0] == 'EDGE':
            _k, a, b = self.snap
            lines([a, b], 3.0, COL_SNAP)
            ortho = []
            for v in self.init:
                p = mw @ v.co
                on_line, _t = geometry.intersect_point_line(p, a, b)
                ortho += [p, on_line]
            lines(ortho, 1.0, COL_ORTHO)
            lines([a, a + (b - a) * 3.0, b, b + (a - b) * 3.0], 1.0, COL_SNAP_FAINT)
        elif self.snap is not None:
            coords = self.snap[3]
            tris = [p for i in range(1, len(coords) - 1) for p in (coords[0], coords[i], coords[i + 1])]
            fsh = gpu.shader.from_builtin('UNIFORM_COLOR')
            fsh.uniform_float("color", COL_FACE)
            batch_for_shader(fsh, 'TRIS', {"pos": tris}).draw(fsh)
        gpu.state.blend_set('NONE')

    def draw_hud(self):
        context = bpy.context
        if context.region is None or context.region.as_pointer() != self.region_ptr:
            return
        ui = context.preferences.system.ui_scale
        font = 0
        x, y = self.mouse.x + 20 * ui, self.mouse.y + 20 * ui
        blf.size(font, 12 * ui)

        def text(s, color, dx=0.0, dy=0.0):
            blf.position(font, x + dx, y + dy, 0)
            blf.color(font, *color)
            blf.draw(font, s)
            return dx + blf.dimensions(font, s)[0]

        dx = text("Smart Vert ", (1, 1, 1, 0.9))
        text("Slide Extend", (0.3, 1.0, 0.3, 1.0), dx)
        line = -16 * ui
        if self.ctrl:
            valid = self.snap is not None
            text(f"Snapping: {self.snap_label}", COL_SNAP if valid else (1, 1, 1, 0.6), 0, line)
            line -= 16 * ui
        if self.ctrl and self.alt and self.snap is not None and self.snap[0] == 'EDGE':
            text("Edge Project", (1.0, 0.85, 0.1, 1.0), 0, line)
            line -= 16 * ui
        if self.flatten:
            text("Flatten", (0.35, 0.75, 1.0, 1.0), 0, line)
            line -= 16 * ui
        if getattr(self, "warning", ""):
            text(self.warning, (1.0, 0.6, 0.1, 1.0), 0, line)


_classes = (BLAYA_OT_smart_vert,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
