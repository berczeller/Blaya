# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save pie (Ctrl+S) and Auto Save.

The pie gathers file tasks in one place: open / save / save as / incremental save, the previous and next
.blend in the same folder, the most recent file, the current and temp folders, revert, auto save,
import / export, append / link, purge and "clean out the .blend". In the Image Editor its top slots
switch to image open / save / pack.

Auto Save keeps timed copies of the open file in their own folder (a "Blaya Autosave" folder in the
temp directory unless another folder is set), only when something changed, and keeps the newest N
copies of each project.
"""

import os
import re
import tempfile
import time

import blf
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator

AUTOSAVE_FOLDER_NAME = "Blaya Autosave"
AUTOSAVE_TOAST_SECONDS = 1.0


def _prefs(context=None):
    return (context or bpy.context).preferences.addons[__package__].preferences


def _dirty_star():
    return "*" if bpy.data.is_dirty else ""


def temp_dir(context=None):
    """Blender's temporary directory (Preferences > File Paths), or the system one."""
    folder = (context or bpy.context).preferences.filepaths.temporary_directory
    return folder if folder and os.path.isdir(folder) else tempfile.gettempdir()


def _op_exists(idname):
    module, name = idname.split(".")
    try:
        getattr(getattr(bpy.ops, module), name).get_rna_type()
        return True
    except (AttributeError, KeyError):
        return False


def _popup(context, title, lines, icon='INFO'):
    def draw(menu, _context):
        for line in lines:
            menu.layout.label(text=line)
    context.window_manager.popup_menu(draw, title=title, icon=icon)


# --------------------------------------------------------------------------- incremental names / sibling files

_INCREMENT_RE = re.compile(r"(.*?)(\d+)$")


def incremented_path(filepath, branch=False):
    """Next incremental file name: trailing digits go up by one keeping their width (foo_009 -> foo_010,
    x_99 -> x_100), otherwise _001 is added. `branch` adds _01 instead (foo_005 -> foo_005_01)."""
    folder, name = os.path.split(filepath)
    m = re.match(r"(.+)\.blend\d*$", name)
    if not m:
        return None
    stem = m.group(1)
    if branch:
        return os.path.join(folder, f"{stem}_01.blend")
    d = _INCREMENT_RE.match(stem)
    if d:
        head, digits = d.groups()
        stem = f"{head}{int(digits) + 1:0{len(digits)}d}"
    else:
        stem = f"{stem}_001"
    return os.path.join(folder, stem + ".blend")


def sibling_file(filepath, direction, backup=False):
    """The previous (-1) or next (+1) .blend in the same folder, in plain name order. With `backup`,
    .blend1 / .blend2 backups count too."""
    if not filepath or not os.path.isfile(filepath):
        return None
    folder, name = os.path.split(filepath)
    files = sorted(f for f in os.listdir(folder) if os.path.splitext(f)[1].startswith(".blend")
                   and os.path.isfile(os.path.join(folder, f)))
    if name not in files:
        return None
    i = files.index(name)
    candidates = files[i + 1:] if direction > 0 else list(reversed(files[:i]))
    for f in candidates:
        if backup or os.path.splitext(f)[1] == ".blend":
            return os.path.join(folder, f)
    return None


