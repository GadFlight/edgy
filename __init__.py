# This code is licensed under CC0 (Public Domain). You may freely use or modify it for any purpose.
# The original code was written by GadFlight and can be found at his GitHub repository: (https://github.com/GadFlight)

from typing import cast
import bpy
from bpy.types import AddonPreferences, AnyType

from . import util, loops  # Note: we must import 'loops' to register the classes.
from .util import (BlenderClass, binding_def, bindings_clear, register_BlenderClasses,
                   unregister_BlenderClasses)

bl_info = {
    "name": "edgy",
    "description": "Utilities to improve the handling of edit-mode edge loops.",
    "author": "GadFlight",
    "version": (1, 0),
    "blender": (3, 5, 0),
    "support": "COMMUNITY",
    "category": "Mesh"
}

def register_bindings(context):
    """Registers all key bindings for the addon. This method is called automatically when the addon is enabled."""
    util.keymap_def("Mesh")
    if context.preferences.addons[__name__].preferences.override_resize:
        binding_def("Mesh", "mesh.edgy_resize_selection", "NUMPAD_PLUS", "PRESS", "C", repeat=True,
                    direction="GROW")
        binding_def("Mesh", "mesh.edgy_resize_selection", "NUMPAD_MINUS", "PRESS", "C", repeat=True,
                    direction="SHRINK")
    if context.preferences.addons[__name__].preferences.override_select:
        binding_def("Mesh", "mesh.edgy_select_loop", "LEFTMOUSE", "CLICK", "A", extend=False)
        binding_def("Mesh", "mesh.edgy_select_loop", "LEFTMOUSE", "CLICK", "AS", extend=True)

def update_bindings(_, context):
    """Refreshes the key bindings for the addon. This method gets triggered when the addon preferences change."""
    bindings_clear()
    register_bindings(context)

@BlenderClass
class EdgyPreferences(AddonPreferences):
    """Preferences for the edgy addon."""
    bl_idname = __package__

    override_resize: bpy.props.BoolProperty(name="Override default 'Select More/Less'",
                                            default=True, update=update_bindings)  # type: ignore
    override_select: bpy.props.BoolProperty(name="Override default 'Loop Select'", default=True,
                                            update=update_bindings)  # type: ignore

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(cast(AnyType, self), "override_resize", toggle=True)
        layout.prop(cast(AnyType, self), "override_select", toggle=True)

def selection_ops_menu(self, context):
    """Includes the edgy selection operators in the edit mode's select menu."""

    layout = self.layout
    layout.separator()
    layout.operator("mesh.edgy_close_loop", text="Close Loop Selection")
    layout.operator("mesh.edgy_resize_selection", text="Grow Selection (Edgy)").direction = "GROW"
    layout.operator("mesh.edgy_resize_selection",
                    text="Shrink Selection (Edgy)").direction = "SHRINK"

def register():
    register_BlenderClasses()
    register_bindings(bpy.context)
    bpy.types.VIEW3D_MT_select_edit_mesh.append(selection_ops_menu)

def unregister():
    bpy.types.VIEW3D_MT_select_edit_mesh.remove(selection_ops_menu)
    bindings_clear()
    unregister_BlenderClasses()
