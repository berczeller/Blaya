# SPDX-FileCopyrightText: 2026 Tom Berczeller
# SPDX-License-Identifier: GPL-3.0-or-later
"""Set Empty and Reset Position (marking menu, Object Mode).

Set Empty puts the selected objects under a Plain Axes Empty at the world center, ready for FBX export:
each object is moved so its own pivot sits on the world center, then its transforms are applied, so it
ends at location 0, rotation 0, scale 1 under the Empty. The Empty is named after the first selected
object in Outliner order without its _LOD<n> suffix (Chair_A_LOD0 ... Chair_A_LOD3 -> "Chair_A").

Reset Position puts objects moved around later (testing modules side by side) back into that state:
every object at 0 / 0 / 1 under its Empty, and the Empty back on the world center.

Hiding or showing any Empty hides or shows its children too, like a collection, and Empty to Collection
turns Empties into real collections with the same names.
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


def is_group_empty(obj):
    return obj is not None and obj.type == 'EMPTY' and bool(obj.get(ROOT_KEY))


def group_empty(obj):
    """The Set Empty group this object belongs to, or None.

    Its parent wins when that is a group Empty, so objects parented to a group later (a new part or LOD
    added with Ctrl+P or an Outliner drag) belong to it too. Otherwise the group recorded by Set Empty,
    so an object unparented by accident still goes back with Reset Position.
    """
    if is_group_empty(obj.parent):
        return obj.parent
    empty = obj.get(GROUP_KEY)
    if isinstance(empty, bpy.types.Object) and empty.name in bpy.data.objects and is_group_empty(empty):
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


def bake_to_center(context, objects):
    """Move each object's pivot onto the world center keeping its rotation / scale, then apply its
    transforms, so it can sit at location 0, rotation 0, scale 1 under a group Empty without changing
    shape. Returns how many objects got their own copy of shared data."""
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
    return single


def adopt(empty, obj):
    """Put an object under a group Empty in the neutral state (location 0, rotation 0, scale 1)."""
    obj.parent = empty
    obj.matrix_parent_inverse = Matrix.Identity(4)
    reset_transform(obj)
    obj[GROUP_KEY] = empty


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

        single = bake_to_center(context, objects)
        for obj in objects:
            adopt(empty, obj)
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
        count = added = 0
        for empty in empties:
            reset_transform(empty)
            members = [o for o in context.scene.objects if group_empty(o) is empty]
            # Parented to the group after Set Empty: baked like Set Empty does, so its rotation and
            # scale survive the reset instead of being zeroed.
            newcomers = [o for o in members if o.get(GROUP_KEY) is not empty]
            if newcomers:
                context.view_layer.update()
                bake_to_center(context, newcomers)
                added += len(newcomers)
            for obj in members:
                adopt(empty, obj)
            count += len(members)
        context.view_layer.update()
        note = f", {added} added to their group" if added else ""
        self.report({'INFO'}, f"Reset {count} object{'s' if count != 1 else ''} in {len(empties)} "
                              f"group{'s' if len(empties) != 1 else ''}{note}")
        return {'FINISHED'}


def _depth(obj):
    n = 0
    while obj.parent is not None:
        obj, n = obj.parent, n + 1
    return n


def _convertible(obj):
    # A collection-instance Empty shows another collection; turning it into one would lose that.
    return obj.type == 'EMPTY' and obj.instance_type != 'COLLECTION'


class BLAYA_OT_empty_to_collection(bpy.types.Operator):
    """Turn the selected Empties into collections with the same names. Their children move into the
    collection and keep their place in the world"""
    bl_idname = "blaya.empty_to_collection"
    bl_label = "Empty to Collection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(_convertible(o) for o in context.selected_objects)

    def execute(self, context):
        # Outer Empties first: a nested Empty's objects are already in the outer collection by the time
        # it is converted, so its collection ends up inside the outer one.
        empties = sorted((o for o in context.selected_objects if _convertible(o)), key=_depth)
        renamed = []
        for empty in empties:
            name = empty.name
            homes = empty.users_collection
            home = homes[0] if homes else context.scene.collection
            coll = bpy.data.collections.new(name)
            home.children.link(coll)
            for obj in empty.children_recursive:
                for c in list(obj.users_collection):
                    c.objects.unlink(obj)
                coll.objects.link(obj)
            for obj in empty.children:
                mw = obj.matrix_world.copy()
                obj.parent = None
                obj.matrix_world = mw
                if GROUP_KEY in obj:
                    del obj[GROUP_KEY]
            _hide_state.pop(name, None)
            from . import ops_export
            ops_export.replace_root(empty, coll)  # an export root stays one, with its folder and settings
            bpy.data.objects.remove(empty)
            if coll.name != name:
                renamed.append(coll.name)
        context.view_layer.update()
        msg = f"{len(empties)} Empt{'ies' if len(empties) != 1 else 'y'} turned into collections"
        if renamed:
            self.report({'WARNING'}, msg + f". Name already used by a collection: {', '.join(renamed)}")
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


# --------------------------------------------------------------------------- hide like a collection
# Hiding any Empty (H, Shift+H, the Outliner eye, however the Empty was made) hides everything parented
# under it too, and showing it shows them again, like a collection. Children hidden on their own before
# stay hidden when the Empty is shown. Shift+H keeps the selection visible, so a selected LOD stays shown
# even though its Empty is hidden.

HIDDEN_BEFORE_KEY = "blaya_hidden_before"  # on the Empty: children that were already hidden when it was hidden
_hide_state = {}   # Empty name -> hidden (as last seen)
_syncing = [False]
_keep_selected = [False]  # set by Hide Unselected (Shift+H) for the update that follows it


def _prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


def _empties(view_layer):
    # Runs on every scene update (every frame of a drag). One pass over the view layer is about 1.5 ms
    # with 6000 objects, while looking objects up by name is linear per lookup and took 100 ms.
    return [o for o in view_layer.objects if o.type == 'EMPTY']


class BLAYA_OT_hide_unselected(bpy.types.Operator):
    """Hide everything that isn't selected. A selected object stays visible even when the Empty it is
    parented to gets hidden"""
    bl_idname = "blaya.hide_unselected"
    bl_label = "Hide Unselected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bpy.ops.object.hide_view_set.poll()

    def execute(self, context):
        _keep_selected[0] = True  # read by the next scene update, right after this operator
        return bpy.ops.object.hide_view_set(unselected=True)


def _hidden(obj, view_layer):
    try:
        return obj.hide_get(view_layer=view_layer)
    except RuntimeError:  # not in this view layer
        return None


def _set_hidden(obj, state, view_layer):
    obj.hide_set(state, view_layer=view_layer)
    if obj.type == 'EMPTY':
        # A nested Empty hidden or shown by its parent isn't a change of its own: without this, the next
        # update would see it change and hide its children again right after they were shown.
        _hide_state[obj.name] = state


def sync_group_visibility(view_layer):
    """Make the children of every Empty follow it when its visibility changed."""
    prefs = _prefs()
    if prefs is None or not prefs.group_hide_children or _syncing[0]:
        return
    _syncing[0] = True
    keep_selected, _keep_selected[0] = _keep_selected[0], False
    try:
        changed = []
        for empty in _empties(view_layer):
            hidden = _hidden(empty, view_layer)
            if hidden is None:
                continue
            was = _hide_state.get(empty.name)
            _hide_state[empty.name] = hidden
            if was is not None and was != hidden:  # first sight (file load, new Empty): leave it alone
                changed.append(empty)
        if not changed:
            return
        handled = set()      # nested Empties already hidden or shown with an outer one
        for empty in sorted(changed, key=_depth):  # outer Empties first
            if empty.name in handled:
                continue
            hidden = _hidden(empty, view_layer)
            kids = [c for c in empty.children_recursive if _hidden(c, view_layer) is not None]
            handled.update(c.name for c in kids)
            if not kids:
                continue
            if hidden:
                empty[HIDDEN_BEFORE_KEY] = [c.name for c in kids if _hidden(c, view_layer)]
                for c in kids:
                    if not (keep_selected and c.select_get(view_layer=view_layer)):
                        _set_hidden(c, True, view_layer)
            else:
                keep = set(empty.get(HIDDEN_BEFORE_KEY, []))
                for c in kids:
                    if c.name not in keep:
                        _set_hidden(c, False, view_layer)
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


_classes = (BLAYA_OT_set_empty, BLAYA_OT_reset_position, BLAYA_OT_empty_to_collection, BLAYA_OT_hide_unselected)


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