def _recent_files():
    path = os.path.join(bpy.utils.user_resource('CONFIG'), "recent-files.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:
        return []


class _ConfirmIfDirty:
    """Ask before throwing away unsaved changes."""
    confirm_text = "The current file has unsaved changes. Continue?"

    def invoke(self, context, event):
        self._event_ctrl, self._event_alt = event.ctrl, event.alt
        if bpy.data.is_dirty:
            return context.window_manager.invoke_confirm(self, event, title=self.confirm_text,
                                                         confirm_text="Continue")
        return self.execute(context)


# --------------------------------------------------------------------------- file operators

class BLAYA_OT_file_new(_ConfirmIfDirty, Operator):
    """Start a new file"""
    bl_idname = "blaya.file_new"
    bl_label = "New"
    confirm_text = "Current file is unsaved. Start a new file anyway?"

    def execute(self, context):
        bpy.ops.wm.read_homefile(load_ui=True)
        return {'FINISHED'}


class BLAYA_OT_file_save(Operator):
    bl_idname = "blaya.file_save"
    bl_label = "Save"

    @classmethod
    def description(cls, context, properties):
        return f"Save {bpy.data.filepath}" if bpy.data.filepath else "Save unsaved file as..."

    def execute(self, context):
        if not bpy.data.filepath:
            bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')
            return {'FINISHED'}
        bpy.ops.wm.save_mainfile()
        self.report({'INFO'}, f"Saved '{os.path.basename(bpy.data.filepath)}'")
        return {'FINISHED'}


class BLAYA_OT_file_save_as(Operator):
    """Save the file under a new name. Alt: save a copy"""
    bl_idname = "blaya.file_save_as"
    bl_label = "Save As"

    def invoke(self, context, event):
        bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', copy=event.alt)
        return {'FINISHED'}

    def execute(self, context):
        bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
        return {'FINISHED'}


class BLAYA_OT_file_save_incremental(Operator):
    bl_idname = "blaya.file_save_incremental"
    bl_label = "Incremental Save"

    branch: BoolProperty(name="Branch", description="Save as <name>_01 instead of the next number",
                         default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if not bpy.data.filepath:
            return "Save unsaved file as..."
        nxt = incremented_path(bpy.data.filepath)
        branch = incremented_path(bpy.data.filepath, branch=True)
        return (f"Save incrementally to {os.path.basename(nxt or '')}\n"
                f"Alt: save to {os.path.basename(branch or '')}")

    def invoke(self, context, event):
        self.branch = event.alt
        return self.execute(context)

    def execute(self, context):
        if not bpy.data.filepath:
            bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')
            return {'FINISHED'}
        target = incremented_path(bpy.data.filepath, branch=self.branch)
        if target is None:
            self.report({'ERROR'}, "This file name can't be incremented")
            return {'CANCELLED'}
        if os.path.exists(target):
            self.report({'ERROR'}, f"File '{target}' exists already! Blend has NOT been saved incrementally!")
            return {'CANCELLED'}
        bpy.ops.wm.save_as_mainfile(filepath=target)  # Blender adds it to the recent files itself
        self.report({'INFO'}, f"Incrementally saved to {os.path.basename(target)}")
        return {'FINISHED'}


class BLAYA_OT_file_load_most_recent(_ConfirmIfDirty, Operator):
    """Open the most recent file"""
    bl_idname = "blaya.file_load_most_recent"
    bl_label = "Most Recent"
    confirm_text = "Load the most recent file? This file has unsaved changes!"

    @classmethod
    def poll(cls, context):
        return bool(_recent_files())

    def execute(self, context):
        recent = _recent_files()
        path = recent[0] if recent else ""
        if not os.path.isfile(path):
            _popup(context, "File not found", [f"File {path} does not exist"], icon='ERROR')
            return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=True)
        return {'FINISHED'}


class BLAYA_OT_file_load_sibling(_ConfirmIfDirty, Operator):
    bl_idname = "blaya.file_load_sibling"
    bl_label = "Load Previous / Next File"

    direction: EnumProperty(items=(('PREVIOUS', "Previous", ""), ('NEXT', "Next", "")), default='NEXT')

    @property
    def confirm_text(self):
        return f"Load {self.direction.lower()} file? File has unsaved Changes!"

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath) and os.path.isfile(bpy.data.filepath)

    @classmethod
    def description(cls, context, properties):
        step = -1 if properties.direction == 'PREVIOUS' else 1
        target = sibling_file(bpy.data.filepath, step)
        name = os.path.basename(target) if target else "none"
        return (f"Load the {properties.direction.lower()} .blend in this folder: {name}\n"
                "Ctrl: include .blend1 backups   Alt: keep the current UI")

    def execute(self, context):
        step = -1 if self.direction == 'PREVIOUS' else 1
        backup = getattr(self, "_event_ctrl", False)
        target = sibling_file(bpy.data.filepath, step, backup=backup)
        if target is None:
            _popup(context, "End of folder reached", [f"There is no {self.direction.lower()} file in this folder"])
            return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=target, load_ui=not getattr(self, "_event_alt", False))
        return {'FINISHED'}


