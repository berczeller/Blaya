# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quick rotation by a typed angle: hold E and tap X / Y / Z in Object Mode.

A small box opens at the mouse with the last angle used, already selected: type to replace it (or
press Enter to repeat it). The selection turns live while typing, each object around its own origin,
along the axis of the header's Transform Orientation. Enter or a click applies (one undo step),
Esc or right-click cancels and restores everything.
"""

import math

import blf
import bpy
import gpu
from bpy.props import EnumProperty
from mathutils import Matrix, Quaternion

from . import ops_view

AXIS_ITEMS = (('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""))
_AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}
_ORIENT_LABELS = {'GLOBAL': "Global", 'LOCAL': "Local", 'NORMAL': "Normal", 'GIMBAL': "Gimbal",
                  'VIEW': "View", 'CURSOR': "Cursor", 'PARENT': "Parent"}
_DIGIT_TYPES = {f"{w}": str(i) for i, w in enumerate(
    ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"))}
_DIGIT_TYPES.update({f"NUMPAD_{i}": str(i) for i in range(10)})
_NAV_TYPES = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', 'TRACKPADPAN',
              'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM', 'NDOF_MOTION'}
MAX_CHARS = 10
SNAP_DEGREE_EPS = 1e-5  # radians: Euler values this close to a whole degree are rounded to it

_last_angle = [90.0]  # degrees, shared by all axes for the Blender session
_running = None


def in_quick_rotate():
    return _running is not None


def format_angle(value):
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def parse_angle(text):
    """Degrees typed in the box, or None while it isn't a number yet ("", "-", ".")."""
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


# --------------------------------------------------------------------------- rotation math

def orientation(context, obj):
    """World-space orientation (3x3, unit columns) of the header's Transform Orientation for `obj`."""
    slot = context.scene.transform_orientation_slots[0]
    kind = slot.type
    if kind in {'LOCAL', 'NORMAL', 'GIMBAL'}:
        return obj.matrix_world.to_quaternion().to_matrix()
    if kind == 'PARENT':
        return obj.parent.matrix_world.to_quaternion().to_matrix() if obj.parent else Matrix.Identity(3)
    if kind == 'VIEW':
        rv3d = context.region_data
        return rv3d.view_rotation.to_matrix() if rv3d is not None else Matrix.Identity(3)
    if kind == 'CURSOR':
        return context.scene.cursor.matrix.to_quaternion().to_matrix()
    custom = getattr(slot, "custom_orientation", None)
    if custom is not None:
        return custom.matrix.to_quaternion().to_matrix()
    return Matrix.Identity(3)


def orientation_label(context):
    slot = context.scene.transform_orientation_slots[0]
    custom = getattr(slot, "custom_orientation", None)
    return custom.name if custom is not None else _ORIENT_LABELS.get(slot.type, slot.type.title())


def save_state(obj):
    return (obj.rotation_mode, obj.rotation_euler.copy(), obj.rotation_quaternion.copy(),
            tuple(obj.rotation_axis_angle))


def restore_state(obj, state):
    mode, euler, quat, axis_angle = state
    obj.rotation_mode = mode
    obj.rotation_euler = euler
    obj.rotation_quaternion = quat
    obj.rotation_axis_angle = axis_angle


def _state_quaternion(state):
    mode, euler, quat, axis_angle = state
    if mode == 'QUATERNION':
        return quat.normalized()
    if mode == 'AXIS_ANGLE':
        angle, x, y, z = axis_angle
        return Quaternion((x, y, z), angle)
    return euler.to_quaternion()


def _snap_degrees(euler):
    for k in range(3):
        deg = math.degrees(euler[k])
        whole = round(deg)
        if abs(math.radians(deg - whole)) < SNAP_DEGREE_EPS:
            euler[k] = math.radians(whole)
    return euler


def _rotation_animated(obj):
    anim = obj.animation_data
    action = anim.action if anim is not None else None
    if action is None:
        return False
    try:
        return any(fc.data_path.startswith(("rotation_", "delta_rotation")) for fc in action.fcurves)
    except AttributeError:  # layered actions without a flat fcurves list: assume animated
        return True


