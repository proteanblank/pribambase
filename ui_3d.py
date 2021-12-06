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

import math
import bpy
import numpy as np
from math import pi
from mathutils import Matrix
from bpy_extras import object_utils

from .addon import addon
from . import util


def prescale(image:bpy.types.Image):
    """Scale image in-place without filtering"""

    if image.sb_props.prescale_size[0] < 1:
        image.sb_props.prescale_size = image.size

    w, h = image.size
    scale = image.sb_props.prescale
    presize = image.sb_props.prescale_size
    desample = max(w // presize[0], 1)
    px = np.array(image.pixels, dtype=np.float32)
    px.shape = (h, w, 4)

    if desample != h // presize[1]:
        raise ValueError("The image is unevenly scaled")

    if desample == scale:
        # already scaled as we want it to
        return
    elif desample > 1:
        px = px[::desample,::desample,:]
    px = px.repeat(scale, 1).repeat(scale, 0)

    image.scale((w // desample) * scale, (h // desample) * scale)
    try:
        # version >= 2.83
        image.pixels.foreach_set(px.ravel())
    except AttributeError:
        # version < 2.83
        image.pixels[:] = px.ravel()
    image.update()


# Pretty annoying but Add SPrite operator should incorporate material creation/assignment, so goo portion of material setup will live outside the operator
_material_sprite_common_props = {    
    "two_sided": bpy.props.BoolProperty(
        name="Two-Sided",
        description="Make both sided of each face visible",
        default=False),
    
    "sheet": bpy.props.BoolProperty(
        name="Animated",
        description="Use spritesheet image in the material. Use when UV animation is set up, or will be.",
        default=True),

    "blend": bpy.props.EnumProperty(name="Blend Mode", description="Imitate blending mode for the material", items=(
        ('NORM', "Normal", "", 0),
        ('ADD', "Additive", "", 1),
        ('MUL', "Multply", "", 2)), 
        default='NORM')}


def _draw_material_props(self:bpy.types.Operator, layout:bpy.types.UILayout):
    img = addon.state.op_props.image_sprite
    if img and img.sb_props.sheet:
        layout.prop(self, "sheet")
    layout.prop(self, "two_sided")
    layout.prop(self, "blend")


class SB_OT_material_add(bpy.types.Operator):
    bl_idname = "pribambase.material_add"
    bl_label = "Create Pixel Material"
    bl_description = "Quick pixel material setup"
    bl_options = {'REGISTER', 'UNDO'}

    shading: bpy.props.EnumProperty(name="Shading", description="Material",
        items=(
            ('LIT', "Lit", "Basic material that receives lighting", 1), 
            ('SHADELESS', "Shadeless", "Emission material that works without any lighting in the scene", 2)), 
        default='LIT')

    sheet: _material_sprite_common_props["sheet"]
    two_sided: _material_sprite_common_props["two_sided"]
    blend: _material_sprite_common_props["blend"]


    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        row = layout.row()
        row.enabled = self.invoke
        row.prop(addon.state.op_props, "image_sprite")
        layout.row().prop(self, "shading", expand=True)
        _draw_material_props(self, layout)


    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH' and not context.active_object.active_material \
            and next((True for i in bpy.data.images if not i.sb_props.is_sheet), False)
    

    def execute(self, context):
        self.invoke = False
        
        img = addon.state.op_props.image_sprite
        if not img:
            self.report({'ERROR'}, "No image selected")
            return {'CANCELLED'}
        
        if img.sb_props.sheet and self.sheet:
            img = img.sb_props.sheet

        mat = bpy.data.materials.new(addon.state.op_props.image_sprite.name)
        # create nodes
        mat.use_nodes = True
        mat.use_backface_culling = not self.two_sided
        mat.blend_method = 'CLIP'
        
        tree = mat.node_tree

        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.location = (-500, 100)
        tex.image = img
        tex.interpolation = 'Closest'
        tex.extension = 'CLIP'

        bsdf = tree.nodes[tree.nodes.find("Principled BSDF")]
        bsdf.location = (-200, 250)
        bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)

        if self.shading == 'LIT':
            tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        elif self.shading == 'SHADELESS':
            bsdf.inputs["Specular"].default_value = 0
            tree.links.new(tex.outputs["Color"], bsdf.inputs["Emission"])
        tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])

        out = tree.nodes[tree.nodes.find("Material Output")]
        out.location = (300, 50)

        if self.blend == 'ADD':
            mat.blend_method = 'BLEND'
            trans = tree.nodes.new("ShaderNodeBsdfTransparent")
            trans.location = (80, 100)
            add = tree.nodes.new("ShaderNodeAddShader")
            add.location = (130, -100)
            tree.links.new(trans.outputs["BSDF"], add.inputs[0])
            tree.links.new(bsdf.outputs["BSDF"], add.inputs[1])
            tree.links.new(add.outputs["Shader"], out.inputs["Surface"])

        elif self.blend == 'MUL':
            mat.blend_method = 'BLEND'
            tree.nodes.remove(bsdf)
            trans = tree.nodes.new("ShaderNodeBsdfTransparent")
            trans.location = (0, -20)
            tree.links.new(tex.outputs["Color"], trans.inputs["Color"])
            tree.links.new(trans.outputs["BSDF"], out.inputs["Surface"])        

        context.active_object.active_material = mat
        return {'FINISHED'}


    def invoke(self, context, event):
        self.invoke = True
        addon.state.op_props.image_sprite = next(i for i in bpy.data.images if not i.sb_props.is_sheet)
        return context.window_manager.invoke_props_dialog(self)


