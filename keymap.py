# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blaya keymap = the current Blender default keymap + the changes in ``keymap_patch.py``.

Building on Blender's own default (instead of shipping a frozen copy of a whole keymap) keeps
new Blender shortcuts working after upgrades; only the Maya-style changes are layered on top.

This file is loaded by file path from the "Blaya" keyconfig preset, so it must not use
relative imports of the add-on package.
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))

_MOD_KEYS = ("shift", "ctrl", "alt", "oskey", "hyper")


def _mod_value(v):
    # Keymap modifiers can be True/False, 1/0 or -1 (KM_ANY).
    if v == -1:
        return -1
    return 1 if v else 0


def event_sig(ev):
    """What makes two keymap items fire on the same input."""
    any_ = bool(ev.get("any", False))
    mods = tuple(-1 if any_ else _mod_value(ev.get(k, False)) for k in _MOD_KEYS)
    return (ev.get("type"), ev.get("value"), mods,
            ev.get("key_modifier", 'NONE') or 'NONE', ev.get("direction", 'ANY') or 'ANY')


def _load_sibling(filename, modname):
    spec = importlib.util.spec_from_file_location(modname, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_keyconfig_data():
    """Blender's default keymap for the running version, with default preferences."""
    import bpy
    blender_preset = bpy.utils.preset_find("Blender", "keyconfig")
    default = bpy.utils.execfile(os.path.join(os.path.dirname(blender_preset), "keymap_data", "blender_default.py"))
    inputs = bpy.context.preferences.inputs
    params = default.Params(
        select_mouse='LEFT',
        use_mouse_emulate_3_button=(inputs.use_mouse_emulate_3_button
                                    and inputs.mouse_emulate_3_button_modifier == 'ALT'),
        spacebar_action='PLAY',
        use_gizmo_drag=True,
        use_fallback_tool=True,
        use_alt_navigation=True,
    )
    return default.generate_keymaps(params)


def apply_patch(data, add, remove):
    """Remove listed items and anything sharing an input with an added item, then add the new items first."""
    for name, _params, content in data:
        items = content.get("items")
        if items is None:
            continue
        # Held-key combos (D+V) first, since a plain V item also fires while D is held; then
        # exact-modifier items before "any modifier" ones on the same key, so e.g. plain 1 reaches
        # smooth preview before the any+1 collection toggle.
        new = sorted(add.get(name, ()), key=lambda it: (not it[1].get("key_modifier"),
                                                        bool(it[1].get("any", False))))
        drop = {(idname, event_sig(ev)) for idname, ev in remove.get(name, ())}
        if not new and not drop:
            continue
        new_sigs = {event_sig(it[1]) for it in new}
        items[:] = [it for it in items
                    if event_sig(it[1]) not in new_sigs and (it[0], event_sig(it[1])) not in drop]
        items[:0] = list(new)
    return data


def apply_insert(data, insert):
    """Put items first in a keymap WITHOUT removing Blender's items on the same input.

    Used for keymaps shared by several editors (e.g. "Frames"): our item only polls true in its own
    editor, and everywhere else Blender falls through to the next item (the original binding).
    """
    for name, _params, content in data:
        items = content.get("items")
        if items is not None and name in insert:
            items[:0] = list(insert[name])
    return data


def build():
    patch = _load_sibling("keymap_patch.py", "blaya_keymap_patch")
    data = apply_patch(default_keyconfig_data(), patch.KEYMAP_ADD, patch.KEYMAP_REMOVE)
    return apply_insert(data, getattr(patch, "KEYMAP_INSERT", {}))


def load(name="Blaya"):
    import bpy
    from bl_keymap_utils.io import keyconfig_init_from_data
    kc = bpy.context.window_manager.keyconfigs.new(name)
    keyconfig_init_from_data(kc, build())
