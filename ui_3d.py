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

import bpy
import numpy as np
from math import pi
from operator import attrgetter

from .addon import addon
from . import util


def scale_image(image, scale):
    """Scale image in-place without filtering"""
    w, h = image.size
    px = np.array(image.pixels, dtype=np.float32)
    px.shape = (w, h, 4)
    image.scale(w * scale, h * scale)
    px = px.repeat(scale, 0).repeat(scale, 1)
    try:
        # version >= 2.83
        image.pixels.foreach_set(px.ravel())
    except:
        # version < 2.83
        image.pixels[:] = px.ravel()
    image.update()


class SB_OT_reference_add(bpy.types.Operator):
    bl_idname = "pribambase.reference_add"
    bl_label = "Add Reference"
    bl_description = "Add reference image with pixels aligned to the view grid"
    bl_options = {'REGISTER', 'UNDO'}

    scale: bpy.props.IntProperty(
        name="Prescale",
        description="Prescale the image",
        default=10,
        min=1,
        max=50)

    opacity: bpy.props.FloatProperty(
        name="Opacity",
        description="Image's viewport opacity",
        default=0.33,
        min=0.0,
        max=1.0,
        subtype='FACTOR')

    selectable: bpy.props.BoolProperty(
        name="Selectable",
        description="If checked, the image can be selected in the viewport, otherwise only in the outliner",
        default=True)

    # dialog
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.bmp;*.png", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    @classmethod
    def poll(self, context):
        return not context.object or context.object.mode == 'OBJECT'


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


    def execute(self, context):
        image = bpy.data.images.load(self.filepath)
        #image.pack() # NOTE without packing it breaks after reload but so what
        w, h = image.size
        scale_image(image, self.scale)
        image.sb_props.prescale = self.scale

        bpy.ops.object.add(align='WORLD', rotation=(pi/2, 0, 0), location = (0, 0, 0))
        ref = context.active_object
        ref.data = image
        ref.empty_display_type = 'IMAGE'
        ref.use_empty_image_alpha = self.opacity < 1.0
        ref.color[3] = self.opacity
        ref.empty_display_size = max(w, h) * context.space_data.overlay.grid_scale
        if not self.selectable:
            ref.hide_select = True
            self.report({'INFO'}, "The reference won't be selectable. Use the outliner to reload/delete it")

        return {'FINISHED'}


class SB_OT_reference_reload(bpy.types.Operator):
    bl_idname = "pribambase.reference_reload"
    bl_label = "Reload Reference"
    bl_description = "Reload reference while keeping it prescaled"
    bl_options = {'REGISTER', 'UNDO'}


    @classmethod
    def poll(self, context):
        return context.object and context.object.type == 'EMPTY' \
                and context.object.empty_display_type == 'IMAGE'


    def execute(self, context):
        image = context.object.data
        image.reload()
        scale_image(image, image.sb_props.prescale)

        return {'FINISHED'}


class SB_OT_reference_reload_all(bpy.types.Operator):
    bl_idname = "pribambase.reference_reload_all"
    bl_label = "Reload All References"
    bl_description = "Reload all references (including non-pribamabase's), while keeping them prescaled"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE':
                image = obj.data
                image.reload()
                scale_image(image, image.sb_props.prescale)

        return {'FINISHED'}


def set_new_animation_name(self, v):
    self["name"] = util.unique_name(v, bpy.context.active_object.sb_props.animations)


