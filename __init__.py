# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blaya: Maya-style hotkeys, mouse navigation, marking menu, pivot editing and quad view.

The keymap itself lives in ``keymap.py`` and is exposed to Blender as the "Blaya"
keyconfig preset (see ``keymap_install.py``). Everything else here is plain operators
and menus that the keymap points at.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

from . import keymap_install, menus, ops_clip, ops_mesh, ops_pivot, ops_view, ui_axis


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
    pivot_edge_step: FloatProperty(
        name="Edge Snap Step",
        description="When snapping the pivot to an edge (D+C), move along it in steps of this percentage "
                    "of the edge length (5% = 21 stops including both ends). 0 slides freely",
        default=5.0, min=0.0, max=50.0, soft_min=1.0, precision=1, step=100, subtype='PERCENTAGE',
    )
    pivot_show_candidates: BoolProperty(
        name="Highlight Snap Points",
        description="While editing the pivot, highlight every point it can snap to (vertices, edges, face centers)",
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
    smooth_preview_shade_smooth: BoolProperty(
        name="Smooth Preview Shades Smooth",
        description="Show the smooth preview (2/3) with smooth shading, like Maya. Done with a temporary "
                    "Geometry Nodes modifier next to the preview: the mesh's own shading is never changed, "
                    "and pressing 1 removes both",
        default=False,
    )

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
        col.prop(self, "pivot_edge_step")
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
        col.label(text="Smooth Preview (1 / 2 / 3)", icon='MOD_SUBSURF')
        col.prop(self, "smooth_preview_shade_smooth")


class BLAYA_OT_activate_keymap(bpy.types.Operator):
    """Make Blaya the active keymap"""
    bl_idname = "blaya.activate_keymap"
    bl_label = "Activate Blaya Keymap"

    def execute(self, context):
        path = keymap_install.ensure_preset()
        bpy.ops.preferences.keyconfig_activate(filepath=path)
        return {'FINISHED'}


_modules = (ops_view, ops_pivot, ops_clip, ops_mesh, menus, ui_axis)
_classes = (BlayaPreferences, BLAYA_OT_activate_keymap)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    for mod in _modules:
        mod.register()
    keymap_install.ensure_preset()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
