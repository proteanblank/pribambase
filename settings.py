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
import secrets
import os.path

from .addon import addon
from . import util


def get_identifier(self):
    if bpy.data.filepath:
        return bpy.data.filepath

    if "_identifier" not in self:
        self["_identifier"] = secrets.token_hex(4) # 8 chars should be enough?

    return self["_identifier"]


class SB_OpProps(bpy.types.PropertyGroup):
    """Workaround for operators not having pointer properties. Instead, they draw this group's props"""

    # used by: SB_OT_sprite_add
    look_at: bpy.props.PointerProperty(
        name="Look At",
        description="Object the sprite will be facing",
        type=bpy.types.Object)

    # used by: SB_OT_sprite_add, SB_OT_material_add
    image_sprite: bpy.props.PointerProperty(
        name="Image", 
        description="Image to use",
        type=bpy.types.Image,
        poll=lambda self,img:not img.sb_props.is_sheet)
    
    # used by: SB_OT_sprite_add
    material: bpy.props.PointerProperty(
        name="Material",
        description="Material to use. If none, a new one can be created",
        type=bpy.types.Material)


class SB_State(bpy.types.PropertyGroup):
    """Pribambase file-related data"""
    identifier: bpy.props.StringProperty(
        name="Identifier",
        description="Unique but not permanent id for the current file. Prevents accidentally syncing textures from another file",
        get=get_identifier)
    
    action_preview: bpy.props.PointerProperty(
        name="Action Preview",
        description="For locking timeline preview range",
        type=bpy.types.Object,
        poll=lambda self, object : object is None or object.type == 'MESH')
    
    action_preview_enabled: bpy.props.BoolProperty(
        name="Action Preview",
        description="Lock timeline preview range to action length")

    op_props: bpy.props.PointerProperty(type=SB_OpProps, options={'HIDDEN', 'SKIP_SAVE'})


class SB_SheetAnimation(bpy.types.PropertyGroup):
    """Pribambase spritesheet animation. Use `object.sb_props.animation_new` to create them with unique names (adds .001 etc)"""
    # use anim.name for an identifier
    # use anim.id_data to get the animated object

    image: bpy.props.PointerProperty(
        name="Sprite",
        description="Image for the sprite the animation came from",
        type=bpy.types.Image)
    
    prop_name: bpy.props.StringProperty(
        name="Prop Name",
        description="Name of the object property for the frame")

    def is_intact(self):
        """Check that none of the rig pieces were removed (usually, by the user)"""
        try:
            prop_name = self.prop_name
            obj = self.id_data
            mod_datapath = f'modifiers["{prop_name}"].offset'
            
            # two driver curves
            assert len([True for driver in obj.animation_data.drivers if driver.data_path == mod_datapath]) >= 2

            # custom property
            assert prop_name in obj
            try:
                # seems like in 3.0+ this part is managed automatically, and we just asserted the property
                # so this just checks if fallback is needed
                obj.id_properties_ui(prop_name)
            except AttributeError:
                # v2.[8/9]x, there's no manager so need to check with available methods
                assert "_RNA_UI" in obj
                assert prop_name in obj["_RNA_UI"]

            # modifier
            assert prop_name in obj.modifiers
        except AssertionError:
            return False
        return True


class SB_ObjectProperties(bpy.types.PropertyGroup):
    animations: bpy.props.CollectionProperty(
        name="Animations",
        description="Store animations the object uses, to sync or remove",
        type=SB_SheetAnimation,
        options={'HIDDEN'})
    
    animation_index: bpy.props.IntProperty(
        name="Animation Index",
        description="List index of the animation selected. For UI purposes",
        options={'HIDDEN', 'SKIP_SAVE'})


    def animations_new(self, name:str) -> SB_SheetAnimation:
        item = self.animations.add()
        item.name = util.unique_name(name, self.animations)
        return item


    def animations_remove(self, item):
        idx = self.animations.find(item.name)
        assert idx > -1, "Item not in the collection"
        self.animations.remove(idx)



class SB_ImageProperties(bpy.types.PropertyGroup):
    """Pribambase image-related data"""

    source: bpy.props.StringProperty(
        name="Sprite",
        description="The file from which the image was created, and that will be synced with this image",
        subtype='FILE_PATH')

    prescale: bpy.props.IntProperty(
        name="Pre-scale",
        description="",
        min=1,
        max=20,
        default=1)

    prescale_actual: bpy.props.IntProperty(
        name="Actual Pre-scale",
        description="Pre-scale value during the last resize operation",
        min=1,
        max=20,
        default=1, 
        options={'HIDDEN'})
    
    source_abs:bpy.props.StringProperty(
        name="Sprite Path",
        description="Absolute and normalized source path, or an empty string if it's empty. Should be used to look up the images.",
        subtype='FILE_PATH',
        get=lambda self: os.path.normpath(bpy.path.abspath(self.source)) if self.source and self.source.startswith("//") else self.source)

    sheet: bpy.props.PointerProperty(
        name="Sheet",
        description="Spritesheet that stores animation frames",
        type=bpy.types.Image)

    frame: bpy.props.IntProperty(
        name="Frame Number",
        description="Index of the image in the spritesheet. Starts at 0",
        options={'HIDDEN'})

    sync_flags: bpy.props.EnumProperty(
        name="Sync Flags",
        description="Sync related flags passed to Aseprite with texture list",
        items=(("SHEET", "All Frames", "Send all frames via spritesheet"),),
        options={'ENUM_FLAG'})

    # Spritesheet-specific props
    is_sheet: bpy.props.BoolProperty(
        name="Spritesheet",
        description="Flag if the image is a spritesheet",
        default=False)
    
    animation_length: bpy.props.IntProperty(
        name="Animation Length",
        description="Number of frames in the Aseprite's timeline. Can be higher than the number of frames in the spritesheet due to repeats",
        default=1)

    sheet_size: bpy.props.IntVectorProperty(
        name="Size",
        description="Spritesheed size in frames",
        subtype='COORDINATES',
        size=2,
        default=(1, 1),
        min=1)
        
    sheet_start: bpy.props.IntProperty(
        name="Start",
        description="First frame number",
        options={'HIDDEN'})

    
    def source_set(self, source, relative:bool=None):
        """
        Set source as relative/absolute path according to relative path setting. Use every time when assigning sources automatically, 
        and never for user interaction. If relative is not specified but possible, it's picked automatically based on blender prefs."""
        if not source:
            self.source = ""
        elif (relative or (relative is None and addon.prefs.use_relative_path)) and bpy.data.filepath: # need to check for None explicitly because bool
            self.source = bpy.path.relpath(source)
        else:
            self.source = os.path.normpath(source)


