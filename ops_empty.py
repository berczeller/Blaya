# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Set Empty and Reset Position (marking menu, Object Mode).

Set Empty puts the selected objects under a Plain Axes Empty at the world center, ready for FBX export:
each object is moved so its own pivot sits on the world center, then its transforms are applied, so it
ends at location 0, rotation 0, scale 1 under the Empty. The Empty is named after the first selected
object in Outliner order without its _LOD<n> suffix (Chair_A_LOD0 ... Chair_A_LOD3 -> "Chair_A").

Reset Position puts objects moved around later (testing modules side by side) back into that state:
every object at 0 / 0 / 1 under its Empty, and the Empty back on the world center.

Hiding or showing a group's Empty hides or shows its children too, like a collection.
"""

import re

import bpy
from mathutils import Matrix, Quaternion

GROUP_KEY = "blaya_set_empty"        # on each object: the Empty it belongs to
ROOT_KEY = "blaya_set_empty_root"   # on the Empty itself

_LOD_RE = re.compile(r"_LOD\d+$", re.IGNORECASE)
_DUP_RE = re.compile(r"\.\d{3,}$")
_DATA_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LATTICE', 'ARMATURE', 'CURVES', 'POINTCLOUD',
               'GREASEPENCIL'}


def empty_name(name):
    """Chair_A_LOD0 -> Chair_A, Chair_A_LOD2.001 -> Chair_A, Table -> Table."""
    return _LOD_RE.sub("", _DUP_RE.sub("", name)) or name


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def outliner_order(objects):
    """Objects sorted the way the Outliner lists them by default: alphanumerically, numbers in order."""
    return sorted(objects, key=lambda o: natural_key(o.name))


def group_empty(obj):
    """The Set Empty this object belongs to, or None."""
    empty = obj.get(GROUP_KEY)
    if isinstance(empty, bpy.types.Object) and empty.name in bpy.data.objects and empty.get(ROOT_KEY):
        return empty
    return None


def top_level(objects):
    """Selected objects whose parent chain holds no other selected object (children follow their parent)."""
    chosen = set(objects)
    out = []
    for obj in objects:
        p = obj.parent
        while p is not None and p not in chosen:
            p = p.parent
        if p is None:
            out.append(obj)
    return out


def reset_transform(obj):
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.rotation_quaternion = Quaternion()
    obj.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)


class BLAYA_OT_set_empty(bpy.types.Operator):
    """Put the selected objects under an Empty at the world center: each object's pivot goes to the
    center and its transforms are applied (location 0, rotation 0, scale 1), ready for FBX export"""
    bl_idname = "blaya.set_empty"
    bl_label = "Set Empty"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(not o.get(ROOT_KEY) for o in context.selected_objects)

    def execute(self, context):
        objects = top_level([o for o in context.selected_objects if not o.get(ROOT_KEY)])
        if not objects:
            return {'CANCELLED'}
        ordered = outliner_order(objects)

        empty, previous, clash = self.resolve_empty(context, empty_name(ordered[0].name), objects, ordered[0])

        single = 0
        for obj in objects:
            data = obj.data
            if data is not None and getattr(data, "users", 1) > 1 and obj.type in _DATA_TYPES:
                obj.data = data.copy()  # applying transforms needs its own data
                single += 1
            # Free the object from any parent, then put its pivot on the world center keeping rotation / scale.
            mw = obj.matrix_world.copy()
            obj.parent = None
            mw.translation = (0.0, 0.0, 0.0)
            obj.matrix_world = mw
        context.view_layer.update()

        with context.temp_override(selected_editable_objects=objects, selected_objects=objects,
                                   active_object=objects[0], object=objects[0]):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True, properties=False)

        for obj in objects:
            obj.parent = empty
            obj.matrix_parent_inverse = Matrix.Identity(4)
            reset_transform(obj)
            obj[GROUP_KEY] = empty
        invalidate_roots()
        # Blaya Empties left without children by this move (the group changed Empty) are removed.
        for old in previous:
            if old is not empty and old.name in bpy.data.objects and old.get(ROOT_KEY) and not old.children:
                bpy.data.objects.remove(old)
        context.view_layer.update()
        note = f", {single} made single user" if single else ""
        msg = f"Set Empty '{empty.name}': {len(objects)} object{'s' if len(objects) != 1 else ''}{note}"
        if clash is not None:
            self.report({'WARNING'}, msg + f". '{clash.name}' is a {clash.type.lower()}, so the Empty got a suffix")
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}

    @staticmethod
    def resolve_empty(context, name, objects, first):
        """(Empty to use, the group Empties the objects came from, object holding `name` if it can't be used).

        Object names are unique in Blender, so a new Empty can't be called `name` if anything else already is.
        An Empty with that name is adopted (and put on the world center, keeping its other children in place);
        any other object keeps its name and the new Empty gets Blender's .001-style suffix.
        """
        previous = {group_empty(o) for o in objects} - {None}
        holder = bpy.data.objects.get(name)
        clash = None
        if holder is not None and holder.type == 'EMPTY' and holder not in objects:
            empty = holder
        else:
            if holder is not None:
                clash = holder
            # Re-running on a group that already has its Empty: reuse it instead of making another one.
            empty = next(iter(previous)) if len(previous) == 1 and clash is None else None
            if empty is not None and empty.name != name and holder is None:
                empty.name = name
            if empty is None:
                empty = bpy.data.objects.new(name, None)
                empty.empty_display_type = 'PLAIN_AXES'
                collections = first.users_collection
                (collections[0] if collections else context.scene.collection).objects.link(empty)
        empty[ROOT_KEY] = True
        others = [(c, c.matrix_world.copy()) for c in empty.children if c not in objects]
        empty.parent = None
        reset_transform(empty)
        context.view_layer.update()
        for child, mw in others:  # children that aren't part of this Set Empty stay where they were
            child.matrix_world = mw
        return empty, previous, clash


class BLAYA_OT_reset_position(bpy.types.Operator):
    """Put Set Empty groups back in their neutral state: every object at 0 / 0 / 1 under its Empty and
    the Empty on the world center. Works on the selected objects' groups (or the selected Empties)"""
    bl_idname = "blaya.reset_position"
    bl_label = "Reset Position"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def groups(context):
        empties = set()
        for obj in context.selected_objects:
            if obj.get(ROOT_KEY):
                empties.add(obj)
            elif group_empty(obj) is not None:
                empties.add(group_empty(obj))
        return empties

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(cls.groups(context))

    def execute(self, context):
        empties = self.groups(context)
        count = 0
        for empty in empties:
            reset_transform(empty)
            for obj in context.scene.objects:
                if group_empty(obj) is empty:
                    if obj.parent is not empty:
                        obj.parent = empty
                    obj.matrix_parent_inverse = Matrix.Identity(4)
                    reset_transform(obj)
                    count += 1
        context.view_layer.update()
        self.report({'INFO'}, f"Reset {count} object{'s' if count != 1 else ''} in {len(empties)} "
                              f"group{'s' if len(empties) != 1 else ''}")
        return {'FINISHED'}


# --------------------------------------------------------------------------- hide like a collection
# Hiding a Set Empty group's Empty (H, Shift+H, the Outliner eye...) hides its children too, and showing it
# shows them again, like a collection. Children hidden on their own before stay hidden when the group is
# shown, and selected children are never hidden by the Empty (so Shift+H on a selected LOD still works).

HIDDEN_BEFORE_KEY = "blaya_hidden_before"  # on the Empty: children that were already hidden when it was hidden
_hide_state = {}   # Empty name -> hidden (as last seen)
_syncing = [False]


def _prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


_root_cache = {"count": -1, "names": []}


def invalidate_roots():
    _root_cache["count"] = -1


def _roots():
    # This runs on every scene update (every frame of a drag), so the scan is cached and only redone when
    # the number of objects changes or Set Empty marks a new group.
    objects = bpy.data.objects
    if _root_cache["count"] != len(objects):
        _root_cache["names"] = [o.name for o in objects if o.type == 'EMPTY' and o.get(ROOT_KEY)]
        _root_cache["count"] = len(objects)
    found = [objects.get(n) for n in _root_cache["names"]]
    if any(o is None or not o.get(ROOT_KEY) for o in found):  # renamed or removed: rescan next time
        invalidate_roots()
    return [o for o in found if o is not None and o.get(ROOT_KEY)]


def _hidden(obj, view_layer):
    try:
        return obj.hide_get(view_layer=view_layer)
    except RuntimeError:  # not in this view layer
        return None


def sync_group_visibility(view_layer):
    """Make the children of Set Empty groups follow their Empty when its visibility changed."""
    prefs = _prefs()
    if prefs is None or not prefs.group_hide_children or _syncing[0]:
        return
    _syncing[0] = True
    try:
        for empty in _roots():
            hidden = _hidden(empty, view_layer)
            if hidden is None:
                continue
            was = _hide_state.get(empty.name)
            _hide_state[empty.name] = hidden
            if was is None or was == hidden:
                continue  # first sight (file load, new group) or no change: leave the children alone
            kids = [c for c in empty.children_recursive if _hidden(c, view_layer) is not None]
            if hidden:
                empty[HIDDEN_BEFORE_KEY] = [c.name for c in kids if _hidden(c, view_layer)]
                for c in kids:
                    if not c.select_get(view_layer=view_layer):
                        c.hide_set(True, view_layer=view_layer)
            else:
                keep = set(empty.get(HIDDEN_BEFORE_KEY, []))
                for c in kids:
                    if c.name not in keep:
                        c.hide_set(False, view_layer=view_layer)
                if HIDDEN_BEFORE_KEY in empty:
                    del empty[HIDDEN_BEFORE_KEY]
    finally:
        _syncing[0] = False


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    if not _syncing[0]:
        sync_group_visibility(depsgraph.view_layer)


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    _hide_state.clear()  # the next update only records the loaded file's state


_classes = (BLAYA_OT_set_empty, BLAYA_OT_reset_position)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load_post)):
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
                         (bpy.app.handlers.load_post, _on_load_post)):
        if fn in handlers:
            handlers.remove(fn)
    _hide_state.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
