# Copyright (c) 2021 lampysprites
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Working with animation
"""

import math
import bpy
import numpy as np
from math import pi
from mathutils import Matrix
from bpy_extras import object_utils
import os.path


from .messaging import encode
from .addon import addon
from .image import SB_OT_sprite_open
from . import util
from . import modify
from . import ase


_action = ""
_msgbus_anim_data_callback_owner = object()
def sb_msgbus_anim_data_callback():
    global _action
    scene = bpy.context.scene
    obj = addon.state.action_preview

    if not scene.use_preview_range or not obj:
        bpy.msgbus.clear_by_owner(_msgbus_anim_data_callback_owner)
        return

    if obj.animation_data.action != _action:
        _action = obj.animation_data.action.name
        scene.frame_preview_start, scene.frame_preview_end = addon.state.action_preview.animation_data.action.frame_range
        # try to revive the curves
        for fcurve in obj.animation_data.action.fcurves:
            fcurve.data_path += ""

class SB_OT_action_preview_set(bpy.types.Operator):
    bl_idname = "pribambase.action_preview_set"
    bl_label = "Tag Preview"
    bl_description = "Lock timeline preview range to selected tag action"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH' and \
            context.active_object.animation_data and context.active_object.animation_data.action and \
            not context.active_object == addon.state.action_preview
    
    def execute(self, context):
        # NOTE when using self here, note that this method is directly invoked during scene initialization
        scene = context.scene
        obj = context.active_object
        addon.state.action_preview = obj
        addon.state.action_preview_enabled = True
        scene.use_preview_range = True
        scene.frame_preview_start, scene.frame_preview_end = obj.animation_data.action.frame_range

        bpy.msgbus.clear_by_owner(_msgbus_anim_data_callback_owner) # try to unsub in case we're changing the object
        bpy.msgbus.subscribe_rna(
            key=bpy.context.active_object.animation_data,
            owner=_msgbus_anim_data_callback_owner,
            args=tuple(),
            notify=sb_msgbus_anim_data_callback,
            options={'PERSISTENT'})

        return {'FINISHED'}


class SB_OT_action_preview_clear(bpy.types.Operator):
    bl_idname = "pribambase.action_preview_clear"
    bl_label = "Cancel Action Preview"
    bl_description = "Stop locking timeline preview range to action length"
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        return addon.state.action_preview_enabled and scene.use_preview_range
    
    def execute(self, context):
        scene = context.scene
        addon.state.action_preview = None
        addon.state.action_preview_enabled = False
        scene.use_preview_range = False
        bpy.msgbus.clear_by_owner(_msgbus_anim_data_callback_owner)
        return {'FINISHED'}


class SB_PT_animation(bpy.types.Panel):
    bl_idname = "SB_PT_animation"
    bl_label = "Animation"
    bl_category = "Pribambase"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):        
        layout = self.layout

        if context.active_object and context.active_object.type == 'MESH':
            obj = context.active_object
            
            # Info
            row = layout.row()
            row.alignment = 'CENTER'
            if next((False for img in bpy.data.images if img.sb_props.sheet), True):
                row.label(text="No synced sprites have animations", icon='INFO')

            row = layout.row(align=True)
            row.operator("pribambase.spritesheet_rig", icon='ADD', text="Set Up")
            row.operator("pribambase.spritesheet_unrig", icon='REMOVE', text="Remove")

            if obj.sb_props.animations:
                anim = obj.sb_props.animations[0]
                prop_name = anim.prop_name

                if not next((True for driver in obj.animation_data.drivers if driver.data_path == f'modifiers["{prop_name}"].offset'), False):
                    layout.row().label(text="Driver(s) were removed or renamed", icon='ERROR')
                elif prop_name not in obj.modifiers:
                    layout.row().label(text="UVWarp modifier was removed or renamed", icon='ERROR')
                elif prop_name not in obj:
                    layout.row().label(text="Object property was removed or renamed", icon='ERROR')
                else:
                    layout.row().prop(obj, f'["{prop_name}"]', text="Frame", expand=False)

            row = layout.row(align=True)
            row.enabled = bool(obj.animation_data)

            sub = row.column()
            sub.enabled = bool(obj.sb_props.animations)
            sub.prop(obj.sb_props, "animation_tag_setter", text="Tag", text_ctxt="ase")
            
            if addon.state.action_preview_enabled:
                active_picked = (context.active_object == addon.state.action_preview)
                row.operator("pribambase.action_preview_set", icon='EYEDROPPER', text="", depress=active_picked)
                row.operator("pribambase.action_preview_clear", icon='PREVIEW_RANGE', text="", depress=True)
            else:
                row.operator("pribambase.action_preview_set", icon='PREVIEW_RANGE', text="")

        else:
            layout.label(text="Select a mesh")
