# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Axis indicator presets for the top-right corner of the 3D View.

These set Blender's own options (Preferences > Viewport > Navigation Controls): the interactive
"Navigation Gizmo" or the "Simple Axes", at sizes Blaya presets. "Blender Default" is applied when
Blaya is enabled; "Don't Change" restores whatever Blender was set to before Blaya changed it.
"""

import bpy

STYLE_ITEMS = (
    ('KEEP', "Don't Change", "Leave Blender's axis indicator as configured in Preferences > Viewport"),
    ('BLENDER', "Blender Default", "Blender 5.3's interactive navigation gizmo at its default size (clickable)"),
    ('GIZMO_LARGE', "Large Gizmo", "Blender's interactive navigation gizmo, larger (clickable)"),
    ('AXES_THIN', "Simple Axes", "Blender's thin simple axes"),
    ('AXES_BOLD', "Bold Simple Axes", "Blender's simple axes at the biggest size and full brightness"),
)
DEFAULT_STYLE = 'BLENDER'

# (mini_axis_type, mini_axis_size, mini_axis_brightness, gizmo_size_navigate_v3d) applied for each style.
STYLE_SETTINGS = {
    'BLENDER': ('GIZMO', 25, 8, 80),
    'GIZMO_LARGE': ('GIZMO', 25, 8, 130),
    'AXES_THIN': ('MINIMAL', 25, 8, 80),
    'AXES_BOLD': ('MINIMAL', 64, 10, 80),
}


def _prefs(context):
    return context.preferences.addons[__package__].preferences


def _snapshot(view):
    return f"{view.mini_axis_type},{view.mini_axis_size},{view.mini_axis_brightness},{view.gizmo_size_navigate_v3d}"


def _restore(view, text):
    try:
        kind, size, bright, giz = text.split(",")
        if kind not in {'NONE', 'MINIMAL', 'GIZMO'}:
            return
        view.mini_axis_type = kind
        view.mini_axis_size = int(size)
        view.mini_axis_brightness = int(bright)
        view.gizmo_size_navigate_v3d = int(giz)
    except (ValueError, TypeError):
        pass


def apply_style(prefs, context):
    """Set Blender's indicator for the chosen style (also the preference's update callback)."""
    view = context.preferences.view
    style = prefs.axis_indicator
    if style == 'KEEP':
        if prefs.axis_restore:
            _restore(view, prefs.axis_restore)
            prefs.axis_restore = ""
    else:
        if not prefs.axis_restore:
            prefs.axis_restore = _snapshot(view)  # what to go back to with "Don't Change"
        kind, size, bright, giz = STYLE_SETTINGS[style]
        view.mini_axis_type = kind
        view.mini_axis_size = size
        view.mini_axis_brightness = bright
        view.gizmo_size_navigate_v3d = giz
    wm = context.window_manager
    for win in wm.windows if wm else ():
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _apply_on_enable():
    """When Blaya is enabled (or Blender starts), make sure the chosen preset is in effect."""
    try:
        prefs = _prefs(bpy.context)
    except KeyError:
        return None
    if prefs.axis_indicator not in STYLE_SETTINGS and prefs.axis_indicator != 'KEEP':
        prefs.axis_indicator = DEFAULT_STYLE  # e.g. a style removed in a newer Blaya
    if prefs.axis_indicator != 'KEEP':
        apply_style(prefs, bpy.context)
    return None


def register():
    # Preferences aren't writable while add-ons register; apply right after.
    bpy.app.timers.register(_apply_on_enable, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_apply_on_enable):
        bpy.app.timers.unregister(_apply_on_enable)
