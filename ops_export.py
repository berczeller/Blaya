# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unity Export: one FBX per export root, from the Ctrl+S pie and the sidebar (Blaya tab).

A root is an Empty (exports what is parented under it, not the Empty itself), a mesh (exports itself and
its children, for collision, shadow proxy or guide meshes kept as their own file) or a collection (exports
its objects). The file is named after the root.

Each root remembers the folder, the scale settings and the object names of its first export. Later exports
go to the same folder at the same size, even if the preferences change, and renamed objects (which break
the references Unity keeps to them) are reported. Nothing is ever renamed for you.

Everything the export changes in the scene (the root moved to 0,0,0, Smooth Preview modifiers turned off,
temporary merged meshes) is put back afterwards, even when the export fails.
"""

import os
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty, CollectionProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from . import ops_mesh, ops_uvisland
from .ops_empty import empty_name, group_empty, natural_key

PATH_KEY = "blaya_export_path"              # on the root: the folder of its first export
SCALE_KEY = "blaya_export_scale"            # on the root: Apply Scalings of its first export
BAKE_KEY = "blaya_export_apply_transform"   # on the root: Apply Transform of its first export
NAMES_KEY = "blaya_export_names"            # on the root: the object names written to the FBX last time
MEMORY_KEYS = (PATH_KEY, SCALE_KEY, BAKE_KEY, NAMES_KEY)

EXPORT_TYPES = {'MESH', 'EMPTY'}
_LOD_PREFIX = re.compile(r"^(.*?_LOD\d+)")            # uppercase only: the case Unity's importer recognises
_LOD_UPPER = re.compile(r"_LOD\d+")
_LOD_ANY = re.compile(r"_lod\d+", re.IGNORECASE)
_DUP_RE = re.compile(r"\.\d{3,}$")
_BAD_FILE_CHARS = re.compile(r'[<>:"/\\|?*]')
_PREVIEW_MODS = {ops_mesh.PREVIEW_NAME, ops_mesh.SHADING_NAME}

SCALE_ITEMS = (
    ('FBX_SCALE_ALL', "FBX All", "Unity imports at Scale Factor 1"),
    ('FBX_SCALE_UNITS', "FBX Units Scale", "Unity converts the file's units (a Scale Factor of 0.01 is common)"),
)


def _prefs(context=None):
    return (context or bpy.context).preferences.addons[__package__].preferences


# --------------------------------------------------------------------------- data

class BlayaExportPreset(PropertyGroup):
    """A named export folder (stored in the preferences, so every .blend can use it)."""
    name: StringProperty(name="Name", default="Preset")
    path: StringProperty(name="Folder", default="", subtype='DIR_PATH')


class BlayaExportRoot(PropertyGroup):
    """One entry of the export list: an object or a collection. Pointers follow renames."""
    obj: PointerProperty(type=bpy.types.Object)
    coll: PointerProperty(type=bpy.types.Collection)


def root_id(item):
    return item.obj or item.coll


def is_valid(scene, item):
    """The root still exists in this scene (deleted objects can linger in the file, unlinked)."""
    if item.obj is not None:
        return scene.objects.get(item.obj.name) == item.obj
    if item.coll is not None:
        return item.coll in scene.collection.children_recursive
    return False


def root_for(obj):
    """The root an object belongs to: its Set Empty group, otherwise the top of its parent chain."""
    group = group_empty(obj)
    if group is not None:
        return group
    while obj.parent is not None:
        obj = obj.parent
    return obj


def find_item(scene, idb):
    for i, item in enumerate(scene.blaya_export_roots):
        if root_id(item) == idb:
            return i
    return -1


def add_root(scene, idb):
    if find_item(scene, idb) >= 0:
        return False
    item = scene.blaya_export_roots.add()
    if isinstance(idb, bpy.types.Collection):
        item.coll = idb
    else:
        item.obj = idb
    return True


def replace_root(old_obj, new_coll):
    """Empty to Collection: the collection takes the Empty's place in every export list, with its memory."""
    for scene in bpy.data.scenes:
        for item in scene.blaya_export_roots:
            if item.obj == old_obj:
                item.obj = None
                item.coll = new_coll
                for key in MEMORY_KEYS:
                    if key in old_obj:
                        new_coll[key] = old_obj[key]