class SB_OT_sprite_add(bpy.types.Operator):
    bl_idname = "pribambase.sprite_add"
    bl_label = "Add Sprite"
    bl_description = "All-in-one 2D sprite setup"
    bl_options = {'REGISTER', 'UNDO'}

    scale: bpy.props.FloatProperty(
        name="Texture Density", 
        description="In pixels per unit. Defaults to 1 pixel per 1 world grid step")

    pivot: bpy.props.FloatVectorProperty(
        name="Pivot",
        description="Placement of the origin in the texture space. (X:0, Y:0) is lower-left, (X:0.5, Y:0) is lower-middle, and so on",
        size=2,
        subtype='XYZ',
        default=(0.5,0.5))
    
    pivot_relative: bpy.props.BoolProperty(
        name="Relative Pivot Coordinates",
        description="If checked, pivot position is interpreted as UV coordinate (0 to 1), otherwise as pixels",
        default=True)
    
    facing: bpy.props.EnumProperty(
        name="Facing",
        description="Sprite orientation, follows the opposite naming to camera shortcuts, so e.g. picking Top means the sprite will be facing Top camera view",
        items=(
            ('YNEG', "Front", "Negative Y axis"),
            ('YPOS', "Back", "Positive Y axis"),
            ('XNEG', "Left", "Negative X axis"),
            ('XPOS', "Right", "Positive X axis"),
            ('ZPOS', "Top", "Positive Z axis"),
            ('ZNEG', "Bottom", "Negative Z axis"),
            ('SPH', "Camera", "Face the selected object, usually camera, from any angle (AKA spherical billboard)"),
            ('CYL', "Camera XY", "Face the selected object by rotating around Z axis only (AKA cylindrical billboard)")),
        default='YNEG')

    shading: bpy.props.EnumProperty(name="Shading", description="Material",
        items=(
            ('NONE', "None", "Do not create material", 0),
            ('LIT', "Lit", "Basic material that receives lighting", 1), 
            ('SHADELESS', "Shadeless", "Emission material that works without any lighting in the scene", 2)), 
        default='LIT')

    ## MATERIAL PROPS
    sheet: _material_sprite_common_props["sheet"]
    two_sided: _material_sprite_common_props["two_sided"]
    blend: _material_sprite_common_props["blend"]

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        
        layout.label(text="Sprite")
        row = layout.row(align=True)
        row.enabled = self.invoke
        row.prop(addon.state.op_props, "image_sprite")
        if not addon.state.op_props.image_sprite:
            row.label(text="", icon='ERROR')

        layout.prop(self, "facing")
        if self.facing in ('SPH', 'CYL'):
            row = layout.row()
            row.enabled = self.invoke
            row.prop(addon.state.op_props, "look_at")
        layout.prop(self, "scale")
        layout.prop(self, "pivot")
        layout.prop(self, "pivot_relative", text="Relative")
        
        layout.label(text="Material")
        layout.row().prop(self, "shading", expand=True)
        if self.shading != 'NONE':
            _draw_material_props(self, layout)


    @classmethod
    def poll(cls, context):
        return next((True for i in bpy.data.images if not i.sb_props.is_sheet), False)
    

    def execute(self, context):
        self.invoke = False
        img = addon.state.op_props.image_sprite
        if not img:
            self.report({'ERROR'}, "No image selected")
            return {'CANCELLED'}
        w,h = img.size
        # normalize to pixel coord
        px, py = [self.pivot[i] * img.size[i] if self.pivot_relative else self.pivot[i] for i in (0,1)]
        px = w - px

        # start with 2d uv coords, scaled to pixels
        points = []
        for u,v in [(w - px, -py), (-px, -py), (-px, h - py), (w - px, h - py)]:
            # scale to grid, flip if needed
            f = -1 if self.facing in ('XPOS', 'YNEG', 'ZPOS', 'SPH', 'CYL') else 1
            u = u * f / self.scale
            v = v / self.scale
            # now add third coord
            if self.facing in ('XPOS', 'XNEG'):
                points.append((0, u, v))
            elif self.facing in ('YPOS', 'YNEG', 'SPH', 'CYL'):
                points.append((u, 0, v))
            elif self.facing == 'ZPOS':
                points.append((u, v, 0))
            elif self.facing == 'ZNEG':
                points.append((-u, -v, 0))

        mesh = bpy.data.meshes.new("Plane")
        mesh.from_pydata( # this will be z up?
            vertices=points,
            edges=[(0, 1),(1, 2),(2, 3),(3, 0)],
            faces=[(0, 1, 2, 3)])
        mesh.uv_layers.new().data.foreach_set("uv", [0, 0, 1, 0, 1, 1, 0, 1])

        obj = object_utils.object_data_add(context, mesh, name="Sprite")
        if self.shading != 'NONE':
            bpy.ops.pribambase.material_add(shading=self.shading, two_sided=self.two_sided, blend=self.blend)
        
        if img.sb_props.sheet:
            addon.state.op_props.animated_sprite = img
            bpy.ops.pribambase.spritesheet_rig()

        if self.facing in ('SPH', 'CYL'):
            # Face camera
            face:bpy.types.TrackToConstraint = obj.constraints.new('TRACK_TO')
            face.track_axis = 'TRACK_NEGATIVE_Y'
            face.up_axis = 'UP_Z'
            face.target = addon.state.op_props.look_at

            if self.facing == 'CYL':
                # For cylindric, also constrain rotation
                lock = obj.constraints.new('LIMIT_ROTATION')
                lock.use_limit_x = True
                lock.use_limit_y = True

        return {'FINISHED'}


    def invoke(self, context, event):
        addon.state.op_props.image_sprite = None
        addon.state.op_props.look_at = context.scene.camera
        self.scale = 1 / context.space_data.overlay.grid_scale
        self.sheet = addon.state.op_props.image_sprite is not None and addon.state.op_props.image_sprite.sb_props.sheet is not None
        self.invoke = True

        return context.window_manager.invoke_props_dialog(self)


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
            self.report({'INFO'}, "The reference won't be selectable. Use the outliner to reload/delete it")
        
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
    bl_description = "Refresh reference scaling without reloading the image."
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
    bl_description = "Replace reference image, keep it aligned to pixel grid."
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