class BLAYA_OT_open_current_dir(Operator):
    """Open the folder of this .blend in the system file browser (Blender's config folder if unsaved)"""
    bl_idname = "blaya.open_current_dir"
    bl_label = "Open Current"

    def execute(self, context):
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else bpy.utils.user_resource('CONFIG')
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


class BLAYA_OT_open_temp_dir(Operator):
    """Pick a .blend in Blender's temporary folder (autosaves, quit.blend) and open it"""
    bl_idname = "blaya.open_temp_dir"
    bl_label = "Open Temp"

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.blend;*.blend1;*.blend2;*.blend3", options={'HIDDEN'})
    load_ui: BoolProperty(name="Load UI", default=True)

    def invoke(self, context, event):
        self.filepath = temp_dir(context) + os.sep
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=self.filepath, load_ui=self.load_ui)
        return {'FINISHED'}


_PURGE_TYPES = (("meshes", "mesh", "meshes"), ("curves", "curve", "curves"), ("objects", "object", "objects"),
                ("materials", "material", "materials"), ("images", "image", "images"),
                ("node_groups", "node group", "node groups"), ("scenes", "scene", "scenes"),
                ("worlds", "world", "worlds"))


class BLAYA_OT_purge_orphans(Operator):
    """Remove unused data and empty collections.
    Alt: recursive (also data that only unused data uses). Shift: Blender's purge dialog"""
    bl_idname = "blaya.purge_orphans"
    bl_label = "Purge"
    bl_options = {'REGISTER', 'UNDO'}

    recursive: BoolProperty(name="Recursive", default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if event.shift:
            bpy.ops.outliner.orphans_purge('INVOKE_DEFAULT')
            return {'FINISHED'}
        self.recursive = event.alt
        return self.execute(context)

    def execute(self, context):
        before = {attr: len(getattr(bpy.data, attr)) for attr, _s, _p in _PURGE_TYPES}
        cols_before = len(bpy.data.collections)
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=self.recursive)
        for col in list(bpy.data.collections):
            if not col.objects and not col.children and col.users == 1 and not col.use_fake_user:
                bpy.data.collections.remove(col)
        removed = {attr: before[attr] - len(getattr(bpy.data, attr)) for attr in before}
        total = sum(removed.values()) + cols_before - len(bpy.data.collections)
        if total:
            lines = [f"Removed {total} data blocks!"]
            lines += [f" • {n} {single if n == 1 else plural}" for (attr, single, plural) in _PURGE_TYPES
                      for n in [removed[attr]] if n]
            _popup(context, "Recursive Purge" if self.recursive else "Purge", lines)
        else:
            self.report({'INFO'}, "Nothing to purge.")
        return {'FINISHED'}