def rotate_object(context, obj, state, axis, degrees):
    """Set `obj`'s rotation to its saved `state` turned by `degrees` around `axis` of the header's
    orientation, about the object's own origin. Location and scale are left alone."""
    mode, euler0, quat0, _aa = state
    axis_world = orientation(context, obj).col[_AXIS_INDEX[axis]].normalized()
    # The rotation channel lives in parent space, after the delta rotation: express the world axis there.
    parent = obj.parent.matrix_world @ obj.matrix_parent_inverse if obj.parent else Matrix.Identity(4)
    space = parent.to_3x3() @ obj.delta_rotation_quaternion.to_matrix() if mode in {'QUATERNION', 'AXIS_ANGLE'} \
        else parent.to_3x3() @ obj.delta_rotation_euler.to_matrix()
    local_axis = space.inverted_safe() @ axis_world
    if local_axis.length < 1e-12:
        return
    turn = Quaternion(local_axis.normalized(), math.radians(degrees))
    q = turn @ _state_quaternion(state)
    if mode == 'QUATERNION':
        if q.dot(quat0) < 0.0:
            q.negate()  # stay on the same side as the original, so keyframes don't flip
        obj.rotation_quaternion = q
    elif mode == 'AXIS_ANGLE':
        ax, ang = q.to_axis_angle()
        obj.rotation_axis_angle = (ang, ax.x, ax.y, ax.z)
    else:
        euler = q.to_euler(mode, euler0)  # closest to the old values, so animation doesn't flip
        if not _rotation_animated(obj):
            # Not animated: keep angles readable. A value that started within -180..180 goes back into
            # that range (four -90 turns end at 0, not -360); values set outside it on purpose stay.
            for k in range(3):
                if -math.pi < euler0[k] <= math.pi and not -math.pi < euler[k] <= math.pi:
                    euler[k] = math.remainder(euler[k], math.tau)
        obj.rotation_euler = _snap_degrees(euler)


def insert_auto_keys(context, objects):
    if not context.scene.tool_settings.use_keyframe_insert_auto:
        return
    for obj in objects:
        path = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(
            obj.rotation_mode, "rotation_euler")
        try:
            obj.keyframe_insert(data_path=path)
        except (RuntimeError, TypeError):
            pass


# --------------------------------------------------------------------------- operator

