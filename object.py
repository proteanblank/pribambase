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
Working with objects (mesh, material, sprites, ...)
"""

import bpy
from bpy_extras import object_utils
import os.path

from .messaging import encode
from .addon import addon
from .image import SB_OT_sprite_open
from . import util
from . import modify
from . import ase


# Pretty annoying but Add SPrite operator should incorporate material creation/assignment, so goo portion of material setup will live outside the operator
_material_sprite_common_props = {    
    "two_sided": bpy.props.BoolProperty(
        name="Two-Sided",
        description="Make both sided of each face visible",
        default=False),
    
    "sheet": bpy.props.BoolProperty(
        name="Animated",
        description="Use spritesheet image in the material. Use when UV animation is set up, or will be",
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


class SB_OT_plane_add(bpy.types.Operator):
    bl_idname = "pribambase.plane_add"
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
    
    ## FILE DIALOG
    from_file: bpy.props.BoolProperty("Open File", options={'HIDDEN'})
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    relative: bpy.props.BoolProperty(name="Relative Path", description="Select the file relative to blend file")
    # dialog settings
    filter_glob: bpy.props.StringProperty(default="*.ase;*.aseprite;*.bmp;*.jpeg;*.jpg;*.png", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    ## MATERIAL PROPS
    sheet: _material_sprite_common_props["sheet"]
    two_sided: _material_sprite_common_props["two_sided"]
    blend: _material_sprite_common_props["blend"]

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        
        if not self.from_file:
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
    def poll(self, context):
        return next((True for i in bpy.data.images if not i.sb_props.is_sheet), False)
    

    def execute(self, context):
        self.invoke = False

        if self.from_file:
            if self.filepath.endswith(".ase") or self.filepath.endswith(".aseprite"):
                # ase files
                # TODO should work without connection
                SB_OT_sprite_open.execute(self, context)
                addon.state.op_props.image_sprite = next(i for i in bpy.data.images if i.sb_props.source_abs == self.filepath)
                size, _ = ase.info(self.filepath)
                addon.state.op_props.image_sprite.scale(*size)
            else:
                # blender supported
                addon.state.op_props.image_sprite = bpy.data.images.load(self.filepath)
            # TODO animation

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

        if self.from_file:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        else:
            return context.window_manager.invoke_props_dialog(self)


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
            self.report({'ERROR'}, "UVWarp transforms needed for animation are not supported in your blender version. Has to be 2.83 or newer")
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
            obj["_RNA_UI"][prop_name] = { "description": "Animation frame, uses the same numbering as timeline in Aseprite"}

        # modifier
        if prop_name not in obj.modifiers:
            obj.modifiers.new(prop_name, "UV_WARP")
        
        uvwarp = obj.modifiers[prop_name]
        uvwarp.uv_layer = "" if self.uv_map == "__none__" else self.uv_map
        uvwarp.center = (0.0, 1.0)
        
        modify.sheet_animation(anim)

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
            if obj.active_material.users > 1:
                # duplicate the mat so it doesn't break the rest of the objects using it
                mat_name = obj.active_material.name + " *Sheet*"
                if mat_name not in bpy.data.materials:
                    mat = obj.active_material.copy()
                    mat.name = mat_name
                obj.active_material = bpy.data.materials[mat_name]

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
            self.report({'ERROR'}, "The object must have at least one UV map")
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


def menu_mesh_add(self, context):
    self.layout.operator("pribambase.plane_add", text="Sprite", icon='ALIASED').from_file = False
    self.layout.operator("pribambase.plane_add", text="Sprite (File)", icon='ALIASED').from_file=True