def members(root, view_layer):
    """What the root's FBX holds: meshes, and the Empties between them and the root (to keep the
    hierarchy and the pivots of moving parts). Objects with Disable in Renders on are helpers and stay out."""
    if isinstance(root, bpy.types.Collection):
        objs = list(root.all_objects)
    elif root.type == 'EMPTY':
        objs = list(root.children_recursive)
    else:
        objs = [root] + list(root.children_recursive)
    in_layer = {o.name for o in view_layer.objects}
    keep = [o for o in objs if o.name in in_layer and not o.hide_render and o.type in EXPORT_TYPES]
    kept = set(keep)
    needed = set()
    for o in keep:
        if o.type == 'MESH':
            p = o.parent
            while p is not None and p != root:
                if p in kept:
                    needed.add(p)
                p = p.parent
    return [o for o in keep if o.type == 'MESH' or o in needed], objs


def _has_rig_or_animation(root, objs):
    for o in ([root] if isinstance(root, bpy.types.Object) else []) + objs:
        if o.type == 'ARMATURE':
            return True
        ad = o.animation_data
        if ad is not None and (ad.action is not None or len(ad.nla_tracks)):
            return True
    return False


def settings_for(root, prefs):
    """The root's remembered scale settings, or the preferences' for a root never exported."""
    scale = root.get(SCALE_KEY) or prefs.unity_apply_scale
    bake = bool(root[BAKE_KEY]) if BAKE_KEY in root else prefs.unity_apply_transform
    return scale, bake


# --------------------------------------------------------------------------- checks

def _is_identity(matrix, eps=1e-5):
    _loc, rot, scale = matrix.decompose()
    return rot.angle < eps and (scale - scale.__class__((1.0, 1.0, 1.0))).length < eps


def check(scene, root, objs, export_names):
    """Warnings about things that come out wrong in Unity. Nothing is changed."""
    out = []
    us = scene.unit_settings
    if us.system != 'METRIC' or abs(us.scale_length - 1.0) > 1e-6:
        out.append("Scene units are not metres at Unit Scale 1, so sizes in Unity won't match Blender")
    if isinstance(root, bpy.types.Object) and root.type == 'EMPTY' and not _is_identity(root.matrix_world):
        out.append(f"{root.name} has rotation or scale; Move to 0,0,0 only moves its position")
    names = [o.name for o in objs]
    lower = [n for n in names if _LOD_ANY.search(n) and not _LOD_UPPER.search(n)]
    if lower:
        out.append("Lowercase _lod, Unity makes no LOD Group: " + ", ".join(lower))
    dup = [n for n in names if _DUP_RE.search(n)]
    if dup:
        out.append("Names with a .001 suffix: " + ", ".join(dup))
    flipped, unapplied = [], []
    for o in objs:
        if o.type != 'MESH':
            continue
        _loc, rot, scale = o.matrix_basis.decompose()
        if any(abs(s) < 1e-8 for s in scale) or scale.x * scale.y * scale.z < 0:
            flipped.append(o.name)
        elif not o.children and (rot.angle > 1e-5 or (scale - scale.__class__((1, 1, 1))).length > 1e-5):
            unapplied.append(o.name)
    if flipped:
        out.append("Zero or negative scale: " + ", ".join(flipped))
    if unapplied:
        out.append("Rotation or scale not applied (Ctrl+A): " + ", ".join(unapplied))
    # Materials: no .001 copies, no name shared with an object or mesh, the same slots on every LOD.
    taken = set(names) | {o.data.name for o in objs if o.type == 'MESH'}
    slots = {}
    bad_mat = set()
    for o in sorted((o for o in objs if o.type == 'MESH'), key=lambda o: natural_key(o.name)):
        mats = [s.material.name for s in o.material_slots if s.material is not None]
        for m in mats:
            if _DUP_RE.search(m) or m in taken:
                bad_mat.add(m)
        lod = _LOD_PREFIX.match(o.name)
        if lod:
            level = slots.setdefault(lod.group(1), [])
            level.extend(m for m in mats if m not in level)
    if bad_mat:
        out.append("Material names with .001 or shared with an object: " + ", ".join(sorted(bad_mat)))
    bases = {}
    for key, mats in slots.items():
        base, _sep, level = key.rpartition("_LOD")
        bases.setdefault(base, {})[int(level)] = mats
    for base, levels in bases.items():
        if 0 in levels:
            differ = [f"{base}_LOD{n}" for n, mats in sorted(levels.items()) if n and mats != levels[0]]
            if differ:
                out.append("Material slots differ from LOD0: " + ", ".join(differ))
    before = root.get(NAMES_KEY)
    if before is not None:
        old, new = set(before.split("\n")) - {""}, set(export_names)
        if old != new:
            parts = []
            if new - old:
                parts.append("new " + ", ".join(sorted(new - old)))
            if old - new:
                parts.append("gone " + ", ".join(sorted(old - new)))
            out.append("Names changed since the last export (Unity loses its references): " + "; ".join(parts))
    return out


