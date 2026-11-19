# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Menus: right-click marking menu, Space view pie, pivot/snap pie and component special menu."""

import bpy
from bpy.types import Menu

from .ops_pivot import SNAP_ITEMS, in_pivot_edit

# Pie slot order in Blender: W, E, S, N, NW, NE, SW, SE.


class BLAYA_MT_marking_menu(Menu):
    bl_idname = "BLAYA_MT_marking_menu"
    bl_label = "Marking Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        pie.operator("blaya.component_mode", text="Vertex", icon='VERTEXSEL').mode = 'VERT'
        pie.operator("blaya.component_mode", text="Multi", icon='EDITMODE_HLT').mode = 'MULTI'
        pie.operator("object.shade_smooth", text="Smooth", icon='MOD_SMOOTH')
        pie.operator("blaya.component_mode", text="Edge", icon='EDGESEL').mode = 'EDGE'
        pie.operator("view3d.localview", text="Isolate", icon='BORDERMOVE')
        pie.operator("object.mode_set", text="Object", icon='OBJECT_DATA').mode = 'OBJECT'
        pie.operator("object.shade_flat", text="Flat", icon='MOD_WIREFRAME')
        pie.operator("blaya.component_mode", text="Face", icon='FACESEL').mode = 'FACE'

        # Extra tools below the pie (the slots N2/S2 are left empty so the box sits low).
        pie.separator()
        pie.separator()
        col = pie.column()
        gap = col.column()
        gap.separator()
        gap.scale_y = 6

        if context.mode == 'EDIT_MESH':
            row = col.box().row(align=True)
            row.operator("mesh.select_all", text="", icon='UV_SYNC_SELECT').action = 'INVERT'
            row.operator("mesh.select_all", text="", icon='SELECT_EXTEND').action = 'SELECT'
            row.operator("mesh.select_all", text="", icon='SELECT_SUBTRACT').action = 'DESELECT'
            row.operator("mesh.select_edge_loop_multi", text="", icon='ANCHOR_LEFT')
            row.operator("mesh.select_edge_ring_multi", text="", icon='ANCHOR_TOP')
            row.operator("mesh.select_more", text="", icon='ADD')
            row.operator("mesh.select_less", text="", icon='REMOVE')

        row = col.box().row(align=True)
        row.menu("BLAYA_MT_add", text="", icon='ADD')
        row.operator("screen.screen_full_area", text="", icon='FULLSCREEN_ENTER')
        row.operator("blaya.subdivide_all", text="", icon='MOD_MULTIRES').reverse = False
        row.operator("blaya.subdivide_all", text="", icon='MESH_PLANE').reverse = True
        if context.mode == 'EDIT_MESH':
            row.operator("mesh.flip_normals", text="", icon='NORMALS_FACE')
            row.operator("mesh.merge", text="", icon='AUTOMERGE_ON')
            row.operator("mesh.remove_doubles", text="", icon='AUTOMERGE_OFF')
        row.menu("BLAYA_MT_transforms", text="", icon='FREEZE')

        row = col.box().row(align=True)
        if context.space_data and context.space_data.type == 'VIEW_3D':
            row.prop(context.space_data.overlay, "show_wireframes", text="", icon='MESH_UVSPHERE', toggle=True)
        if context.object is not None:
            row.prop(context.object, "show_wire", text="", icon='SHADING_WIRE', toggle=True)
        row.menu("BLAYA_MT_modes", text="", icon='SCULPTMODE_HLT')
        row.menu("BLAYA_MT_pivot", text="", icon='SNAP_ON')


class BLAYA_MT_view_pie(Menu):
    bl_idname = "BLAYA_MT_view_pie"
    bl_label = "Views"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for axis, label in (('LEFT', "Left"), ('RIGHT', "Right"), ('BOTTOM', "Bottom"),
                            ('TOP', "Top"), ('FRONT', "Front"), ('BACK', "Back")):
            pie.operator("blaya.view_ortho", text=label, icon='VIEW_ORTHO').axis = axis
        pie.operator("blaya.view_persp_toggle", text="Persp/Ortho", icon='ARROW_LEFTRIGHT')
        pie.operator("blaya.quad_toggle", text="Quad View", icon='VIEW_PERSPECTIVE')

        pie.separator()
        pie.separator()
        col = pie.column()
        gap = col.column()
        gap.separator()
        gap.scale_y = 7
        box = col.box().column()
        box.scale_y = 1.3
        box.operator("screen.area_split", text="Vertical Split", icon='SPREADSHEET').direction = 'VERTICAL'
        box.operator("screen.area_split", text="Horizontal Split", icon='SPREADSHEET').direction = 'HORIZONTAL'
        box.operator("view3d.view_camera", text="Active Camera", icon='CAMERA_DATA')
        box.prop(context.space_data, "lock_camera", text="Lock Camera to View", icon='CON_CAMERASOLVER')
        box.operator("view3d.camera_to_view", text="Camera to View", icon='RESTRICT_VIEW_ON')
        box.operator("screen.screen_full_area", text="Maximize", icon='FULLSCREEN_ENTER')