_uv_map_enum_items_ref = None
def _uv_map_enum_items(self, context):
    # enum items reference must be stored to avoid crashing the UI
    global _uv_map_enum_items_ref
    if context is None:
        _uv_map_enum_items_ref = []
    else: 
        _uv_map_enum_items_ref = [("__none__", "", "", 0)] + [(layer.name, layer.name, "", i + 1) for i,layer in enumerate(context.active_object.data.uv_layers)]
    return _uv_map_enum_items_ref
    
class SB_OT_spritesheet_rig(bpy.types.Operator):
    bl_idname = "pribambase.spritesheet_rig"
    bl_label = "Set Up Animation"
    bl_description = "Set up spritesheet UV animation for this object. Does not assign materials or textures"
    bl_options = {'UNDO'}

    uv_map: bpy.props.EnumProperty(
        name="UV Layer",
        description="UV Layer that transforms apply to",
        items=_uv_map_enum_items)
    
    update_nodes: bpy.props.BoolProperty(
        name="Update Image Nodes",
        description="Replace the image with spritesheet in Image Texture nodes of the object's material, if there's any",
        default=True)


    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(addon.state.op_props, "animated_sprite")
        layout.prop(self, "uv_map")
        layout.prop(self, "update_nodes")
    

    @classmethod
    def poll(self, context):
        # need a mesh to store modifiers these days
        return context.active_object and context.active_object.type == 'MESH' and context.active_object.select_get() and next((img for img in bpy.data.images if img.sb_props.sheet), False)  


    def execute(self, context):
        if bpy.app.version < (2, 83):
            self.report({'ERROR'}, "UVWarp transforms needed for animation are not supported in your blender version. Has to be 2.83 or newer.")
            return {'CANCELLED'}

        obj = context.active_object
        img = addon.state.op_props.animated_sprite
        if not img:
            self.report({'ERROR'}, "No sprite selected")
            return {'CANCELLED'}
        start = img.sb_props.sheet.sb_props.sheet_start

        # Uniqualize the name in case there's already one from the same sprite
        default_prop = f"Frame {img.name}" # this is the name that generated actions use by default
        prop_name = util.unique_name(default_prop, obj)
        prop_path = f'["{prop_name}"]'

        if prop_name != default_prop:
            self.report({'WARNING'}, "Several animations of this object use the same sprite. Change FCurves' channel to the object property with the name of the desired modifier")

        anim = obj.sb_props.animations_new(util.unique_name("FrameAnim", obj.sb_props.animations))
        anim.image = img
        anim.prop_name = prop_name
        obj.sb_props.animation_index = obj.sb_props.animations.find(anim.name)

        # custom property
        if prop_name not in obj:
            obj[prop_name] = start

        try:
            # 3.0
            obj.id_properties_ui(prop_name).update(description="Animation frame, uses the same numbering as timeline in Aseprite")
        except AttributeError:
            # 2.[8/9]x
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

        # revive the curves if needed
        if obj.animation_data and obj.animation_data.action:
            for fcurve in obj.animation_data.action.fcurves:
                if fcurve.data_path == prop_path:
                    # It seems there's no way to clear FCURVE_DISABLED flag directly from script
                    # Seems that changing the path does that as a side effect
                    fcurve.data_path += ""
                    fcurve.update()

        obj.animation_data.drivers.update()
        obj.update_tag()

        # try updating the material
        if self.update_nodes and obj.active_material and obj.active_material.use_nodes:
            for node in obj.active_material.node_tree.nodes:
                if node.bl_idname == 'ShaderNodeTexImage' and node.image == img:
                    node.image = img.sb_props.sheet

        util.refresh()

        return {'FINISHED'}


    def invoke(self, context, event):
        if not next((True for img in bpy.data.images if img.sb_props.sheet), False):
            self.report({'ERROR'}, "No animations in the current blendfile")
            return {'CANCELLED'}

        if not context.active_object.data.uv_layers:
            self.report({'ERROR'}, "THe object must have at least one UV map")
            return {'CANCELLED'}
        
        return context.window_manager.invoke_props_dialog(self)