# --------------------------------------------------------------------------- export

def _alive(idb):
    try:
        idb.name
        return True
    except ReferenceError:
        return False


class _Restore:
    """Everything an export changes, put back by restore() whatever happened."""

    def __init__(self):
        self.mods = []      # (modifier, show_viewport, show_render)
        self.moves = []     # (object, matrix_world)
        self.names = []     # (object, name)
        self.temp = []      # temporary objects
        self.meshes = []    # temporary meshes

    def restore(self):
        for obj in self.temp:
            if _alive(obj):
                bpy.data.objects.remove(obj)
        for me in self.meshes:
            if _alive(me) and me.users == 0:
                bpy.data.meshes.remove(me)
        for obj, name in reversed(self.names):
            if _alive(obj):
                obj.name = name
        for obj, mw in reversed(self.moves):
            if _alive(obj):
                obj.matrix_world = mw
        for mod, vp, rd in self.mods:
            try:
                mod.show_viewport, mod.show_render = vp, rd
            except ReferenceError:
                pass


def _hide_previews(objs, rs):
    """Blaya's Smooth Preview subdivides for render too; the FBX would get the subdivided mesh."""
    for o in objs:
        if o.type != 'MESH':
            continue
        for mod in o.modifiers:
            if mod.name in _PREVIEW_MODS:
                rs.mods.append((mod, mod.show_viewport, mod.show_render))
                mod.show_viewport = mod.show_render = False


def _merge(context, root, objs, rs):
    """Join the meshes of each LOD level into one object named after it (Chair_LOD0_seat + Chair_LOD0_legs
    -> Chair_LOD0). Parts without an LOD suffix join into one named after the root. Objects with children
    (moving parts and their hinges) and objects deeper in the hierarchy stay as they are."""
    if not isinstance(root, bpy.types.Object) or root.type != 'EMPTY':
        return objs
    base = empty_name(root.name)
    groups = {}
    for o in objs:
        if o.type == 'MESH' and o.parent == root and not o.children:
            m = _LOD_PREFIX.match(o.name)
            groups.setdefault(m.group(1) if m else base, []).append(o)
    groups = {k: sorted(v, key=lambda o: natural_key(o.name)) for k, v in groups.items() if len(v) > 1}
    if not groups:
        return objs
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    merged, dropped = [], set()
    for name, parts in groups.items():
        temps = []
        for o in parts:
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            rs.meshes.append(me)
            t = bpy.data.objects.new("blaya_export_merge", me)
            rs.temp.append(t)
            context.scene.collection.objects.link(t)
            t.matrix_world = o.matrix_world.copy()
            temps.append(t)
        with context.temp_override(active_object=temps[0], object=temps[0], selected_objects=temps,
                                   selected_editable_objects=temps):
            bpy.ops.object.join()
        joined = temps[0]
        holder = bpy.data.objects.get(name)
        if holder is not None and holder != joined:   # the name is taken (by a part or the root itself)
            rs.names.append((holder, holder.name))
            holder.name = name + ".blaya_export"
        joined.name = name
        merged.append(joined)
        dropped.update(parts)
    return [o for o in objs if o not in dropped] + merged


