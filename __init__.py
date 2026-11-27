# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blaya: Maya-style hotkeys, mouse navigation, marking menu, pivot editing and quad view.

The keymap itself lives in ``keymap.py`` and is exposed to Blender as the "Blaya"
keyconfig preset (see ``keymap_install.py``). Everything else here is plain operators
and menus that the keymap points at.
"""

import time

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       StringProperty)

from . import (keymap_install, menus, ops_clip, ops_empty, ops_export, ops_mesh, ops_pivot, ops_rotate, ops_save,
               ops_smartvert, ops_uv, ops_uvisland, ops_view, ui_axis)


class BlayaPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    space_tap: EnumProperty(
        name="Space Tap",
        description="What a quick tap of Space does. Holding Space always opens the view pie",
        items=(
            ('PERSP', "Perspective / Orthographic", "Toggle the view under the mouse between perspective and orthographic"),
            ('QUAD', "Quad View", "Toggle Quad View; leaving it maximizes the pane under the mouse, like Maya"),
        ),
        default='PERSP',
    )
    pie_delay: FloatProperty(
        name="Pie Menu Delay",
        description="How long Space must be held before the view pie opens. A shorter delay opens the pie "
                    "sooner, but quick taps longer than this open the pie instead of the tap action "
                    "(typical taps last 0.1-0.18 s)",
        default=0.18, min=0.1, max=1.0, step=1, precision=2, subtype='TIME_ABSOLUTE', unit='TIME_ABSOLUTE',
    )
    show_view_name: BoolProperty(
        name="Show View Name",
        description="Briefly show the view's name (Front, Top, Perspective...) at the bottom of the viewport "
                    "when you pick a view from the Space pie menu",
        default=True,
    )
    view_name_duration: FloatProperty(
        name="View Name Duration",
        description="How long the view name stays on screen, including its fade-out",
        default=1.0, min=0.3, max=5.0, step=10, precision=1, subtype='TIME_ABSOLUTE', unit='TIME_ABSOLUTE',
    )
    label_bg_color: FloatVectorProperty(
        name="Label Background",
        description="Colour and transparency of the view name box",
        subtype='COLOR_GAMMA', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 0.65),
    )
    label_axis_bg_color: FloatVectorProperty(
        name="Axis Box Background",
        description="Colour and transparency of the box holding the axis letter",
        subtype='COLOR_GAMMA', size=4, min=0.0, max=1.0, default=(0.95, 0.95, 0.95, 0.92),
    )
    label_text_color: FloatVectorProperty(
        name="Label Text",
        description="Colour of the view name (the axis letter always uses the theme's axis colour)",
        subtype='COLOR_GAMMA', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0),
    )
    label_rounding: FloatProperty(
        name="Label Rounding",
        description="Corner rounding of the view name label: 0 = rectangle, 1 = full capsule",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
    )
    label_border: BoolProperty(
        name="Label Border",
        description="Thin border around the view name label, in the Axis Box Background colour and transparency",
        default=True,
    )
    label_shadow: BoolProperty(
        name="Label Drop Shadow",
        description="Draw a soft shadow under the view name label",
        default=True,
    )
    axis_indicator: EnumProperty(
        name="Axis Indicator",
        description="Style of the axis indicator in the top-right corner of the 3D View",
        items=ui_axis.STYLE_ITEMS,
        default=ui_axis.DEFAULT_STYLE,
        update=lambda self, context: ui_axis.apply_style(self, context),
    )
    axis_restore: StringProperty(
        name="Axis Indicator Restore",
        description="Blender's indicator settings from before Blaya changed them (used by Don't Change)",
        default="", options={'HIDDEN'},
    )
    pivot_snap_radius: IntProperty(
        name="Pivot Snap Radius", description="Screen distance (pixels) at which the pivot jumps to a snap point",
        default=40, min=5, max=200, subtype='PIXEL',
    )
    pivot_show_candidates: BoolProperty(
        name="Highlight Snap Points",
        description="While editing the pivot, highlight every point it can snap to (vertices, edge midpoints, "
                    "face centers)",
        default=True,
    )
    clip_cap_default: BoolProperty(
        name="Cap New Surfaces",
        description="Close the holes left by the Clipping Tool (Shift+C) so cut pieces stay solid. "
                    "Toggle with C while cutting",
        default=True,
    )
    clip_keep_default: EnumProperty(
        name="Start With",
        description="Keep mode the Clipping Tool starts in (cycle with Shift+X while cutting)",
        items=(
            ('A', "Keep Side A", "Keep the side marked A"),
            ('B', "Keep Side B", "Keep the side marked B"),
            ('BOTH', "Keep Both", "Split into two separate objects"),
        ),
        default='A',
    )
    clip_show_hints: BoolProperty(
        name="Show Key Hints",
        description="Show a small list of the Clipping Tool's keys in the bottom-left corner while it's active",
        default=True,
    )
    clip_snap_radius: IntProperty(
        name="Vertex Snap Radius",
        description="Screen distance (pixels) at which a clip line end snaps to a vertex instead of the grid",
        default=20, min=0, max=200, subtype='PIXEL',
    )
    uv_smart_select: BoolProperty(
        name="Smart Selection",
        description="In the UV Editor a click picks the vertex, edge or face closest to the mouse. "
                    "Keys 1-4 fix a mode, 5 goes back to smart selection",
        default=True,
        update=lambda self, context: setattr(context.window_manager, "blaya_uv_auto", self.uv_smart_select),
    )
    uv_auto_detach: BoolProperty(
        name="Auto Detach on Move",
        description="In Face or Island mode, moving a selection splits it from the rest of its UV island first, "
                    "so neighbouring faces don't stretch",
        default=True,
    )
    uv_island_colors: BoolProperty(
        name="UV Island Highlight",
        description="In UV Island mode, tint and outline the selected islands and the island under the mouse "
                    "in the 3D View",
        default=True,
    )
    uv_island_alpha: FloatProperty(
        name="Island Tint Opacity", default=0.25, min=0.05, max=1.0, subtype='FACTOR',
    )
    uv_island_color: FloatVectorProperty(
        name="Selected Island Colour",
        description="Tint and outline of the selected UV islands",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0, default=(0.2, 0.75, 1.0),
    )
    uv_island_hover_color: FloatVectorProperty(
        name="Hover Island Colour",
        description="Tint and outline of the UV island under the mouse",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0, default=(1.0, 0.85, 0.3),
    )
    uv_show_hints: BoolProperty(
        name="Show Key Hints",
        description="Show the UV pivot keys in the bottom-right corner while editing the UV pivot",
        default=True,
    )
    smooth_preview_shade_smooth: BoolProperty(
        name="Smooth Preview Shades Smooth",
        description="Show the smooth preview (2/3) with smooth shading, like Maya. Done with a temporary "
                    "Geometry Nodes modifier next to the preview: the mesh's own shading is never changed, "
                    "and pressing 1 removes both",
        default=False,
    )
    # Save pie (Ctrl+S) and Auto Save
    autosave_interval: FloatProperty(
        name="Auto Save Interval", description="Seconds between automatic copies while the file has changes",
        default=30.0, min=10.0, soft_max=600.0, step=100, precision=0, subtype='TIME_ABSOLUTE', unit='TIME_ABSOLUTE',
    )
    autosave_limit: IntProperty(
        name="Keep Autosaves", description="How many automatic copies to keep per project (the oldest go first)",
        default=20, min=3, max=500,
    )
    autosave_undo: BoolProperty(
        name="Save on Undo", description="Also take a copy right after each undo", default=True,
    )
    autosave_redo: BoolProperty(
        name="Save on Redo Panel", description="Also take a copy when you start tweaking an operator in the redo panel",
        default=False,
    )
    autosave_folder: StringProperty(
        name="Auto Save Folder",
        description="Where the copies go. Empty: a 'Blaya Autosave' folder in Blender's temporary directory",
        default="", subtype='DIR_PATH',
    )
    save_pie_show_obj: BoolProperty(name="OBJ", default=True)
    save_pie_show_plasticity: BoolProperty(name="Plasticity", description="OBJ with Z up, Y forward", default=True)
    save_pie_show_fbx: BoolProperty(name="FBX", default=True)
    save_pie_show_usd: BoolProperty(name="USD", default=True)
    save_pie_show_gltf: BoolProperty(name="glTF", default=False)
    save_pie_show_stl: BoolProperty(name="STL", default=False)
    group_hide_children: BoolProperty(
        name="Empties Hide Like Collections",
        description="Hiding or showing an Empty also hides or shows the objects parented under it, "
                    "like a collection",
        default=True,
    )
    fbx_export_apply_scale_all: BoolProperty(
        name="FBX Apply Scale All", description="Export FBX with Apply Scalings set to 'FBX All' (for Unity)",
        default=False,
    )
    unity_apply_scale: EnumProperty(
        name="Apply Scalings",
        description="For roots exported for the first time. Each root keeps the setting of its first export, "
                    "so its size in Unity never changes",
        items=ops_export.SCALE_ITEMS, default='FBX_SCALE_ALL',
    )
    unity_apply_transform: BoolProperty(
        name="Apply Transform",
        description="For roots exported for the first time: bake the Z-up to Y-up conversion into the mesh, "
                    "so objects arrive in Unity with rotation 0,0,0. Each root keeps the setting of its first "
                    "export",
        default=True,
    )
    unity_triangulate: BoolProperty(
        name="Triangulate",
        description="Triangulate on export. Off keeps the triangulation of the source (a Triangulate modifier "
                    "is applied either way), so it matches what the textures were baked on",
        default=False,
    )
    unity_tangents: BoolProperty(
        name="Tangents",
        description="Write tangents to the FBX. Off lets Unity calculate them (Calculate Mikktspace)",
        default=False,
    )
    unity_presets: CollectionProperty(type=ops_export.BlayaExportPreset)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        kc_active = context.preferences.keymap.active_keyconfig
        box = layout.box()
        row = box.row()
        if kc_active == keymap_install.KEYCONFIG_NAME:
            row.label(text="Blaya keymap is active", icon='CHECKMARK')
        else:
            row.label(text=f"Active keymap: {kc_active}", icon='INFO')
            row.operator("blaya.activate_keymap", icon='KEYINGSET')
        col = layout.column(heading="")
        col.label(text="Space Bar", icon='VIEW_PERSPECTIVE')
        col.prop(self, "space_tap", text="Tap")
        col.prop(self, "pie_delay")
        col.prop(self, "show_view_name")
        sub = col.column()
        sub.active = self.show_view_name
        sub.prop(self, "view_name_duration")
        sub.prop(self, "label_rounding", slider=True)
        sub.prop(self, "label_border")
        sub.prop(self, "label_shadow")
        sub.prop(self, "label_bg_color")
        sub.prop(self, "label_axis_bg_color")
        sub.prop(self, "label_text_color")
        layout.separator()
        col = layout.column()
        col.label(text="Viewport", icon='ORIENTATION_GIMBAL')
        col.prop(self, "axis_indicator")
        layout.separator()
        col = layout.column()
        col.label(text="Pivot Edit (D + V / C / F / G / X)", icon='OBJECT_ORIGIN')
        col.prop(self, "pivot_snap_radius")
        col.prop(self, "pivot_show_candidates")
        layout.separator()
        col = layout.column()
        col.label(text="Clipping Tool (Shift+C)", icon='MOD_BOOLEAN')
        col.prop(self, "clip_keep_default")
        col.prop(self, "clip_cap_default")
        col.prop(self, "clip_snap_radius")
        col.prop(self, "clip_show_hints")
        layout.separator()
        col = layout.column()
        col.label(text="UV Editor", icon='UV')
        col.prop(self, "uv_smart_select")
        col.prop(self, "uv_auto_detach")
        col.prop(self, "uv_island_colors")
        sub = col.column()
        sub.active = self.uv_island_colors
        sub.prop(self, "uv_island_color")
        sub.prop(self, "uv_island_hover_color")
        sub.prop(self, "uv_island_alpha", slider=True)
        col.prop(self, "uv_show_hints")
        layout.separator()
        col = layout.column()
        col.label(text="Smooth Preview (1 / 2 / 3)", icon='MOD_SUBSURF')
        col.prop(self, "smooth_preview_shade_smooth")
        layout.separator()
        col = layout.column()
        col.label(text="Empties", icon='EMPTY_AXIS')
        col.prop(self, "group_hide_children")
        layout.separator()
        col = layout.column()
        col.label(text="Save Pie (Ctrl+S)", icon='FILE_TICK')
        row = col.row(heading="Export Formats")
        for name in ("obj", "plasticity", "fbx", "usd", "gltf", "stl"):
            row.prop(self, f"save_pie_show_{name}", toggle=True)
        col.prop(self, "fbx_export_apply_scale_all")
        col.prop(self, "autosave_interval")
        col.prop(self, "autosave_limit")
        col.prop(self, "autosave_undo")
        col.prop(self, "autosave_redo")
        col.prop(self, "autosave_folder")
        layout.separator()
        col = layout.column()
        col.label(text="Unity Export (Ctrl+S, sidebar Blaya tab)", icon='EXPORT')
        col.prop(self, "unity_apply_scale")
        col.prop(self, "unity_apply_transform")
        col.prop(self, "unity_triangulate")
        col.prop(self, "unity_tangents")
        col.label(text="Folder Presets")
        for i, p in enumerate(self.unity_presets):
            row = col.row(align=True)
            row.prop(p, "name", text="")
            row.prop(p, "path", text="")
            row.operator("blaya.export_preset_remove", text="", icon='X').index = i
        col.operator("blaya.export_preset_add", text="Save the Scene's Folder as a Preset", icon='ADD')


class BLAYA_OT_activate_keymap(bpy.types.Operator):
    """Make Blaya the active keymap"""
    bl_idname = "blaya.activate_keymap"
    bl_label = "Activate Blaya Keymap"

    def execute(self, context):
        path = keymap_install.ensure_preset()
        bpy.ops.preferences.keyconfig_activate(filepath=path)
        return {'FINISHED'}


_modules = (ops_view, ops_pivot, ops_clip, ops_mesh, ops_empty, ops_rotate, ops_save, ops_smartvert, ops_uv,
            ops_uvisland, ops_export, menus, ui_axis)
_classes = (ops_export.BlayaExportPreset, BlayaPreferences, BLAYA_OT_activate_keymap)


KEYMAP_WAIT = 5.0  # seconds to wait for the Blaya keyconfig to become active after loading
_keymap_wait_start = [0.0]


def _refresh_keymap():
    """Rebuild the Blaya keymap once Blaya's operators are registered.

    Blender can build the keymap before Blaya registers (at start-up), and turning Blaya off and on leaves
    the keymap items pointing at the old operators. Either way the items lose their settings: 1 / 2 / 3
    all ran smooth preview level 2 and D+C / F / G / X all started in Vertex mode. Reading those stale
    items' properties can crash Blender, so the keymap is rebuilt instead of checked.
    """
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.active if wm is not None else None
        if kc is not None and kc.name == keymap_install.KEYCONFIG_NAME:
            bpy.utils.keyconfig_set(keymap_install.ensure_preset())
            return None
    except Exception as exc:  # never block start-up over the keymap
        print("Blaya: could not refresh the keymap:", exc)
        return None
    if time.monotonic() - _keymap_wait_start[0] < KEYMAP_WAIT:
        return 0.25
    return None


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    for mod in _modules:
        mod.register()
    keymap_install.ensure_preset()
    _keymap_wait_start[0] = time.monotonic()
    bpy.app.timers.register(_refresh_keymap, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_refresh_keymap):
        bpy.app.timers.unregister(_refresh_keymap)
    for mod in reversed(_modules):
        mod.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
