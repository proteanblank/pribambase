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
Reference related stuff.
"""

import math
import bpy
from math import pi
from mathutils import Matrix

from .modify import prescale

class SB_OT_reference_add(bpy.types.Operator):
    bl_idname = "pribambase.reference_add"
    bl_label = "Add Reference"
    bl_description = "Add reference image with pixels aligned to the view grid"
    bl_options = {'REGISTER', 'UNDO'}

    facing: bpy.props.EnumProperty(
        name="Facing",
        description="Image orientation, follows the opposite naming to camera shortcuts, so e.g. picking Top means the image will be facing Top camera view",
        items=(
            ('YNEG', "Front", "Negative Y axis"),
            ('YPOS', "Back", "Positive Y axis"),
            ('XNEG', "Left", "Negative X axis"),
            ('XPOS', "Right", "Positive X axis"),
            ('ZPOS', "Top", "Positive Z axis"),
            ('ZNEG', "Bottom", "Negative Z axis")),
        default='YNEG')

    scale: bpy.props.IntProperty(
        name="Pre-scale",
        description="Pre-scale the image",
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
        return not context.active_object or context.active_object.mode == 'OBJECT'


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


    def execute(self, context):
        image = bpy.data.images.load(self.filepath)
        w, h = image.size
        image.sb_props.prescale = self.scale
        prescale(image)

        bpy.ops.object.add(align='WORLD', rotation=(pi/2, 0, 0), location = (0, 0, 0))
        ref = context.active_object
        ref.data = image
        ref.empty_display_type = 'IMAGE'
        ref.use_empty_image_alpha = True
        ref.color[3] = self.opacity
        ref.empty_display_size = max(w, h) * context.space_data.overlay.grid_scale
        if not self.selectable:
            ref.hide_select = True
            self.report({'INFO'}, "The reference won't be selectable. Use the outliner to reload or delete it")
        
        if self.facing == 'YPOS':
            ref.matrix_basis @=  Matrix.Rotation(math.pi, 4, (0,1,0))
        elif self.facing == 'XNEG':
            ref.matrix_basis @=  Matrix.Rotation(math.pi/2, 4, (0,-1,0))
        elif self.facing == 'XPOS':
            ref.matrix_basis @=  Matrix.Rotation(math.pi/2, 4, (0,1,0))
        elif self.facing == 'ZPOS':
            ref.matrix_basis @=  Matrix.Rotation(math.pi/2, 4, (-1,0,0))
        elif self.facing == 'ZNEG':
            ref.matrix_basis @=  Matrix.Rotation(math.pi/2, 4, (1,0,0))

        return {'FINISHED'}


class SB_OT_reference_reload(bpy.types.Operator):
    bl_idname = "pribambase.reference_reload"
    bl_label = "Reload Reference"
    bl_description = "Reload reference while keeping it prescaled"
    bl_options = {'UNDO'}


    @classmethod
    def poll(self, context):
        return context.active_object and context.active_object.type == 'EMPTY' \
                and context.active_object.empty_display_type == 'IMAGE'


    def execute(self, context):
        image = context.active_object.data
        image.reload()
        image.sb_props.prescale_size = (-1, -1)
        prescale(image)

        return {'FINISHED'}


class SB_OT_reference_rescale(bpy.types.Operator):
    bl_idname = "pribambase.reference_rescale"
    bl_label = "Refresh Scale"
    bl_description = "Restore reference scaling without reloading the image"
    bl_options = {'UNDO'}


    @classmethod
    def poll(self, context):
        return context.active_object and context.active_object.type == 'EMPTY' \
                and context.active_object.empty_display_type == 'IMAGE'


    def execute(self, context):
        ref = context.active_object
        prescale(ref.data)
        return {'FINISHED'}


class SB_OT_reference_replace(bpy.types.Operator):
    bl_idname = "pribambase.reference_replace"
    bl_label = "Replace Reference"
    bl_description = "Replace reference image, keep it aligned to pixel grid"
    bl_options = {'UNDO'}

    scale: bpy.props.IntProperty(
        name="Pre-scale",
        description="Pre-scale the image",
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

    # dialog
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.bmp;*.png", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    @classmethod
    def poll(self, context):
        return context.active_object and context.active_object.type == 'EMPTY' \
            and context.active_object.empty_display_type == 'IMAGE'


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


    def execute(self, context):
        image = bpy.data.images.load(self.filepath)
        w, h = image.size
        image.sb_props.prescale = self.scale
        image.sb_props.prescale_size = (-1, -1)
        prescale(image)

        ref = context.active_object
        ref.data = image
        ref.use_empty_image_alpha = self.opacity < 1.0
        ref.color[3] = self.opacity
        ref.empty_display_size = max(w, h) * context.space_data.overlay.grid_scale

        return {'FINISHED'}


class SB_OT_reference_reload_all(bpy.types.Operator):
    bl_idname = "pribambase.reference_reload_all"
    bl_label = "Reload References"
    bl_description = "Reload all references (including non-pribamabase's), while keeping them prescaled"
    bl_options = {'UNDO'}

    def execute(self, context):
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE':
                image = obj.data
                image.reload()
                image.sb_props.prescale_size = (-1, -1)
                prescale(image)

        return {'FINISHED'}


class SB_OT_reference_freeze_all(bpy.types.Operator):
    bl_idname = "pribambase.reference_freeze_all"
    bl_label = "Lock All References"
    bl_description = "Make all references unselectabe (including non-pribamabase's)"
    bl_options = {'UNDO'}

    invert: bpy.props.BoolProperty(
        name="Invert",
        description="Make all references selectable instead")

    def execute(self, context):
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE':
                obj.hide_select = not self.invert

        return {'FINISHED'}


class SB_PT_reference(bpy.types.Panel):
    bl_idname = "SB_PT_reference"
    bl_label = "Reference"
    bl_category = "Item"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'EMPTY' and context.active_object.empty_display_type == 'IMAGE'


    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        img = obj.data
        layout.row().template_ID(obj, "data", unlink="object.unlink_data", open="pribambase.reference_replace")
        row = layout.row(align=True)
        row.operator("pribambase.reference_rescale", icon='FULLSCREEN_ENTER', text="Rescale")
        row.operator("pribambase.reference_reload", icon='FILE_REFRESH', text="Reload")
        if img:
            layout.row().prop(img.sb_props, "prescale")
        layout.row().prop(obj, "color", text="Opacity", index=3, slider=True)
        layout.row().prop(obj, "hide_select", toggle=False)


def menu_reference_add(self, context):
    self.layout.operator("pribambase.reference_add", text="Pixel Reference", icon='ALIASED')