def _file_path(root, scene):
    folder = root.get(PATH_KEY) or scene.blaya_export_folder
    if not folder:
        return None, None, "no export folder set"
    if folder.startswith("//") and not bpy.data.filepath:
        return None, None, "the folder is relative to the .blend, which isn't saved yet"
    absolute = os.path.normpath(bpy.path.abspath(folder))
    return folder, os.path.join(absolute, _BAD_FILE_CHARS.sub("_", root.name) + ".fbx"), None


def export_root(context, root, move_origin, merge):
    """Export one root. Returns (file path or None, warnings, error or None)."""
    scene = context.scene
    prefs = _prefs(context)
    objs, everything = members(root, context.view_layer)
    if _has_rig_or_animation(root, everything):
        return None, [], "has a rig or animation; export it with your animation setup"
    if not any(o.type == 'MESH' for o in objs):
        return None, [], "no meshes to export"
    folder, path, error = _file_path(root, scene)
    if error:
        return None, [], error
    if os.path.exists(path) and not os.access(path, os.W_OK):
        return None, [], f"{os.path.basename(path)} is read-only (check it out first)"
    scale, bake = settings_for(root, prefs)
    rs = _Restore()
    try:
        _hide_previews(objs, rs)
        if move_origin and isinstance(root, bpy.types.Object):
            mw = root.matrix_world.copy()
            rs.moves.append((root, mw))
            moved = mw.copy()
            moved.translation = (0.0, 0.0, 0.0)
            root.matrix_world = moved
        source = objs
        if merge:
            objs = _merge(context, root, objs, rs)
        context.view_layer.update()
        export_names = sorted(o.name for o in objs)
        warnings = check(scene, root, source, export_names)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with context.temp_override(selected_objects=objs):
            bpy.ops.export_scene.fbx(
                filepath=path, check_existing=False, use_selection=True, use_visible=False,
                use_active_collection=False, global_scale=1.0, apply_unit_scale=True, apply_scale_options=scale,
                use_space_transform=True, bake_space_transform=bake, object_types=EXPORT_TYPES,
                use_mesh_modifiers=True, use_mesh_modifiers_render=True, mesh_smooth_type='FACE',
                use_subsurf=False, use_mesh_edges=False, use_tspace=prefs.unity_tangents,
                use_triangles=prefs.unity_triangulate, use_custom_props=False, add_leaf_bones=False,
                bake_anim=False, path_mode='AUTO', embed_textures=False, batch_mode='OFF',
                axis_forward='-Z', axis_up='Y')
    except (RuntimeError, OSError) as exc:
        return None, [], str(exc).strip().splitlines()[-1]
    finally:
        rs.restore()
        context.view_layer.update()
    root[PATH_KEY] = folder
    root[SCALE_KEY] = scale
    root[BAKE_KEY] = int(bake)
    root[NAMES_KEY] = "\n".join(export_names)
    return path, warnings, None


def _popup(context, title, lines, icon):
    if context.window_manager is None or context.window is None or not lines:
        return

    def draw(menu, _context):
        for line in lines:
            menu.layout.label(text=line)
    context.window_manager.popup_menu(draw, title=title, icon=icon)