class SB_ActionProperties(bpy.types.PropertyGroup):
    """Pribambase action-related data"""
    
    sprite: bpy.props.PointerProperty(
        name="Sprite",
        description="Image for the sprite the action came from",
        type=bpy.types.Image)

    tag: bpy.props.StringProperty(
        name="Tag",
        description="Corresponding tag on Asperite timeline")


class SB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: bpy.props.IntProperty(
        name="Port",
        description="Port used by the websocket server. Aseprite plugin must have the same value to connect",
        default=34613,
        min=1025,
        max=65535)

    localhost: bpy.props.BoolProperty(
        name="Only Local Connections",
        description="Only accept connections from localhost (127.0.0.1)",
        default=True)

    autostart: bpy.props.BoolProperty(
        name="Start Automatically",
        description="Set up the connection when Blender starts. Enabling increases blender's launch time",
        default=False)

    uv_layer:bpy.props.StringProperty(
        name="UV Layer Name",
        description="Name of the reference layer that will be created/used to display the UVs in Aseprite",
        default="UVMap")

    uv_scale:bpy.props.FloatProperty(
        name="UV Scale",
        description="Default resolution of the UV layer relative to the texture size",
        default=8.0,
        min=0.0,
        max=50.0)

    uv_color: bpy.props.FloatVectorProperty(
        name="UV Color",
        description="Default color to draw the UVs with",
        size=4,
        default=(0.0, 0.0, 0.0, 0.45),
        min=0.0,
        max=1.0,
        subtype='COLOR')

    uv_aa: bpy.props.BoolProperty(
        name="Anti-aliased UVs",
        description="Apply anti-aliasing to the UV map",
        default=True)

    uv_weight: bpy.props.FloatProperty(
        name="UV Thickness",
        description="Default thickness of the UV map with scale appied. For example, if `UV scale` is 2 and thickness is 3, the lines will be 1.5 pixel thick in aseprite",
        default=4.0)

    use_relative_path: bpy.props.BoolProperty(
        name="Relative Paths",
        description="Changes how the file paths are stored. The addon stays consistent with Blender behavior, which can be changed in \"Preferences > Save & Load\"",
        get=lambda self: bpy.context.preferences.filepaths.use_relative_paths)

    skip_modal: bpy.props.BoolProperty(
        name="No modal timers",
        description="Change the way the changes are applied to blender data. Degrades the experience but might fix some crashes",
        default=False)
    
    whole_frames: bpy.props.BoolProperty(
        name="Round Fractional Frames",
        description="When sprite timings do not match the scene framerate, move keyframes to the nearest whole frame. Otherwise, use fractional frames to preserver timing",
        default=True)


    def template_box(self, layout, label="Box"):
        row = layout.row().split(factor=0.15)
        row.label(text=label)
        return row.box()


    def draw(self, context):
        layout = self.layout

        box = self.template_box(layout, label="UV Map:")

        box.row().prop(self, "uv_layer", text="Layer Name")
        box.row().prop(self, "uv_color")

        row = box.row()
        row.prop(self, "uv_scale", text="Scale")
        row.prop(self, "uv_weight", text="Thickness")
        row.prop(self, "uv_aa", text="Anti-aliasing")

        box = self.template_box(layout, label="Connection:")

        box.row().prop(self, "autostart")

        row = box.row()
        row.enabled = not addon.server_up
        row.prop(self, "localhost")
        row.prop(self, "port")

        if addon.server_up:
            box.row().operator("pribambase.stop_server")
        else:
            box.row().operator("pribambase.start_server")

        box = self.template_box(layout, label="Misc:")

        box.row().prop(self, "use_relative_path")
        box.row().prop(self, "whole_frames")
        box.row().prop(self, "skip_modal")


class SB_OT_preferences(bpy.types.Operator):
    bl_idname = "pribambase.preferences"
    bl_label = "Preferences"
    bl_description = "Open this addon's settings"

    def execute(self, context):
        bpy.ops.preferences.addon_show(module=__package__)

        return {'FINISHED'}


def migrate():
    """Move image props created by older versions to the property group"""

    for img in bpy.data.images:
        if "sb_source" in img:
            # copy without source_set here as we don't know how and why it was assigned
            img.sb_props.source = img["sb_source"]
            del img["sb_source"]

        if "sb_scale" in img:
            img.sb_props.prescale = img["sb_scale"]
            del img["sb_scale"]