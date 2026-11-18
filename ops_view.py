# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""View operators: orthographic axis views, Maya-style Quad View toggle, Space tap/hold."""

import time

import bpy
from bpy.props import EnumProperty

VIEW_PIE = "BLAYA_MT_view_pie"

AXES = (
    ('LEFT', "Left", ""),
    ('RIGHT', "Right", ""),
    ('TOP', "Top", ""),
    ('BOTTOM', "Bottom", ""),
    ('FRONT', "Front", ""),
    ('BACK', "Back", ""),
)


def _prefs(context):
    return context.preferences.addons[__package__].preferences


def _in_view3d(context):
    return context.area is not None and context.area.type == 'VIEW_3D'


# --------------------------------------------------------------------------- view name toast
# A short-lived label (e.g. "Front") at the bottom center of the pane whose view just changed.

_toast = {"text": "", "axis": None, "region": 0, "start": 0.0, "duration": 0.0}

# Which world axis each orthographic view looks along (shown as the coloured letter).
VIEW_AXIS = {'FRONT': 'Y', 'BACK': 'Y', 'LEFT': 'X', 'RIGHT': 'X', 'TOP': 'Z', 'BOTTOM': 'Z'}


def axis_color(context, axis):
    ui = context.preferences.themes[0].user_interface
    return tuple({'X': ui.axis_x, 'Y': ui.axis_y, 'Z': ui.axis_z}[axis])
_toast_handle = None
HOLD_FRACTION = 0.6  # full opacity for this part of the duration, then fade out


def _tag_view3d_redraw():
    wm = bpy.context.window_manager
    for win in wm.windows if wm else ():
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def toast_alpha(now=None):
    """Current opacity of the toast (0 when hidden)."""
    if not _toast["text"] or _toast["duration"] <= 0:
        return 0.0
    t = (time.monotonic() if now is None else now) - _toast["start"]
    dur = _toast["duration"]
    hold = dur * HOLD_FRACTION
    if t < 0 or t >= dur:
        return 0.0
    if t <= hold:
        return 1.0
    return max(0.0, 1.0 - (t - hold) / (dur - hold))


def _toast_tick():
    _tag_view3d_redraw()
    if toast_alpha() > 0.0:
        return 0.03
    _toast["text"] = ""
    return None


def show_view_name(context, text, axis=None):
    """Show `text` (and an optional axis letter box) at the bottom center of the current 3D region."""
    prefs = _prefs(context)
    if not prefs.show_view_name or context.region is None:
        return
    _toast.update(text=text, axis=axis, region=context.region.as_pointer(), start=time.monotonic(),
                  duration=prefs.view_name_duration)
    if not bpy.app.timers.is_registered(_toast_tick):
        bpy.app.timers.register(_toast_tick, first_interval=0.0)


def toast_boxes(text_w, cap_h, pad, region_w, bottom, with_axis, end_pad=0.0):
    """Layout of the toast: (dark box, axis box or None, text origin). Boxes are (x0, y0, x1, y1).

    `end_pad` adds room at the rounded outer ends so the text never touches the curve.
    """
    h = cap_h + 2 * pad
    axis_w = h if with_axis else 0.0
    name_w = text_w + 2 * pad + end_pad + (0.0 if with_axis else end_pad)
    total = name_w + axis_w
    x0 = (region_w - total) / 2.0
    dark = (x0, bottom, x0 + name_w, bottom + h)
    light = (dark[2], bottom, dark[2] + axis_w, bottom + h) if with_axis else None
    return dark, light, (x0 + pad + end_pad, bottom + pad)


def rounded_box(box, radius, round_left=True, round_right=True, segments=10):
    """Outline (counter-clockwise points) of a box with rounded left and/or right corners.

    `radius` is clamped to half the box height, which gives capsule ends.
    """
    import math
    x0, y0, x1, y1 = box
    r = max(0.0, min(radius, (y1 - y0) / 2.0, (x1 - x0) / 2.0 if round_left and round_right else (x1 - x0)))

    def arc(cx, cy, a0):
        return [(cx + math.cos(math.radians(a0 + 90.0 * i / segments)) * r,
                 cy + math.sin(math.radians(a0 + 90.0 * i / segments)) * r) for i in range(segments + 1)]

    pts = []
    pts += arc(x0 + r, y0 + r, 180) if round_left and r > 0 else [(x0, y0)]   # bottom-left
    pts += arc(x1 - r, y0 + r, 270) if round_right and r > 0 else [(x1, y0)]  # bottom-right
    pts += arc(x1 - r, y1 - r, 0) if round_right and r > 0 else [(x1, y1)]    # top-right
    pts += arc(x0 + r, y1 - r, 90) if round_left and r > 0 else [(x0, y1)]    # top-left
    return pts