class BLAYA_OT_clean_out_blend(Operator):
    """Remove everything from this .blend except the selected objects (Alt: also custom brushes)"""
    bl_idname = "blaya.clean_out_blend"
    bl_label = "Clean out .blend file!"
    bl_options = {'REGISTER', 'UNDO'}

    remove_brushes: BoolProperty(name="Remove Custom Brushes", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.area is not None and context.area.type == 'VIEW_3D' \
            and bool(bpy.data.objects or bpy.data.materials or bpy.data.images or bpy.data.node_groups)

    def invoke(self, context, event):
        self.remove_brushes = event.alt
        width = 300 + 150 * bool(context.selected_objects) + 150 * self.remove_brushes
        return context.window_manager.invoke_props_dialog(self, width=width, title="Clean out .blend file!",
                                                          confirm_text="Clean out")

    def draw(self, context):
        text = "This will remove everything in the current .blend file"
        if self.remove_brushes:
            text += ", including custom Brushes"
        if context.selected_objects:
            text += ", except the selected objects"
        self.layout.label(text=text + "!", icon='ERROR')

    def execute(self, context):
        scene = context.scene
        keep = set(context.selected_objects)
        for obj in list(bpy.data.objects):
            if obj not in keep:
                bpy.data.objects.remove(obj)
        for obj in keep:
            if obj.name not in scene.collection.objects:
                scene.collection.objects.link(obj)
        for sc in list(bpy.data.scenes):
            if sc != scene:
                bpy.data.scenes.remove(sc)
        for coll in (bpy.data.materials, bpy.data.images, bpy.data.collections, bpy.data.texts, bpy.data.actions):
            for block in list(coll):
                coll.remove(block)
        if self.remove_brushes:
            # Blender's own brushes come linked from the Essentials asset library; local ones are custom.
            for brush in list(bpy.data.brushes):
                if brush.library is None:
                    bpy.data.brushes.remove(brush)
        for world in list(bpy.data.worlds):
            bpy.data.worlds.remove(world)
        used_groups = {m.node_group for obj in keep for m in obj.modifiers if m.type == 'NODES' and m.node_group}
        for ng in list(bpy.data.node_groups):
            if ng not in used_groups:
                bpy.data.node_groups.remove(ng)
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        kept_meshes = {obj.data for obj in keep if obj.type == 'MESH'}
        for me in list(bpy.data.meshes):
            if me not in kept_meshes:
                bpy.data.meshes.remove(me)
        space = context.space_data
        if getattr(space, "local_view", None):
            bpy.ops.view3d.localview()
        shading = getattr(space, "shading", None)
        if shading is not None:
            shading.use_scene_world = shading.use_scene_lights = False
            shading.use_scene_world_render = shading.use_scene_lights_render = False
        return {'FINISHED'}


class BLAYA_OT_reload_libraries(Operator):
    """Reload all linked libraries"""
    bl_idname = "blaya.reload_libraries"
    bl_label = "Reload Linked Libraries"

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(bpy.data.libraries)

    def execute(self, context):
        for lib in bpy.data.libraries:
            lib.reload()
        self.report({'INFO'}, f"Reloaded {len(bpy.data.libraries)} linked "
                              f"librar{'y' if len(bpy.data.libraries) == 1 else 'ies'}")
        return {'FINISHED'}


# --------------------------------------------------------------------------- auto save

_autosave = {"last": 0.0, "changed": False, "active_op": None, "toast_until": 0.0, "toast_text": ""}
_toast_handle = None


def autosave_folder(context=None):
    custom = bpy.path.abspath(_prefs(context).autosave_folder)
    if custom and os.path.isdir(custom):
        return custom
    folder = os.path.join(temp_dir(context), AUTOSAVE_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder


def autosave_stem():
    name = os.path.basename(bpy.data.filepath)
    return re.sub(r"\.blend\d*$", "", name) if name else "untitled"


def autosave_files(folder, stem):
    """This project's autosaves in `folder`, oldest first (the date prefix sorts by time)."""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_" + re.escape(stem) + r"-autosave\.blend\d?$")
    try:
        return sorted(f for f in os.listdir(folder) if pattern.match(f))
    except OSError:
        return []


def auto_save(context, undo=False):
    """Save a copy of the open file into the autosave folder and drop this project's oldest copies."""
    folder = autosave_folder(context)
    stem = autosave_stem()
    path = os.path.join(folder, f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{stem}-autosave.blend")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False, copy=True,
                                    compress=context.preferences.filepaths.use_file_compression)
    except RuntimeError as exc:
        print("Blaya: auto save failed:", exc)
        return False
    _autosave["changed"] = False
    limit = max(3, _prefs(context).autosave_limit)
    files = autosave_files(folder, stem)
    for old in files[:max(0, len(files) - limit)]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass
    _autosave["toast_text"] = "Auto Saved (undo)" if undo else "Auto Saved"
    _autosave["toast_until"] = time.monotonic() + AUTOSAVE_TOAST_SECONDS
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    return True


def _draw_autosave_toast():
    if time.monotonic() > _autosave["toast_until"]:
        return
    context = bpy.context
    region = context.region
    if region is None:
        return
    ui = context.preferences.system.ui_scale
    font = 0
    blf.size(font, 12 * ui)
    text = _autosave["toast_text"]
    w = blf.dimensions(font, text)[0]
    alpha = min(1.0, (_autosave["toast_until"] - time.monotonic()) / AUTOSAVE_TOAST_SECONDS * 2)
    blf.position(font, (region.width - w) / 2, 80 * ui, 0)
    blf.color(font, 0.35, 0.75, 1.0, alpha)
    blf.draw(font, text)


class BLAYA_OT_auto_save(Operator):
    """Toggle Auto Save: a copy of this file every few seconds while it has changes.
    Alt: pick an autosave to open. Ctrl: open the autosave folder"""
    bl_idname = "blaya.auto_save"
    bl_label = "Auto Save"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.blend;*.blend1", options={'HIDDEN'})

    def invoke(self, context, event):
        wm = context.window_manager
        if event.alt:
            self.filepath = autosave_folder(context) + os.sep
            self._browse = True
            wm.fileselect_add(self)
            return {'RUNNING_MODAL'}
        if event.ctrl:
            bpy.ops.wm.path_open(filepath=autosave_folder(context))
            return {'FINISHED'}
        if wm.blaya_auto_save:
            wm.blaya_auto_save = False  # the running modal ends on its next tick
            auto_save(context)          # one last copy right away
            return {'FINISHED'}
        wm.blaya_auto_save = True
        auto_save(context)
        _autosave["last"] = time.monotonic()
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if getattr(self, "_browse", False) and os.path.isfile(self.filepath):
            bpy.ops.wm.open_mainfile(filepath=self.filepath, load_ui=True)
            return {'FINISHED'}
        return {'CANCELLED'}

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.blaya_auto_save:
            wm.event_timer_remove(self._timer)
            return {'FINISHED'}
        if event.type == 'TIMER':
            interval = _prefs(context).autosave_interval
            if (bpy.data.is_dirty and _autosave["changed"]
                    and time.monotonic() - _autosave["last"] >= interval):
                auto_save(context)
                _autosave["last"] = time.monotonic()
        return {'PASS_THROUGH'}


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    _autosave["changed"] = True


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    wm = bpy.context.window_manager
    if wm is not None and getattr(wm, "blaya_auto_save", False):
        wm.blaya_auto_save = False  # a new file starts with Auto Save off
    _autosave["changed"] = False


def _undo_save():
    context = bpy.context
    wm = context.window_manager
    if wm is None or not getattr(wm, "blaya_auto_save", False):
        return None
    prefs = _prefs(context)
    op = context.active_operator
    if prefs.autosave_undo and op is None:
        auto_save(context, undo=True)
    elif prefs.autosave_redo and op is not None and op.bl_idname != _autosave["active_op"]:
        auto_save(context)
    _autosave["active_op"] = op.bl_idname if op is not None else None
    return None


@bpy.app.handlers.persistent
def _on_undo_pre(*_args):
    # Runs before the undo; the copy is taken right after it has been applied.
    if not bpy.app.timers.is_registered(_undo_save):
        bpy.app.timers.register(_undo_save, first_interval=0.0)


# --------------------------------------------------------------------------- pie

def _export_rows(layout, context):
    prefs = _prefs(context)
    has_selection = bool(context.selected_objects)
    rows = []
    if prefs.save_pie_show_obj:
        rows.append(("OBJ", "wm.obj_import", {}, "wm.obj_export", {"export_selected_objects": has_selection}))
    if prefs.save_pie_show_plasticity:
        axes = {"up_axis": 'Z', "forward_axis": 'Y'}
        rows.append(("Plasticity", "wm.obj_import", dict(axes), "wm.obj_export",
                     dict(axes, export_selected_objects=has_selection)))
    if prefs.save_pie_show_fbx and _op_exists("export_scene.fbx"):
        imp = "wm.fbx_import" if _op_exists("wm.fbx_import") else "import_scene.fbx"
        exp_props = {"use_selection": has_selection}
        if prefs.fbx_export_apply_scale_all:
            exp_props["apply_scale_options"] = 'FBX_SCALE_ALL'
        rows.append(("FBX", imp, {}, "export_scene.fbx", exp_props))
    if prefs.save_pie_show_usd and _op_exists("wm.usd_import"):
        rows.append(("USD", "wm.usd_import", {}, "wm.usd_export", {"selected_objects_only": has_selection}))
    if prefs.save_pie_show_gltf and _op_exists("export_scene.gltf"):
        rows.append(("glTF", "import_scene.gltf", {}, "export_scene.gltf", {"use_selection": has_selection}))
    if prefs.save_pie_show_stl and _op_exists("wm.stl_export"):
        rows.append(("STL", "wm.stl_import", {}, "wm.stl_export", {"export_selected_objects": has_selection}))
    if not rows:
        return False
    box = layout.box()
    col = box.column(align=True)
    for label, imp, imp_props, exp, exp_props in rows:
        split = col.split(factor=0.25 if prefs.save_pie_show_plasticity else 0.15, align=True)
        split.label(text=label)
        row = split.row(align=True)
        op = row.operator(imp, text="Import", icon='IMPORT')
        for k, v in imp_props.items():
            setattr(op, k, v)
        op = row.operator(exp, text="Export", icon='EXPORT')
        for k, v in exp_props.items():
            setattr(op, k, v)
        if label == "FBX":
            row.prop(prefs, "fbx_export_apply_scale_all", text="", icon='EMPTY_ARROWS')
    return True


class BLAYA_MT_save_pie(Menu):
    bl_idname = "BLAYA_MT_save_pie"
    bl_label = "Save, Open, Append"

    def draw(self, context):
        pie = self.layout.menu_pie()
        star = _dirty_star()
        image_editor = context.area is not None and context.area.type == 'IMAGE_EDITOR'
        pie.operator("wm.open_mainfile", text="Open...", icon='FILE_FOLDER')       # W
        pie.operator("blaya.file_save", text="Save" + star, icon='FILE_TICK')       # E
        pie.operator("blaya.file_save_as", text="Save As.." + star, icon='FILE_NEW')  # S
        if image_editor:
            self.draw_image_top(pie, context)                                         # N, NW, NE
        else:
            self.draw_top(pie, context)                                               # N
            pie.separator()                                                           # NW
            from . import ops_export
            ops_export.draw_pie_box(pie, context)                                     # NE
        pie.operator("blaya.file_new", text="New", icon='FILE')                       # SW
        pie.operator("blaya.file_save_incremental", text="Incremental Save", icon='DUPLICATE')  # SE

    def draw_top(self, pie, context):
        wm = context.window_manager
        prefs = _prefs(context)
        split = pie.split()
        # Left: recent, folders, revert, auto save
        box = split.box()
        col = box.column(align=True)
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("blaya.file_load_most_recent", text="(R) Most Recent", icon='FILE_REFRESH')
        row.menu("TOPBAR_MT_file_open_recent", text="All Recent", icon='RECOVER_LAST')
        row = col.row(align=True)
        row.operator("blaya.open_current_dir", text="Open Current", icon='FOLDER_REDIRECT')
        row.operator("blaya.open_temp_dir", text="Open Temp", icon='TEMP')
        col.separator()
        row = col.split(factor=0.49, align=True)
        row.operator("wm.revert_mainfile", text="Revert", icon='LOOP_BACK')
        row.operator("blaya.auto_save", text="Auto Save", icon='TIME', depress=wm.blaya_auto_save)
        if wm.blaya_auto_save:
            row = col.row(align=True)
            row.prop(prefs, "autosave_interval", text="")
            row.prop(prefs, "autosave_undo", text="Undo", toggle=True)
            row.prop(prefs, "autosave_redo", text="Redo", toggle=True)
        # Center: export, previous / next
        center = split.column()
        _export_rows(center, context)
        if bpy.data.filepath:
            box = center.box()
            row = box.split(factor=0.5, align=True)
            row.scale_y = 1.2
            row.operator("blaya.file_load_sibling", text="Previous", icon='TRIA_LEFT').direction = 'PREVIOUS'
            row.operator("blaya.file_load_sibling", text="Next", icon='TRIA_RIGHT').direction = 'NEXT'
            if os.path.normcase(os.path.dirname(bpy.data.filepath)) == os.path.normcase(temp_dir(context).rstrip("\\/")):
                box.label(text="You are currently in the Temp Folder", icon='ERROR')
                box.label(text="If you want to save, do it elsewhere!")
        # Right: append / link / external data / purge / clean
        box = split.box()
        col = box.column(align=True)
        row = col.row(align=True)
        row.operator("wm.append", text="Append", icon='APPEND_BLEND')
        row.operator("wm.link", text="Link", icon='LINK_BLEND')
        row.separator()
        row.menu("TOPBAR_MT_file_external_data", text="", icon='PACKAGE')
        row.operator("blaya.purge_orphans", text="Purge", icon='ORPHAN_DATA')
        if bpy.data.libraries:
            n = len(bpy.data.libraries)
            col.operator("blaya.reload_libraries",
                         text="Reload Linked Library" if n == 1 else "Reload All Linked Libraries",
                         icon='FILE_REFRESH')
        col.separator()
        col.operator("blaya.clean_out_blend", text="Clean out .blend", icon='ERROR')

    def draw_image_top(self, pie, context):
        space = context.space_data
        image = space.image
        if image is not None:                                                         # N
            pie.operator("image.save_as", text="Save Image As..", icon='IMAGE_DATA')
        else:
            pie.template_ID(space, "image", new="image.new", open="image.open")
        col = pie.column(align=True)                                                  # NW
        row = col.row(align=True)
        row.operator("image.open", text="Open Image", icon='FILE_IMAGE')
        if image is not None:
            row.operator("blaya.image_clear", text="", icon='X')
            if context.preferences.filepaths.image_editor:
                col.operator("image.external_edit", text="external edit", icon='WINDOW')
        col = pie.column(align=True)                                                  # NE
        if image is not None:
            if image.packed_file:
                col.operator("image.unpack", text="Unpack", icon='PACKAGE')
            else:
                col.operator("image.pack", text="Pack", icon='UGLYPACKAGE')
            col.operator("image.save", text="Save Image", icon='FILE_TICK')
        else:
            col.separator()


class BLAYA_OT_image_clear(Operator):
    """Close the image shown in this Image Editor (the image itself is kept)"""
    bl_idname = "blaya.image_clear"
    bl_label = "Clear Image"

    def execute(self, context):
        if context.space_data is not None and context.space_data.type == 'IMAGE_EDITOR':
            context.space_data.image = None
        return {'FINISHED'}


# --------------------------------------------------------------------------- registration

_classes = (BLAYA_OT_file_new, BLAYA_OT_file_save, BLAYA_OT_file_save_as, BLAYA_OT_file_save_incremental,
            BLAYA_OT_file_load_most_recent, BLAYA_OT_file_load_sibling, BLAYA_OT_open_current_dir,
            BLAYA_OT_open_temp_dir, BLAYA_OT_purge_orphans, BLAYA_OT_clean_out_blend, BLAYA_OT_reload_libraries,
            BLAYA_OT_auto_save, BLAYA_OT_image_clear, BLAYA_MT_save_pie)


def register():
    global _toast_handle
    bpy.types.WindowManager.blaya_auto_save = BoolProperty(name="Auto Save", default=False)
    for cls in _classes:
        bpy.utils.register_class(cls)
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load_post),
                         (bpy.app.handlers.undo_pre, _on_undo_pre)):
        if fn not in handlers:
            handlers.append(fn)
    _toast_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_autosave_toast, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _toast_handle
    wm = bpy.context.window_manager
    if wm is not None and getattr(wm, "blaya_auto_save", False):
        wm.blaya_auto_save = False
    if _toast_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_toast_handle, 'WINDOW')
        _toast_handle = None
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load_post),
                         (bpy.app.handlers.undo_pre, _on_undo_pre)):
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(_undo_save):
        bpy.app.timers.unregister(_undo_save)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.blaya_auto_save
