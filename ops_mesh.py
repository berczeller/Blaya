# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling helpers: Maya-style smooth preview (1/2/3), component modes, delete without menu."""

import bpy
from bpy.props import EnumProperty, IntProperty

PREVIEW_NAME = "Smooth Preview"  # the only modifiers these operators ever add or remove
SHADING_NAME = "Smooth Preview Shading"
SHADING_GROUP = "Blaya Smooth Preview Shading"
_PREVIEW_TYPES = {'MESH', 'CURVE', 'SURFACE'}


def shading_node_group():
    """Geometry Nodes group that shades the (subdivided) result smooth without touching the mesh data."""
    ng = bpy.data.node_groups.get(SHADING_GROUP)
    if ng is not None and ng.bl_idname == 'GeometryNodeTree':
        return ng
    ng = bpy.data.node_groups.new(SHADING_GROUP, 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gin = ng.nodes.new('NodeGroupInput')
    gout = ng.nodes.new('NodeGroupOutput')
    smooth = ng.nodes.new('GeometryNodeSetShadeSmooth')
    gin.location, smooth.location, gout.location = (-300, 0), (0, 0), (300, 0)
    shade_in = next(s for s in smooth.inputs if s.type == 'BOOLEAN' and s.name != "Selection")
    shade_in.default_value = True
    ng.links.new(gin.outputs[0], smooth.inputs["Geometry"])
    ng.links.new(smooth.outputs["Geometry"], gout.inputs[0])
    return ng


def set_preview(obj, level, shade):
    """Add/update/remove the preview modifiers on `obj`. Never edits the mesh itself."""
    mod = obj.modifiers.get(PREVIEW_NAME)
    shading = obj.modifiers.get(SHADING_NAME)
    if level == 0:
        for m in (shading, mod):
            if m is not None:
                obj.modifiers.remove(m)
        return
    if mod is None:
        mod = obj.modifiers.new(PREVIEW_NAME, 'SUBSURF')
    mod.levels = level
    mod.render_levels = level
    mod.show_in_editmode = True
    mod.show_on_cage = False
    if shade and obj.type == 'MESH':
        if shading is None:
            shading = obj.modifiers.new(SHADING_NAME, 'NODES')
            shading.node_group = shading_node_group()
        shading.show_in_editmode = True
        # Keep the shading right after the subdivision so it applies to the smoothed result.
        names = [m.name for m in obj.modifiers]
        want = names.index(PREVIEW_NAME) + 1
        if names.index(SHADING_NAME) != want:
            obj.modifiers.move(names.index(SHADING_NAME), min(want, len(names) - 1))
    elif shading is not None:
        obj.modifiers.remove(shading)


def _prefs(context):
    return context.preferences.addons[__package__].preferences


def _targets(context):
    objs = [o for o in context.selected_objects if o.type in _PREVIEW_TYPES]
    act = context.active_object
    if act is not None and act.type in _PREVIEW_TYPES and act not in objs:
        objs.append(act)
    return objs


class BLAYA_OT_smooth_preview(bpy.types.Operator):
    """Smooth mesh preview like Maya's 1/2/3. Uses its own "Smooth Preview" modifier and never touches
    your other Subdivision modifiers"""
    bl_idname = "blaya.smooth_preview"
    bl_label = "Smooth Preview"
    bl_options = {'REGISTER', 'UNDO'}

    level: IntProperty(name="Level", description="0 turns the preview off", default=2, min=0, max=6)

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def execute(self, context):
        shade = _prefs(context).smooth_preview_shade_smooth
        for obj in _targets(context):
            set_preview(obj, self.level, shade)
        return {'FINISHED'}


class BLAYA_OT_component_mode(bpy.types.Operator):
    """Enter Edit Mode in a component selection mode"""
    bl_idname = "blaya.component_mode"
    bl_label = "Component Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(('VERT', "Vertex", ""), ('EDGE', "Edge", ""), ('FACE', "Face", ""), ('MULTI', "Multi", "")),
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'CURVE', 'SURFACE', 'LATTICE', 'ARMATURE', 'FONT', 'META'}

    def execute(self, context):
        obj = context.active_object
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        if obj.type == 'MESH':
            context.tool_settings.mesh_select_mode = {
                'VERT': (True, False, False),
                'EDGE': (False, True, False),
                'FACE': (False, False, True),
                'MULTI': (True, True, True),
            }[self.mode]
        return {'FINISHED'}


class BLAYA_OT_delete_components(bpy.types.Operator):
    """Delete the selected components according to the select mode, without the delete menu"""
    bl_idname = "blaya.delete_components"
    bl_label = "Delete Components"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        vert, edge, face = context.tool_settings.mesh_select_mode
        kind = 'VERT' if vert else 'EDGE' if edge else 'FACE'
        return bpy.ops.mesh.delete(type=kind)


class BLAYA_OT_subdivide_all(bpy.types.Operator):
    """Subdivide (or un-subdivide) the whole mesh of the active object"""
    bl_idname = "blaya.subdivide_all"
    bl_label = "Subdivide All"
    bl_options = {'REGISTER', 'UNDO'}

    reverse: bpy.props.BoolProperty(name="Un-Subdivide", default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        if context.active_object.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        if self.reverse:
            bpy.ops.mesh.unsubdivide()
        else:
            bpy.ops.mesh.subdivide()
        return {'FINISHED'}


_classes = (BLAYA_OT_smooth_preview, BLAYA_OT_component_mode, BLAYA_OT_delete_components,
            BLAYA_OT_subdivide_all)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