class BLAYA_MT_pivot(Menu):
    bl_idname = "BLAYA_MT_pivot"
    bl_label = "Pivot & Snapping"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Edit pivot, snapping to:")
        for ident, label, _desc, icon, _n in SNAP_ITEMS:
            layout.operator("blaya.pivot_edit", text=label, icon=icon).snap = ident
        if in_pivot_edit():
            layout.separator()
            layout.operator("blaya.pivot_exit", text="Finish Pivot Edit", icon='OBJECT_ORIGIN')
        layout.separator()
        ts = context.scene.tool_settings
        layout.prop(ts, "use_snap", text="Transform Snapping")


class BLAYA_MT_add(Menu):
    bl_idname = "BLAYA_MT_add"
    bl_label = "Create"

    def draw(self, context):
        layout = self.layout
        for op, text, icon in (
            ("mesh.primitive_plane_add", "Plane", 'MESH_PLANE'),
            ("mesh.primitive_cube_add", "Cube", 'MESH_CUBE'),
            ("mesh.primitive_circle_add", "Circle", 'MESH_CIRCLE'),
            ("mesh.primitive_uv_sphere_add", "UV Sphere", 'MESH_UVSPHERE'),
            ("mesh.primitive_ico_sphere_add", "Ico Sphere", 'MESH_ICOSPHERE'),
            ("mesh.primitive_cylinder_add", "Cylinder", 'MESH_CYLINDER'),
            ("mesh.primitive_cone_add", "Cone", 'MESH_CONE'),
            ("mesh.primitive_torus_add", "Torus", 'MESH_TORUS'),
        ):
            layout.operator(op, text=text, icon=icon)
        layout.operator("object.empty_add", text="Null", icon='EMPTY_AXIS').type = 'PLAIN_AXES'
        layout.separator()
        for kind, text, icon in (('POINT', "Point", 'LIGHT_POINT'), ('SUN', "Sun", 'LIGHT_SUN'),
                                 ('SPOT', "Spot", 'LIGHT_SPOT'), ('AREA', "Area", 'LIGHT_AREA')):
            layout.operator("object.light_add", text=text, icon=icon).type = kind
        layout.separator()
        layout.operator("object.camera_add", text="Camera", icon='OUTLINER_DATA_CAMERA')


class BLAYA_MT_modes(Menu):
    bl_idname = "BLAYA_MT_modes"
    bl_label = "Mode"

    def draw(self, context):
        layout = self.layout
        for mode, text, icon in (('SCULPT', "Sculpt", 'SCULPTMODE_HLT'),
                                 ('VERTEX_PAINT', "Vertex Paint", 'VPAINT_HLT'),
                                 ('WEIGHT_PAINT', "Weight Paint", 'WPAINT_HLT'),
                                 ('TEXTURE_PAINT', "Texture Paint", 'TPAINT_HLT')):
            layout.operator("object.mode_set", text=text, icon=icon).mode = mode


class BLAYA_MT_transforms(Menu):
    bl_idname = "BLAYA_MT_transforms"
    bl_label = "Freeze / Reset Transforms"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Freeze Transforms", icon='FREEZE')
        for mode, text in (('ALL', "All"), ('LOC', "Location"), ('ROT', "Rotation"), ('SCALE', "Scale")):
            layout.operator("object.transforms_to_deltas", text=text).mode = mode
        layout.separator()
        layout.label(text="Reset Transforms", icon='LOOP_BACK')
        layout.operator("object.location_clear", text="Location").clear_delta = False
        layout.operator("object.rotation_clear", text="Rotation").clear_delta = False
        layout.operator("object.scale_clear", text="Scale").clear_delta = False
        layout.operator("object.origin_clear", text="Origin")