def _dedupe(pts, eps=1e-3):
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) <= eps and abs(out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def feather_ring(pts, width):
    """Triangles of a strip `width` px wide just outside a convex CCW outline.

    Returns (positions, is_outer flags) so callers can fade the colour from the edge outwards.
    """
    import math
    pts = _dedupe(pts)
    n = len(pts)
    if n < 3:
        return [], []
    normals = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        acc = [0.0, 0.0]
        for a, b in ((p0, p1), (p1, p2)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy) or 1.0
            acc[0] += dy / ln   # outward normal of a CCW edge
            acc[1] += -dx / ln
        ln = math.hypot(*acc) or 1.0
        normals.append((acc[0] / ln, acc[1] / ln))
    outer = [(p[0] + nx * width, p[1] + ny * width) for p, (nx, ny) in zip(pts, normals)]
    pos, flags = [], []
    for i in range(n):
        j = (i + 1) % n
        for v, f in ((pts[i], 0), (pts[j], 0), (outer[j], 1), (pts[i], 0), (outer[j], 1), (outer[i], 1)):
            pos.append(v)
            flags.append(f)
    return pos, flags


def _draw_smooth(pos, colors):
    from gpu_extras.batch import batch_for_shader
    import gpu
    if pos:
        sh = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(sh, 'TRIS', {"pos": pos, "color": colors}).draw(sh)


def draw_soft_edge(outline, width, color_at):
    """Antialiasing: fade from the shape's colour at its edge to transparent over `width` px."""
    pos, flags = feather_ring(outline, width)
    cols = []
    for p, f in zip(pos, flags):
        c = color_at(p)
        cols.append(c[:3] + (0.0 if f else c[3],))
    _draw_smooth(pos, cols)


def draw_shadow(outline, offset, softness, color):
    """Soft drop shadow: the outline shifted by `offset`, with a `softness` px blurred edge."""
    shifted = [(x + offset[0], y + offset[1]) for x, y in _dedupe(outline)]
    cx = sum(p[0] for p in shifted) / len(shifted)
    cy = sum(p[1] for p in shifted) / len(shifted)
    pos = [v for i in range(len(shifted)) for v in ((cx, cy), shifted[i], shifted[(i + 1) % len(shifted)])]
    _draw_smooth(pos, [color] * len(pos))
    draw_soft_edge(shifted, softness, lambda _p: color)


def border_segments(outline):
    """Closed outline as line segment pairs (for the antialiased polyline shader)."""
    pts = _dedupe(outline)
    return [p for i in range(len(pts)) for p in (pts[i], pts[(i + 1) % len(pts)])]


def draw_border(outline, width, color):
    from gpu_extras.batch import batch_for_shader
    import gpu
    region = bpy.context.region
    sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    sh.uniform_float("viewportSize", (region.width, region.height))
    sh.uniform_float("lineWidth", width)
    sh.uniform_float("color", color)
    batch_for_shader(sh, 'LINES', {"pos": border_segments(outline)}).draw(sh)


def _fill(shader, pts, color):
    from gpu_extras.batch import batch_for_shader
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    tris = [v for i in range(len(pts)) for v in ((cx, cy), pts[i], pts[(i + 1) % len(pts)])]
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRIS', {"pos": tris}).draw(shader)


def _draw_toast():
    import blf
    import gpu
    alpha = toast_alpha()
    context = bpy.context
    region = context.region
    if alpha <= 0.0 or region is None or region.as_pointer() != _toast["region"]:
        return
    ui = context.preferences.system.ui_scale
    font = 0
    blf.size(font, 20 * ui)
    text = _toast["text"]
    text_w = blf.dimensions(font, text)[0]
    cap_h = blf.dimensions(font, "X")[1]  # cap height: centers the text regardless of descenders
    axis = _toast["axis"]
    prefs = _prefs(context)
    pad = 10 * ui
    end_pad = prefs.label_rounding * (cap_h + 2 * pad) / 2.0 * 0.45
    dark, light, (tx, ty) = toast_boxes(text_w, cap_h, pad, region.width, 50 * ui, axis is not None, end_pad)
    bg, axis_bg, fg = tuple(prefs.label_bg_color), tuple(prefs.label_axis_bg_color), tuple(prefs.label_text_color)
    radius = prefs.label_rounding * (dark[3] - dark[1]) / 2.0  # 1.0 = capsule ends
    gpu.state.blend_set('ALPHA')
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    bg_c = bg[:3] + (bg[3] * alpha,)
    axis_c = axis_bg[:3] + (axis_bg[3] * alpha,)
    whole = (dark[0], dark[1], (light or dark)[2], dark[3])
    outline = rounded_box(whole, radius, True, True)
    if prefs.label_shadow:
        draw_shadow(outline, (0.0, -2.0 * ui), 6.0 * ui, (0.0, 0.0, 0.0, 0.28 * alpha))
    # One capsule: the name box rounds on the left (and right if there's no axis box), the axis box on the right.
    _fill(flat, rounded_box(dark, radius, True, light is None), bg_c)
    if light is not None:
        _fill(flat, rounded_box(light, radius, False, True), axis_c)
    # Antialiased outer edge: a ~1 px fade in the colour of whichever box is underneath.
    split = dark[2]
    draw_soft_edge(outline, 1.25 * ui, lambda p: axis_c if (light is not None and p[0] > split) else bg_c)
    if prefs.label_border:
        # Thin border in the axis box colour (follows its colour and transparency).
        draw_border(outline, 1.5 * ui, axis_c)
    gpu.state.blend_set('NONE')

    blf.position(font, tx, ty, 0)
    blf.color(font, *fg[:3], fg[3] * alpha)
    blf.draw(font, text)
    if light is not None:
        lw = blf.dimensions(font, axis)[0]
        blf.position(font, (light[0] + light[2] - lw) / 2.0, ty, 0)
        blf.color(font, *axis_color(context, axis)[:3], alpha)
        blf.draw(font, axis)


_AXIS_LABELS = {a[0]: a[1] for a in AXES}


class BLAYA_OT_view_ortho(bpy.types.Operator):
    """Align the view under the mouse to an axis, in orthographic projection"""
    bl_idname = "blaya.view_ortho"
    bl_label = "Orthographic View"

    axis: EnumProperty(name="Axis", items=AXES)

    @classmethod
    def poll(cls, context):
        return _in_view3d(context)

    def execute(self, context):
        bpy.ops.view3d.view_axis(type=self.axis)
        # Only the pane under the mouse; other 3D views keep their projection.
        if context.region_data is not None:
            context.region_data.view_perspective = 'ORTHO'
        show_view_name(context, _AXIS_LABELS[self.axis], VIEW_AXIS[self.axis])
        return {'FINISHED'}


class BLAYA_OT_view_persp_toggle(bpy.types.Operator):
    """Toggle the view under the mouse between perspective and orthographic, and show which one it is"""
    bl_idname = "blaya.view_persp_toggle"
    bl_label = "Perspective / Orthographic"

    @classmethod
    def poll(cls, context):
        return _in_view3d(context) and context.region_data is not None

    def execute(self, context):
        bpy.ops.view3d.view_persportho()
        persp = context.region_data.view_perspective
        show_view_name(context, "Orthographic" if persp == 'ORTHO' else
                       "Camera" if persp == 'CAMERA' else "Perspective")
        return {'FINISHED'}


class BLAYA_OT_quad_toggle(bpy.types.Operator):
    """Toggle Quad View. Leaving Quad View maximizes the pane under the mouse, like Maya"""
    bl_idname = "blaya.quad_toggle"
    bl_label = "Toggle Quad View"

    @classmethod
    def poll(cls, context):
        return _in_view3d(context)

    def execute(self, context):
        space = context.space_data
        if not space.region_quadviews:
            bpy.ops.screen.region_quadview()
            return {'FINISHED'}

        src = context.region_data  # the quad pane under the mouse
        saved = None
        if src is not None:
            saved = (src.view_perspective, src.view_rotation.copy(),
                     src.view_location.copy(), src.view_distance)
        bpy.ops.screen.region_quadview()
        dst = space.region_3d
        if saved is not None and dst is not None:
            dst.view_perspective, dst.view_rotation, dst.view_location, dst.view_distance = saved
        return {'FINISHED'}


class BLAYA_OT_space(bpy.types.Operator):
    """Tap: toggle perspective/orthographic (or Quad View, see preferences). Hold: view pie menu.
    Always consumes the Space press, so it never falls through to animation playback"""
    bl_idname = "blaya.space"
    bl_label = "Persp/Ortho / View Pie"

    @classmethod
    def poll(cls, context):
        return _in_view3d(context)

    def invoke(self, context, event):
        prefs = _prefs(context)
        self._key = event.type
        self._start = time.monotonic()
        self._hold = prefs.pie_delay
        self._tap = prefs.space_tap
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)  # fine ticks: pie opens right at the delay
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _stop(self, context):
        context.window_manager.event_timer_remove(self._timer)

    def modal(self, context, event):
        elapsed = time.monotonic() - self._start
        if event.type == self._key:
            if event.value == 'RELEASE':
                self._stop(context)
                if elapsed < self._hold:
                    if self._tap == 'QUAD':
                        bpy.ops.blaya.quad_toggle()
                    else:
                        bpy.ops.view3d.view_persportho()
                return {'FINISHED'}
            return {'RUNNING_MODAL'}  # key repeat while held
        if event.type == 'TIMER':
            if elapsed >= self._hold:
                self._stop(context)
                bpy.ops.wm.call_menu_pie('INVOKE_DEFAULT', name=VIEW_PIE)
                return {'FINISHED'}
            return {'PASS_THROUGH'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}


_classes = (BLAYA_OT_view_ortho, BLAYA_OT_view_persp_toggle, BLAYA_OT_quad_toggle, BLAYA_OT_space)


def register():
    global _toast_handle
    for cls in _classes:
        bpy.utils.register_class(cls)
    _toast_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_toast, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _toast_handle
    if _toast_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_toast_handle, 'WINDOW')
        _toast_handle = None
    if bpy.app.timers.is_registered(_toast_tick):
        bpy.app.timers.unregister(_toast_tick)
    _toast["text"] = ""
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
