# This code is licensed under CC0 (Public Domain). You may freely use or modify it for any purpose.
# The original code was written by GadFlight and can be found at his GitHub repository: (https://github.com/GadFlight)

from collections import defaultdict
from typing import Iterable, Type, Union
import traceback as exc

import bpy
from bpy.types import KeyConfig, KeyMap, Context
from bpy.utils import register_class, unregister_class

keymaps: dict[str, KeyMap] = {}

def keymap_def(name, space_type='EMPTY', region_type='WINDOW'):
    """Ensures that desired addon keymap exists. Typically you will only need to specify the name of a '(Global)' 
    section of the keymap preferences."""
    kc: KeyConfig = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.new(name, space_type=space_type, region_type=region_type)
    keymaps[name] = km

addon_keymaps = defaultdict(list)

def binding_def(maps: Union[str, Iterable[str]], op, key, op_action, mods="", modifier=None,
                repeat=False, **properties):
    """Defines a key binding for the specified operator in the named keymap(s). Note: the keymaps should be defined before using 'keymap_def' method."""

    if isinstance(maps, str):
        maps = (maps,)
    for keymap in maps:
        km = keymaps[keymap]
        mod_dict = dict(shift="S" in mods, ctrl="C" in mods, alt="A" in mods)
        if modifier:
            mod_dict["key_modifier"] = modifier
        kmi = km.keymap_items.new(op, key, op_action, repeat=repeat, **mod_dict)
        if properties:
            for k, v in properties.items():
                setattr(kmi.properties, k, v)
        addon_keymaps[keymap].append(kmi)

def bindings_clear():
    """Clears all bindings created via binding_def."""
    for km, items in addon_keymaps.items():
        keymap = keymaps[km]
        for kmi in items:
            keymap.keymap_items.remove(kmi)
    addon_keymaps.clear()

_blender_classes = {}

def register_BlenderClasses():
    """Registers all classes created via @BlenderClass or @BlenderOperator."""
    for cls in _blender_classes.values():
        register_class(cls)

def unregister_BlenderClasses():
    """Unregisters all classes registed via register_BlenderClasses. If an error occurs, the traceback is printed."""
    for cls in _blender_classes.values():
        try:
            unregister_class(cls)
        except:
            exc.print_stack()

def BlenderClass(cls: Type) -> Type:
    """Notes a blender class with a bl_idname that will be automatically registered via register_BlenderClasses."""
    _blender_classes[cls.bl_idname] = cls
    return cls

OPTIONS_NONE = set()
OPTIONS_UNDO = {"UNDO"}
OPTIONS_REDO = {"REGISTER", "UNDO"}

def BlenderOperator(id: str, options=OPTIONS_NONE, label=None, description=None):
    """Wrapper to create a new Blender operator, specifying the standard "bl_" header values. These operators will be
    automatically registered via register_BlenderClasses.
    
    'options' will typically be one of the OPTIONS_* constants. If 'label' is not specified, it will be generated
    from the id."""
    if not label:
        label = " ".join(p.capitalize() for p in id[id.rindex(".") + 1:].split("_"))

    def wrapper(cls: Type) -> Type:
        cls.bl_idname = id
        cls.bl_label = label
        cls.bl_options = options
        cls.bl_description = description
        return BlenderClass(cls)

    return wrapper

def show_results_dialog(lines: list[str]):
    """Displays a popup dialog with the given lines of text."""
    def draw(self, context: Context):
        for line in lines:
            self.layout.label(text=line)

    bpy.context.window_manager.popup_menu(draw, title="Results", icon="INFO")

def make_enum(*values, is_flag=False, **pairs):
    """Generates an enumerated type from a list of values and pairs. 
    
    If is_flag is True, the values are treated as bit flags. If False, they are treated as a list.  
    If pairs are specified, they are added to the enumeration after the values. The pairs are specified
    as keyword arguments, where the key is the name of the enumeration value and the value is the display 
    name. If the display name is not specified, the key is used."""
    def index(i):
        return 2**i if is_flag else i

    result: list[tuple] = [
        *((v, " ".join(s.capitalize()
                       for s in v.split("_")), "", index(i))
          for i, v in enumerate(values)),
        *((k, v, "", index(i + len(values))) for i, (k, v) in enumerate(pairs.items()))
    ]
    return result

def report_finished(op_self, message, warn=False):
    """A convenience function which reports a message to the user and returns {'FINISHED'}."""
    op_self.report({"WARNING" if warn else "INFO"}, message)
    return {"FINISHED"}