class BLAYA_OT_export_unity(Operator):
    """Export each root of the export list to its own FBX, set up for Unity"""
    bl_idname = "blaya.export_unity"
    bl_label = "Unity Export"
    # UNDO: the export joins temporary meshes; without its own undo step, Ctrl+Z would land on that join.
    bl_options = {'UNDO'}

    mode: EnumProperty(items=(
        ('ALL', "All", "Every root in the list"),
        ('SELECTED', "Selected", "The roots of the selected objects"),
        ('ACTIVE', "Active", "The root highlighted in the list"),
    ), default='ALL')

    @classmethod
    def description(cls, context, properties):
        return {
            'ALL': "Export every root in the export list to its own FBX, set up for Unity",
            'SELECTED': "Export the roots that hold the selected objects",
            'ACTIVE': "Export the root highlighted in the list",
        }[properties.mode]

    @classmethod
    def poll(cls, context):
        return context.scene is not None and len(context.scene.blaya_export_roots) > 0

    def _roots(self, context):
        scene = context.scene
        items = [it for it in scene.blaya_export_roots if is_valid(scene, it)]
        if self.mode == 'ACTIVE':
            i = scene.blaya_export_index
            if 0 <= i < len(scene.blaya_export_roots) and is_valid(scene, scene.blaya_export_roots[i]):
                return [root_id(scene.blaya_export_roots[i])]
            return []
        roots = [root_id(it) for it in items]
        if self.mode == 'SELECTED':
            sel = set(context.selected_objects)
            roots = [r for r in roots if r in sel or sel & set(members(r, context.view_layer)[1])]
        return roots

    def execute(self, context):
        scene = context.scene
        roots = self._roots(context)
        if not roots:
            self.report({'WARNING'}, "Nothing to export: add roots to the export list (or select one)")
            return {'CANCELLED'}
        wm = context.window_manager
        active = context.view_layer.objects.active
        mode = active.mode if active is not None else 'OBJECT'
        island = bool(getattr(wm, "blaya_uv_island", False))
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')   # Edit Mode changes only reach the mesh on leaving it
        done, lines, failed = [], [], 0
        try:
            for root in roots:
                path, warnings, error = export_root(context, root, scene.blaya_export_move_origin,
                                                    scene.blaya_export_merge)
                if error:
                    failed += 1
                    lines.append(f"{root.name}: not exported, {error}")
                    continue
                done.append(path)
                lines.extend(f"{root.name}: {w}" for w in warnings)
        finally:
            if mode != 'OBJECT' and active is not None and _alive(active):
                try:
                    bpy.ops.object.mode_set(mode=mode)
                except RuntimeError:
                    pass
                if island and mode == 'EDIT' and not wm.blaya_uv_island:
                    ops_uvisland.enter(context)
        for line in lines:
            print("Blaya Unity Export:", line)
        folders = sorted({os.path.dirname(p) for p in done})
        msg = f"Exported {len(done)} FBX file{'s' if len(done) != 1 else ''}"
        if len(folders) == 1:
            msg += f" to {folders[0]}"
        if failed or lines:
            self.report({'WARNING'}, msg + f", {len(lines)} note{'s' if len(lines) != 1 else ''} (see popup)")
            _popup(context, msg, lines, 'ERROR' if failed else 'INFO')
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'} if done else {'CANCELLED'}


# --------------------------------------------------------------------------- list editing