class SB_OT_spritesheet_rig(bpy.types.Operator):
    bl_idname = "pribambase.spritesheet_rig"
    bl_label = "Setup Sprite Animation"
    bl_description = "Set up spritesheet UV animation for this object. Does not affect materials or textures"
    bl_options = {'UNDO'}


    name: bpy.props.StringProperty(
        name="Name",
        description="Name for animation, also used for custom property and modifier",
        default="Sprite Frame", 
        set=set_new_animation_name,
        get=lambda self: self["name"] if "name" in self else util.unique_name("Sprite Frame", bpy.context.active_object.sb_props.animations))

    image: bpy.props.EnumProperty(
        name="Sprite",
        description="Animation to use (needed to calculate spritesheet UV transforms)",
        items=lambda self, context: [(img.name, img.name, "", i) for i,img in enumerate((img for img in bpy.data.images if img.sb_props.sheet))],
        default=0)

    action: bpy.props.EnumProperty(
        name="Action",
        description="If set, replaces object's current timeline with sprite animation. Old keyframes can be acessed in action editor, and WILL BE LOST after reloading unless protected. \"Editor\" action syncs with the loop section of Asperite's timeline.",
        items=lambda self,context: [("__none__", "", "", 0)] + [(a.name, a.name, "", i + 1) for i,a in enumerate((a for a in bpy.data.actions if a.sb_props.sprite and a.sb_props.sprite.name == self.image))],
        default=0)

    uv_map: bpy.props.EnumProperty(
        name="UV Layer",
        description="UV Layer that transforms apply to",
        items=lambda self, context : [] if context is None else [("__none__", "", "", 0)] + [(layer.name, layer.name, "", i + 1) for i,layer in enumerate(context.active_object.data.uv_layers)],
        default=0)
    

    @classmethod
    def poll(self, context):
        # need a mesh to store modifiers these days
        return context.active_object and context.object.type == 'MESH' and context.active_object.select_get() and next((img for img in bpy.data.images if img.sb_props.sheet), False)


    def execute(self, context):
        obj = context.active_object
        img = bpy.data.images[self.image]
        start = img.sb_props.sheet.sb_props.sheet_start

        anim = obj.sb_props.animations_new("Sprite Frame")
        anim.image = img
        prop_name = anim.name

        # custom property
        if prop_name not in obj:
            obj[prop_name] = start

        if "_RNA_UI" not in obj:
            obj["_RNA_UI"] = {}
        obj["_RNA_UI"][prop_name] = { "description": "Animation frame, uses the same numbering as timeline in Aseprite" }

        # modifier
        if prop_name not in obj.modifiers:
            obj.modifiers.new(prop_name, "UV_WARP")
        
        uvwarp = obj.modifiers[prop_name]
        uvwarp.uv_layer = "" if self.uv_map == "__none__" else self.uv_map
        uvwarp.center = (0.0, 1.0)
        
        util.update_sheet_animation(anim)
        
        if self.action != "__none__" and self.action in bpy.data.actions:
            obj.animation_data.action = bpy.data.actions[self.action]

        obj.update_tag()

        return {'FINISHED'}


    def invoke(self, context, event):
        if not next((True for img in bpy.data.images if img.sb_props.sheet), False):
            self.report({'ERROR'}, "No animations in the current blendfile")
            return {'CANCELLED'}

        if not context.active_object.data.uv_layers:
            self.report({'ERROR'}, "THe object must have at least one UV map")
            return {'CANCELLED'}
            
        return context.window_manager.invoke_props_dialog(self)



class SB_PT_panel_link(bpy.types.Panel):
    bl_idname = "SB_PT_panel_link_3d"
    bl_label = "Sync"
    bl_category = "Tool"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):
        layout = self.layout

        row = layout.row()
        status = "Off"
        icon = 'UNLINKED'
        if addon.connected:
            status = "Connected"
            icon = 'CHECKMARK'
        elif addon.server_up:
            status = "Waiting..."
            icon = 'SORTTIME'

        row.label(text=status, icon=icon)

        row = row.row()
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.stop_server", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("pribambase.start_server", text="Connect", icon="DECORATE_LINKED")
        row.operator("pribambase.preferences", icon='PREFERENCES', text="", emboss=False)

        layout.row().operator("pribambase.reference_add")
        layout.row().operator("pribambase.reference_reload")
        layout.row().operator("pribambase.reference_reload_all")

        layout.separator()

        layout.row().operator("pribambase.spritesheet_rig")

        if context.object and context.object.type == 'MESH':
            for anim in context.object.sb_props.animations:
                row = layout.row()
                row.prop(context.object, f'["{anim.name}"]')

