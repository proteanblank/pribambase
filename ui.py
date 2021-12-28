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


class SB_OT_grid_set(bpy.types.Operator):
    bl_idname = "pribambase.grid_set"
    bl_label = "Set Pixel Grid"
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


class SB_PT_link(bpy.types.Panel):
    bl_idname = "SB_PT_link"
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

        if bpy.app.version < (2, 81):
            icon = 'NONE' # :\

        row.label(text=status, icon=icon)

        row = row.row(align=True)
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.server_stop", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("pribambase.server_start", text="Connect", icon="DECORATE_LINKED")
        row.menu("SB_MT_global", icon='DOWNARROW_HLT', text="")

        layout.row().operator("pribambase.pencil")


class SB_MT_global(bpy.types.Menu):
    bl_label = "Pribambase"
    bl_idname = "SB_MT_global"

    def draw(self, context):
        layout = self.layout
        layout.operator("pribambase.grid_set")
        layout.separator()
        layout.operator("pribambase.sprite_reload_all")
        layout.separator()
        layout.operator("pribambase.reference_reload_all")
        layout.operator("pribambase.reference_freeze_all").invert = False
        layout.operator("pribambase.reference_freeze_all", text="Unlock All References").invert = True
        layout.separator()
        layout.operator("pribambase.preferences", icon='PREFERENCES')