class BLAYA_OT_export_root_add(Operator):
    """Add the roots of the selected objects to the export list: their Set Empty group or the top of their
    parent chain. A selected Empty is added itself. With nothing selected, the active collection is added"""
    bl_idname = "blaya.export_root_add"
    bl_label = "Add Export Root"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        roots = []
        for o in context.selected_objects:
            r = o if o.type == 'EMPTY' else root_for(o)
            if r not in roots:
                roots.append(r)
        if not roots:
            coll = context.collection
            if coll is None or coll == scene.collection:
                self.report({'WARNING'}, "Select objects, or make a collection active, to add a root")
                return {'CANCELLED'}
            roots = [coll]
        added = [r.name for r in roots if add_root(scene, r)]
        if added:
            scene.blaya_export_index = len(scene.blaya_export_roots) - 1
            self.report({'INFO'}, "Added: " + ", ".join(added))
        else:
            self.report({'INFO'}, "Already in the export list")
        return {'FINISHED'}


class BLAYA_OT_export_root_remove(Operator):
    """Remove the highlighted root from the export list (the object and its files are left alone)"""
    bl_idname = "blaya.export_root_remove"
    bl_label = "Remove Export Root"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return scene is not None and 0 <= scene.blaya_export_index < len(scene.blaya_export_roots)

    def execute(self, context):
        scene = context.scene
        scene.blaya_export_roots.remove(scene.blaya_export_index)
        scene.blaya_export_index = min(scene.blaya_export_index, len(scene.blaya_export_roots) - 1)
        return {'FINISHED'}


class BLAYA_OT_export_root_select(Operator):
    """Select the highlighted root and everything it exports"""
    bl_idname = "blaya.export_root_select"
    bl_label = "Select Export Root"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return BLAYA_OT_export_root_remove.poll(context) and context.mode == 'OBJECT'

    def execute(self, context):
        scene = context.scene
        item = scene.blaya_export_roots[scene.blaya_export_index]
        if not is_valid(scene, item):
            self.report({'WARNING'}, "That root is no longer in the scene")
            return {'CANCELLED'}
        root = root_id(item)
        objs, _all = members(root, context.view_layer)
        for o in context.selected_objects:
            o.select_set(False)
        for o in objs + ([root] if isinstance(root, bpy.types.Object) else []):
            if o.visible_get():
                o.select_set(True)
        if isinstance(root, bpy.types.Object) and root.visible_get():
            context.view_layer.objects.active = root
        return {'FINISHED'}


class BLAYA_OT_export_root_forget(Operator):
    """Forget the highlighted root's folder, scale settings and exported names. Its next export uses the
    current folder and preferences, which can change its size and references in Unity"""
    bl_idname = "blaya.export_root_forget"
    bl_label = "Forget Export Settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not BLAYA_OT_export_root_remove.poll(context):
            return False
        idb = root_id(context.scene.blaya_export_roots[context.scene.blaya_export_index])
        return idb is not None and any(k in idb for k in MEMORY_KEYS)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        idb = root_id(context.scene.blaya_export_roots[context.scene.blaya_export_index])
        for key in MEMORY_KEYS:
            if key in idb:
                del idb[key]
        return {'FINISHED'}


class BLAYA_OT_export_open_folder(Operator):
    """Open the export folder of the highlighted root (or the folder for new roots)"""
    bl_idname = "blaya.export_open_folder"
    bl_label = "Open Export Folder"

    def execute(self, context):
        scene = context.scene
        folder = scene.blaya_export_folder
        i = scene.blaya_export_index
        if 0 <= i < len(scene.blaya_export_roots):
            idb = root_id(scene.blaya_export_roots[i])
            if idb is not None and idb.get(PATH_KEY):
                folder = idb[PATH_KEY]
        folder = bpy.path.abspath(folder) if folder else ""
        if not folder or not os.path.isdir(folder):
            self.report({'WARNING'}, "The folder doesn't exist yet")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


# --------------------------------------------------------------------------- presets