class SB_OT_spritesheet_unrig(bpy.types.Operator):
    bl_idname = "pribambase.spritesheet_unrig"
    bl_label = "Clean Up"
    bl_description = "Remove modifier, drivers, and custom property created buy spritesheet UV animation"
    bl_options = {'UNDO'}

    @classmethod 
    def poll(self, context):
        try:
            context.active_object.sb_props.animations[context.active_object.sb_props.animation_index]
            return context.active_object.select_get()
        except (AttributeError, IndexError):
            return False
    
    def execute(self, context):
        obj = context.active_object
        anim = obj.sb_props.animations[obj.sb_props.animation_index]
        prop_name = anim.prop_name

        # drivers
        for driver in obj.animation_data.drivers:
            if driver.data_path == f'modifiers["{prop_name}"].offset':
                obj.animation_data.drivers.remove(driver)

        # custom property
        try:
            # 3.0+
            obj.id_properties_ui(prop_name).clear()
        except AttributeError:
            # 2.[8/9]x
            if "_RNA_UI" in obj and prop_name in obj["_RNA_UI"]:
                del obj["_RNA_UI"][prop_name]

        if prop_name in obj:
            del obj[prop_name]

        # modifier
        if prop_name in obj.modifiers:
            obj.modifiers.remove(obj.modifiers[prop_name])
        
        # animation
        obj.sb_props.animations_remove(anim)

        return {'FINISHED'}


action = ""
msgbus_anim_data_callback_owner = object()
def sb_msgbus_anim_data_callback():
    global action
    scene = bpy.context.scene
    obj = addon.state.action_preview

    if not scene.use_preview_range or not obj:
        bpy.msgbus.clear_by_owner(msgbus_anim_data_callback_owner)
        return

    if obj.animation_data.action != action:
        action = obj.animation_data.action.name
        scene.frame_preview_start, scene.frame_preview_end = addon.state.action_preview.animation_data.action.frame_range
        # try to revive the curves
        for fcurve in obj.animation_data.action.fcurves:
            fcurve.data_path += ""