class BLAYA_OT_quick_rotate(bpy.types.Operator):
    """Rotate the selected objects by a typed angle around X, Y or Z (header orientation), each around
    its own origin. Enter or click applies, Esc or right-click cancels"""
    bl_idname = "blaya.quick_rotate"
    bl_label = "Quick Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name="Axis", items=AXIS_ITEMS, default='Z')

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.area is not None and context.area.type == 'VIEW_3D'
                and bool(context.selected_editable_objects))

    # -- text field

    def type_text(self, char):
        """Feed one typed character: a digit, '-' (flips the sign) or '.' / ',' (decimal point)."""
        if char == "-":
            text = "" if self._selected else self._text
            self._text = text[1:] if text.startswith("-") else "-" + text
        elif char in {".", ","}:
            if self._selected or not self._text:
                self._text = "0."
            elif "." not in self._text:
                self._text += "."
        elif char.isdigit():
            self._text = char if self._selected else (self._text + char)[:MAX_CHARS]
        else:
            return False
        self._selected = False
        return True

    def backspace(self, clear=False):
        self._text = "" if (self._selected or clear) else self._text[:-1]
        self._selected = False

    def value(self):
        return parse_angle(self._text)

    # -- preview / apply

    def preview(self, context):
        degrees = self.value() or 0.0
        for obj, state in self._saved:
            restore_state(obj, state)
            rotate_object(context, obj, state, self.axis, degrees)
        context.view_layer.update()
        if context.area:
            context.area.tag_redraw()

    def restore(self, context):
        for obj, state in self._saved:
            restore_state(obj, state)
        context.view_layer.update()

    def apply(self, context):
        degrees = self.value()
        if degrees is None or abs(degrees) < 1e-9:
            return self.cancel_box(context)
        self.preview(context)
        insert_auto_keys(context, [obj for obj, _state in self._saved])
        _last_angle[0] = degrees
        self.report({'INFO'}, f"Rotated {degrees:+g}° around {self.axis} ({orientation_label(context)})")
        self._finish(context, {'FINISHED'})
        return {'FINISHED'}

    def cancel_box(self, context):
        self.restore(context)
        self._finish(context, {'CANCELLED'})
        return {'CANCELLED'}

    # -- drawing

    def box_rect(self, context):
        """(x0, y0, x1, y1) of the box in region pixels, placed next to the mouse and kept inside the region."""
        region = self._region
        ui = context.preferences.system.ui_scale
        w, h = self._box_size
        x = self._anchor[0] + 18 * ui
        y = self._anchor[1] - 18 * ui - h
        x = max(4 * ui, min(x, region.width - w - 4 * ui))
        y = max(4 * ui + 18 * ui, min(y, region.height - h - 4 * ui))
        return x, y, x + w, y + h

    def draw_px(self):
        context = bpy.context
        region = context.region
        if region is None or region.as_pointer() != self._region_ptr:
            return
        prefs = context.preferences.addons[__package__].preferences
        ui = context.preferences.system.ui_scale
        font = 0
        blf.size(font, 15 * ui)
        cap_h = blf.dimensions(font, "X")[1]
        pad = 9 * ui
        label = "Rotate "
        orient = f" ({orientation_label(context)})"
        shown = self._text if self._text else " "
        field_w = max(blf.dimensions(font, shown)[0], blf.dimensions(font, "000")[0]) + 2 * pad * 0.6
        parts_w = (blf.dimensions(font, label)[0] + blf.dimensions(font, self.axis)[0]
                   + blf.dimensions(font, orient)[0] + 10 * ui + field_w + blf.dimensions(font, " °")[0])
        h = cap_h + 2 * pad
        self._box_size = (parts_w + 2 * pad, h)
        x0, y0, x1, y1 = self.box_rect(context)

        bg, axis_bg, fg = tuple(prefs.label_bg_color), tuple(prefs.label_axis_bg_color), tuple(prefs.label_text_color)
        radius = prefs.label_rounding * h / 2.0
        gpu.state.blend_set('ALPHA')
        flat = gpu.shader.from_builtin('UNIFORM_COLOR')
        outline = ops_view.rounded_box((x0, y0, x1, y1), radius, True, True)
        if prefs.label_shadow:
            ops_view.draw_shadow(outline, (0.0, -2.0 * ui), 6.0 * ui, (0.0, 0.0, 0.0, 0.28))
        ops_view._fill(flat, outline, bg)
        ops_view.draw_soft_edge(outline, 1.25 * ui, lambda _p: bg)

        tx, ty = x0 + pad, y0 + pad
        # Field for the value: light box, with a selection highlight while the prefill is selected.
        fx0 = x0 + pad + blf.dimensions(font, label + self.axis + orient)[0] + 10 * ui
        field = (fx0, y0 + 4 * ui, fx0 + field_w, y1 - 4 * ui)
        ops_view._fill(flat, ops_view.rounded_box(field, 4 * ui), axis_bg[:3] + (min(1.0, axis_bg[3]),))
        text_w = blf.dimensions(font, shown)[0]
        text_x = field[0] + pad * 0.6
        if self._selected and self._text:
            sel = (text_x - 2 * ui, field[1] + 3 * ui, text_x + text_w + 2 * ui, field[3] - 3 * ui)
            ops_view._fill(flat, ops_view.rounded_box(sel, 2 * ui), (0.28, 0.5, 0.9, 0.85))
        gpu.state.blend_set('NONE')

        def text(s, x, color):
            blf.position(font, x, ty, 0)
            blf.color(font, *color)
            blf.draw(font, s)
            return x + blf.dimensions(font, s)[0]

        x = text(label, tx, fg)
        x = text(self.axis, x, ops_view.axis_color(context, self.axis)[:3] + (1.0,))
        text(orient, x, fg[:3] + (fg[3] * 0.7,))
        dark = (0.05, 0.05, 0.05, 1.0)
        end = text(shown, text_x, (1.0, 1.0, 1.0, 1.0) if (self._selected and self._text) else dark)
        if not self._selected:
            gpu.state.blend_set('ALPHA')
            caret = ((end + 1 * ui, field[1] + 4 * ui), (end + 2.5 * ui, field[1] + 4 * ui),
                     (end + 2.5 * ui, field[3] - 4 * ui), (end + 1 * ui, field[3] - 4 * ui))
            ops_view._fill(flat, list(caret), dark)
            gpu.state.blend_set('NONE')
        text(" °", field[2], fg)

        blf.size(font, 11 * ui)
        blf.position(font, x0 + 2 * ui, y0 - 15 * ui, 0)
        blf.color(font, 1.0, 1.0, 1.0, 0.55)
        blf.draw(font, "Enter apply   Esc cancel   X Y Z axis   - sign")

    # -- lifecycle

    def invoke(self, context, event):
        global _running
        if _running is not None:
            return {'CANCELLED'}
        self._region = context.region
        self._region_ptr = context.region.as_pointer()
        self._anchor = (event.mouse_region_x, event.mouse_region_y)
        self._box_size = (220.0, 30.0)
        self._saved = [(obj, save_state(obj)) for obj in context.selected_editable_objects]
        self._text = format_angle(_last_angle[0])
        self._selected = True
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        _running = self
        self.preview(context)
        context.workspace.status_text_set("Quick Rotate   |   type the angle   Enter / click: apply   "
                                          "Esc / right-click: cancel   X Y Z: axis   -: flip sign")
        return {'RUNNING_MODAL'}

    def execute(self, context):
        # Non-interactive (scripts, redo): rotate by the last angle without the box.
        degrees = _last_angle[0]
        objs = list(context.selected_editable_objects)
        for obj in objs:
            rotate_object(context, obj, save_state(obj), self.axis, degrees)
        insert_auto_keys(context, objs)
        return {'FINISHED'}

    def _finish(self, context, result):
        global _running
        self._result = result
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        if _running is self:
            _running = None

    def modal(self, context, event):
        if getattr(self, "_result", None) is not None:
            return self._result  # already finished (e.g. driven from a script): just let Blender drop it
        if context.mode != 'OBJECT' or context.area is None:
            return self.cancel_box(context)
        typ, val = event.type, event.value

        if typ in _NAV_TYPES or (event.alt and typ in {'LEFTMOUSE', 'RIGHTMOUSE', 'MOUSEMOVE'}):
            return {'PASS_THROUGH'}  # navigation keeps working while the box is open
        if typ in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            return {'RUNNING_MODAL'}
        if val != 'PRESS' or event.is_repeat:
            return {'RUNNING_MODAL'}  # E release, held keys, releases of our own keys

        if typ in {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'}:
            return self.apply(context)
        if typ in {'ESC', 'RIGHTMOUSE'}:
            return self.cancel_box(context)
        if typ in _AXIS_INDEX and not (event.ctrl or event.alt or event.oskey):
            self.axis = typ
            self.preview(context)
            return {'RUNNING_MODAL'}
        if typ in {'BACK_SPACE', 'DEL'}:
            self.backspace(clear=event.ctrl or typ == 'DEL')
            self.preview(context)
            return {'RUNNING_MODAL'}
        char = event.unicode if event.unicode and event.unicode in "0123456789-.," else None
        if char is None:
            char = _DIGIT_TYPES.get(typ) or {'MINUS': "-", 'NUMPAD_MINUS': "-", 'PERIOD': ".",
                                             'NUMPAD_PERIOD': ".", 'COMMA': ","}.get(typ)
        if char is not None and self.type_text(char):
            self.preview(context)
        return {'RUNNING_MODAL'}


_classes = (BLAYA_OT_quick_rotate,)


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