class BLAYA_OT_export_preset_use(Operator):
    """Use this preset's folder for roots that haven't been exported yet"""
    bl_idname = "blaya.export_preset_use"
    bl_label = "Use Export Preset"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    @classmethod
    def description(cls, context, properties):
        presets = _prefs(context).unity_presets
        if 0 <= properties.index < len(presets):
            return f"Export new roots to {presets[properties.index].path}"
        return cls.__doc__

    def execute(self, context):
        presets = _prefs(context).unity_presets
        if not 0 <= self.index < len(presets):
            return {'CANCELLED'}
        context.scene.blaya_export_folder = presets[self.index].path
        self.report({'INFO'}, f"New roots export to {presets[self.index].path}")
        return {'FINISHED'}


class BLAYA_OT_export_preset_add(Operator):
    """Save the folder for new roots as a preset"""
    bl_idname = "blaya.export_preset_add"
    bl_label = "Add Export Preset"

    name: StringProperty(name="Name")

    def invoke(self, context, event):
        folder = context.scene.blaya_export_folder.rstrip("\\/")
        self.name = os.path.basename(folder) or "Preset"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        folder = context.scene.blaya_export_folder
        if not folder:
            self.report({'WARNING'}, "Set the folder for new roots first")
            return {'CANCELLED'}
        p = _prefs(context).unity_presets.add()
        p.name, p.path = self.name or "Preset", folder
        context.preferences.is_dirty = True
        return {'FINISHED'}


class BLAYA_OT_export_preset_remove(Operator):
    """Remove this export preset"""
    bl_idname = "blaya.export_preset_remove"
    bl_label = "Remove Export Preset"

    index: IntProperty()

    def execute(self, context):
        presets = _prefs(context).unity_presets
        if 0 <= self.index < len(presets):
            presets.remove(self.index)
            context.preferences.is_dirty = True
        return {'FINISHED'}


class BLAYA_MT_export_presets(Menu):
    bl_idname = "BLAYA_MT_export_presets"
    bl_label = "Export Folder Presets"

    def draw(self, context):
        layout = self.layout
        presets = _prefs(context).unity_presets
        for i, p in enumerate(presets):
            layout.operator("blaya.export_preset_use", text=p.name, icon='FILE_FOLDER').index = i
        if presets:
            layout.separator()
        layout.operator("blaya.export_preset_add", text="Save Current Folder as Preset", icon='ADD')


# --------------------------------------------------------------------------- UI

class BLAYA_UL_export_roots(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        idb = root_id(item)
        if idb is None or not is_valid(context.scene, item):
            layout.label(text=(idb.name if idb is not None else "?") + " [Missing]", icon='ERROR')
            return
        if item.coll is not None:
            icon = 'OUTLINER_COLLECTION'
        else:
            icon = 'EMPTY_AXIS' if idb.type == 'EMPTY' else 'MESH_DATA'
        row = layout.row(align=True)
        row.label(text=idb.name, icon=icon)
        if PATH_KEY in idb:
            row.label(text="", icon='LOCKED')


def _draw_panel(layout, context):
    scene = context.scene
    row = layout.row()
    row.template_list("BLAYA_UL_export_roots", "", scene, "blaya_export_roots", scene, "blaya_export_index",
                      rows=4)
    side = row.column(align=True)
    side.operator("blaya.export_root_add", text="", icon='ADD')
    side.operator("blaya.export_root_remove", text="", icon='REMOVE')
    side.separator()
    side.operator("blaya.export_root_select", text="", icon='RESTRICT_SELECT_OFF')
    side.operator("blaya.export_root_forget", text="", icon='UNLOCKED')

    i = scene.blaya_export_index
    if 0 <= i < len(scene.blaya_export_roots):
        idb = root_id(scene.blaya_export_roots[i])
        if idb is not None and PATH_KEY in idb:
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"{idb.name}: exported before, settings kept", icon='LOCKED')
            col.prop(idb, f'["{PATH_KEY}"]', text="Folder")
            scale = {k: n for k, n, _d in SCALE_ITEMS}.get(idb.get(SCALE_KEY), "?")
            col.label(text=f"{scale}, Apply Transform {'on' if idb.get(BAKE_KEY) else 'off'}")

    col = layout.column(align=True)
    col.label(text="Folder for new roots:")
    row = col.row(align=True)
    row.prop(scene, "blaya_export_folder", text="")
    row.menu("BLAYA_MT_export_presets", text="", icon='PRESET')
    col = layout.column(align=True)
    col.prop(scene, "blaya_export_move_origin")
    col.prop(scene, "blaya_export_merge")

    col = layout.column(align=True)
    row = col.row(align=True)
    row.scale_y = 1.3
    row.operator("blaya.export_unity", text="All", icon='EXPORT').mode = 'ALL'
    row.operator("blaya.export_unity", text="Active").mode = 'ACTIVE'
    row.operator("blaya.export_unity", text="Selected").mode = 'SELECTED'
    col.operator("blaya.export_open_folder", icon='FOLDER_REDIRECT')