class BLAYA_MT_component_special(Menu):
    bl_idname = "BLAYA_MT_component_special"
    bl_label = "Component Tools"

    def draw(self, context):
        layout = self.layout
        vert, edge, face = context.tool_settings.mesh_select_mode
        if face and not (vert or edge):
            layout.menu("VIEW3D_MT_edit_mesh_faces", text="Face Tools", icon='FACESEL')
        elif edge and not vert:
            layout.menu("VIEW3D_MT_edit_mesh_edges", text="Edge Tools", icon='EDGESEL')
        else:
            layout.menu("VIEW3D_MT_edit_mesh_vertices", text="Vertex Tools", icon='VERTEXSEL')
        layout.separator()
        layout.label(text="Switch To")
        layout.operator("blaya.component_mode", text="Vertices", icon='VERTEXSEL').mode = 'VERT'
        layout.operator("blaya.component_mode", text="Edges", icon='EDGESEL').mode = 'EDGE'
        layout.operator("blaya.component_mode", text="Faces", icon='FACESEL').mode = 'FACE'
        layout.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATA').mode = 'OBJECT'


class BLAYA_MT_uv_marking_menu(Menu):
    bl_idname = "BLAYA_MT_uv_marking_menu"
    bl_label = "UV Marking Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        # Same slots as the 3D marking menu: W vertex, E island (multi), N edge, SE face.
        pie.operator("blaya.uv_select_mode", text="Vertex", icon='UV_VERTEXSEL').mode = 'VERTEX'
        pie.operator("blaya.uv_select_mode", text="Island", icon='UV_ISLANDSEL').mode = 'ISLAND'
        pie.operator("uv.unwrap", text="Unwrap", icon='UV')
        pie.operator("blaya.uv_select_mode", text="Edge", icon='UV_EDGESEL').mode = 'EDGE'
        pie.operator("uv.select_split", text="Split", icon='SCULPTMODE_HLT')
        pie.operator("uv.stitch", text="Stitch", icon='AUTOMERGE_ON')
        pie.operator("blaya.uv_straighten", text="Straighten", icon='ALIGN_JUSTIFY').axis = 'ALIGN_AUTO'
        pie.operator("blaya.uv_select_mode", text="Face", icon='UV_FACESEL').mode = 'FACE'

        pie.separator()
        pie.separator()
        col = pie.column()
        gap = col.column()
        gap.separator()
        gap.scale_y = 6
        wm = context.window_manager
        ts = context.scene.tool_settings
        row = col.box().row(align=True)
        row.operator("blaya.uv_select_mode", text="Auto", icon='RESTRICT_SELECT_OFF',
                     depress=getattr(wm, "blaya_uv_auto", False)).mode = 'AUTO'
        row.prop(ts, "use_uv_select_sync", text="", icon='UV_SYNC_SELECT')
        row.prop(ts, "uv_sticky_select_mode", text="", icon_only=True)
        row = col.box().row(align=True)
        row.operator("blaya.uv_straighten", text="", icon='EVENT_X').axis = 'ALIGN_X'
        row.operator("blaya.uv_straighten", text="", icon='EVENT_Y').axis = 'ALIGN_Y'
        row.menu("IMAGE_MT_uvs_align", text="", icon='ALIGN_CENTER')
        row.operator("uv.select_all", text="", icon='SELECT_EXTEND').action = 'SELECT'
        row.operator("uv.select_all", text="", icon='SELECT_SUBTRACT').action = 'DESELECT'
        row.operator("uv.select_all", text="", icon='UV_SYNC_SELECT').action = 'INVERT'
        row = col.box().row(align=True)
        row.operator("uv.mark_seam", text="", icon='EDGESEL').clear = False
        row.operator("uv.mark_seam", text="", icon='X').clear = True
        row.operator("uv.pack_islands", text="", icon='PACKAGE')
        row.operator("uv.average_islands_scale", text="", icon='FULLSCREEN_EXIT')
        row.menu("BLAYA_MT_uv_pivot", text="", icon='PIVOT_CURSOR')


class BLAYA_MT_uv_pivot(Menu):
    bl_idname = "BLAYA_MT_uv_pivot"
    bl_label = "UV Pivot"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Place pivot (2D cursor), snapping to:")
        for ident, label, _desc, icon, _n in SNAP_ITEMS:
            layout.operator("blaya.uv_pivot_edit", text=label, icon=icon).snap = ident
        layout.separator()
        layout.prop(context.space_data, "pivot_point", text="Pivot")


_classes = (
    BLAYA_MT_uv_marking_menu,
    BLAYA_MT_uv_pivot,
    BLAYA_MT_marking_menu,
    BLAYA_MT_view_pie,
    BLAYA_MT_pivot,
    BLAYA_MT_add,
    BLAYA_MT_modes,
    BLAYA_MT_transforms,
    BLAYA_MT_component_special,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