class SB_OT_set_action_preview(bpy.types.Operator):
    bl_idname = "pribambase.set_action_preview"
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

        bpy.msgbus.clear_by_owner(msgbus_anim_data_callback_owner) # try to unsub in case we're changing the object
        bpy.msgbus.subscribe_rna(
            key=bpy.context.active_object.animation_data,
            owner=msgbus_anim_data_callback_owner,
            args=tuple(),
            notify=sb_msgbus_anim_data_callback,
            options={'PERSISTENT'})

        return {'FINISHED'}



class SB_OT_clear_action_preview(bpy.types.Operator):
    bl_idname = "pribambase.clear_action_preview"
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
        bpy.msgbus.clear_by_owner(msgbus_anim_data_callback_owner)
        return {'FINISHED'}


class SB_OT_set_grid(bpy.types.Operator):
    bl_idname = "pribambase.set_grid"
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



class SB_UL_animations(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon = 'BLANK1' if item.is_intact() else 'ERROR')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='DECORATE_LINKED')


class SB_PT_panel_animation(bpy.types.Panel):
    bl_idname = "SB_PT_panel_animation"
    bl_label = "Sprite"
    bl_category = "Item"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 476


    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'


    def draw(self, context):        
        if context.active_object and context.active_object.type == 'MESH':
            layout = self.layout
            obj = context.active_object
            
            if not obj.active_material:
                layout.row().operator("pribambase.material_add", icon='ADD')

            layout.row().label(text="Animation:")

            # Info
            row = layout.row()
            row.alignment = 'CENTER'
            if next((False for img in bpy.data.images if img.sb_props.sheet), True):
                row.label(text="No synced sprites have animations", icon='INFO')
            elif not obj.sb_props.animations:
                row.label(text="Press \"+\" to set up 2D animation", icon='INFO')
            row = layout.row()
            row.column().template_list("SB_UL_animations", "", obj.sb_props, "animations", obj.sb_props, "animation_index", rows=1)

            col = row.column(align=True)
            col.operator("pribambase.spritesheet_rig", icon='ADD', text="")
            col.operator("pribambase.spritesheet_unrig", icon='REMOVE', text="")

            try:
                anim = obj.sb_props.animations[obj.sb_props.animation_index]
                prop_name = anim.prop_name

                if not next((True for driver in obj.animation_data.drivers if driver.data_path == f'modifiers["{prop_name}"].offset'), False):
                    layout.row().label(text="Driver(s) were removed or renamed", icon='ERROR')
                elif prop_name not in obj.modifiers:
                    layout.row().label(text="UVWarp modifier was removed or renamed", icon='ERROR')
                elif prop_name not in obj:
                    layout.row().label(text="Object property was removed or renamed", icon='ERROR')
                else:
                    layout.row().prop(obj, f'["{prop_name}"]', text="Frame", expand=False)

            except IndexError:
                pass # no selected animation

            row = layout.row(align=True)
            row.enabled = bool(obj.animation_data)

            sub = row.column()
            sub.enabled = bool(obj.sb_props.animations and obj.sb_props.animation_index > -1)
            sub.prop(obj.sb_props, "animation_tag_setter")
            
            if addon.state.action_preview_enabled:
                active_picked = (context.active_object == addon.state.action_preview)
                row.operator("pribambase.set_action_preview", icon='EYEDROPPER', text="", depress=active_picked)
                row.operator("pribambase.clear_action_preview", icon='PREVIEW_RANGE', text="", depress=True)
            else:
                row.operator("pribambase.set_action_preview", icon='PREVIEW_RANGE', text="")


class SB_PT_panel_reference(bpy.types.Panel):
    bl_idname = "SB_PT_panel_reference"
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

        if bpy.app.version < (2, 81):
            icon = 'NONE' # :\

        row.label(text=status, icon=icon)

        row = row.row(align=True)
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.stop_server", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("pribambase.start_server", text="Connect", icon="DECORATE_LINKED")
        row.menu("SB_MT_global", icon='DOWNARROW_HLT', text="")


class SB_MT_global(bpy.types.Menu):
    bl_label = "Pribambase"
    bl_idname = "SB_MT_global"

    def draw(self, context):
        layout = self.layout
        layout.operator("pribambase.set_grid")
        layout.separator()
        layout.operator("pribambase.reference_reload_all")
        layout.operator("pribambase.reference_freeze_all").invert = False
        layout.operator("pribambase.reference_freeze_all", text="Unlock All References").invert = True
        layout.separator()
        layout.operator("pribambase.preferences", icon='PREFERENCES')


def menu_reference_add(self, context):
    self.layout.operator("pribambase.reference_add", text="Pixel Reference", icon='ALIASED')

def menu_mesh_add(self, context):
    self.layout.operator("pribambase.sprite_add", text="Sprite", icon='ALIASED')