class VIEW3D_PT_blaya_export(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Blaya"
    bl_label = "Unity Export"
    bl_ui_units_x = 16   # width when opened from the pie's Manage button

    def draw(self, context):
        _draw_panel(self.layout, context)


def draw_pie_box(pie, context):
    """The Unity Export box in the Ctrl+S pie: one-click actions; the list itself lives in the panel."""
    scene = context.scene
    n = sum(1 for it in scene.blaya_export_roots if is_valid(scene, it))
    box = pie.box()
    box.ui_units_x = 11   # pie slots size to their content; without this the labels get cut
    col = box.column(align=True)
    col.label(text="Unity Export", icon='EXPORT')
    row = col.row(align=True)
    row.scale_y = 1.2
    row.operator("blaya.export_unity", text=f"Export All ({n})", icon='EXPORT').mode = 'ALL'
    row.operator("blaya.export_unity", text="Selected").mode = 'SELECTED'
    row = col.row(align=True)
    row.operator("blaya.export_root_add", text="Add", icon='ADD')
    row.menu("BLAYA_MT_export_presets", text="", icon='FILE_FOLDER')
    op = row.operator("wm.call_panel", text="Manage", icon='PREFERENCES')
    op.name = VIEW3D_PT_blaya_export.__name__
    op.keep_open = True


_classes = (BlayaExportRoot, BLAYA_OT_export_unity, BLAYA_OT_export_root_add, BLAYA_OT_export_root_remove,
            BLAYA_OT_export_root_select, BLAYA_OT_export_root_forget, BLAYA_OT_export_open_folder,
            BLAYA_OT_export_preset_use, BLAYA_OT_export_preset_add, BLAYA_OT_export_preset_remove,
            BLAYA_MT_export_presets, BLAYA_UL_export_roots, VIEW3D_PT_blaya_export)


def register():
    # BlayaExportPreset is registered with the preferences, which hold it.
    for cls in _classes:
        bpy.utils.register_class(cls)
    S = bpy.types.Scene
    S.blaya_export_roots = CollectionProperty(type=BlayaExportRoot)
    S.blaya_export_index = IntProperty(default=0)
    S.blaya_export_folder = StringProperty(
        name="Export Folder", subtype='DIR_PATH', default="",
        description="Where roots exported for the first time go. Each root keeps the folder of its first "
                    "export. Start with // for a folder relative to the .blend")
    S.blaya_export_move_origin = BoolProperty(
        name="Move to 0,0,0", default=True,
        description="Export each root as if it stood at the world origin (it is put back afterwards)")
    S.blaya_export_merge = BoolProperty(
        name="Merge per LOD", default=False,
        description="Join the meshes of each LOD level into one (Chair_LOD0_seat + Chair_LOD0_legs -> "
                    "Chair_LOD0). Objects with children, like moving parts, stay separate")


def unregister():
    S = bpy.types.Scene
    for name in ("blaya_export_merge", "blaya_export_move_origin", "blaya_export_folder", "blaya_export_index",
                 "blaya_export_roots"):
        delattr(S, name)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
