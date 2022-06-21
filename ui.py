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
Connection panel and general stuff.
"""

import bpy

from .addon import addon
from .image import SB_OT_sprite_reload_all


class SB_OT_grid_set(bpy.types.Operator):
    bl_idname = "pribambase.grid_set"
    bl_label = "Pixel Grid"
    bl_description = "Set grid step in every viewport"
    

    step: bpy.props.FloatProperty(
        name="Density (px/m)",
        description="Grid step in pixels. It's inverse of what viewport uses",
        default=10)
    

    def execute(self, context):
        if not context or not context.window_manager:
            return {'CANCELLED'}

        context.scene.unit_settings.system = 'NONE'
        # looong looong
        for wsp in bpy.data.workspaces:
            for screen in wsp.screens:
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            if space.type == 'VIEW_3D':
                                space.overlay.grid_subdivisions = 1
                                space.overlay.grid_scale = 1/self.step

        return {'FINISHED'}
    

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class SB_PT_uv_draw(bpy.types.Panel):
    bl_idname = "SB_PT_uv_draw"
    bl_label = "UV Style"
    bl_category = "Pribambase"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, ctx):
        layout = self.layout

        watch_row = layout.row()
        watch_row.enabled = addon.prefs.uv_sync_auto
        watch_row.prop(addon.state, "uv_watch")
        size_row = layout.row(align=True)
        if addon.state.uv_is_relative:
            size_row.prop(addon.state, "uv_scale")
            size_row.prop(addon.state, "uv_is_relative", icon='LINKED', text="")
        else:
            size_row.prop(addon.state, "uv_size")
            size_row.prop(addon.state, "uv_is_relative", icon='UNLINKED', text="")
        layout.prop(addon.state, "uv_color")
        layout.prop(addon.state, "uv_weight")


class SB_PT_edit(bpy.types.Panel):
    bl_idname = "SB_PT_edittil"
    bl_label = "Edit"
    bl_category = "Pribambase"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.label(text="As Plane")
        row.operator("pribambase.plane_add", text="Image", icon='FILE_IMAGE').from_file = False
        row.operator("pribambase.plane_add", text="Open", icon='FILE').from_file = True
        row.operator("pribambase.plane_add", text="New", icon='ADD').new_image = True

        layout.operator("pribambase.material_add", icon='MATERIAL')
        layout.operator("pribambase.grid_set", icon='GRID')
        
        row = layout.row()
        row.operator("pribambase.sprite_reload_all", icon='FILE_REFRESH')
        if not SB_OT_sprite_reload_all.poll(context):
            row.label(text="", icon='UNLINKED')


class SB_PT_link(bpy.types.Panel):
    bl_idname = "SB_PT_link"
    bl_label = "Sync"
    bl_category = "Pribambase"
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

        if bpy.app.version < (2, 81):
            icon = 'NONE' # :\

        row.label(text=status, icon=icon)

        row = row.row(align=True)
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.server_stop", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("pribambase.server_start", text="Connect", icon="DECORATE_LINKED")
        row.operator("pribambase.preferences", icon='PREFERENCES', text="")
