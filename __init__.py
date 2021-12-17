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

# import wheel deps
import sys
import os.path as path
from glob import glob
thirdparty = path.join(path.dirname(__file__), "thirdparty", "*.whl")
sys.path += glob(thirdparty)

from bpy.app.handlers import persistent

from .async_loop import *
from .props import *
from .sync import *
from .image import *
from .ui import *
from .object import *
from .animation import *
from .reference import *
from .modify import *
from .util import *
from .addon import addon


bl_info = {
    "name": "Pribambase",
    "author": "lampysprites",
    "description": "Paint pixelart textures in Blender using Aseprite",
    "blender": (2, 80, 0),
    "version": (2, 1, 0),
    "category": "Paint"
}


classes = (
    # Property types
    SB_OpProps,
    SB_State,
    SB_Preferences,
    SB_SheetAnimation,
    SB_ObjectProperties,
    SB_ImageProperties,
    SB_ActionProperties,
    # Operators
    SB_OT_server_start,
    SB_OT_server_stop,
    SB_OT_uv_send,
    SB_OT_send_texture_list,
    SB_OT_sprite_open,
    SB_OT_sprite_new,
    SB_OT_sprite_edit,
    SB_OT_sprite_edit_copy,
    SB_OT_sprite_replace,
    SB_OT_sprite_make_animated,
    SB_OT_sprite_purge,
    SB_OT_material_add,
    SB_OT_plane_add,
    SB_OT_sprite_reload_all,
    SB_OT_reference_add,
    SB_OT_reference_replace,
    SB_OT_reference_rescale,
    SB_OT_reference_reload,
    SB_OT_reference_reload_all,
    SB_OT_reference_freeze_all,
    SB_OT_grid_set,
    SB_OT_update_image,
    SB_OT_update_spritesheet,
    SB_OT_update_frame,
    SB_OT_new_texture,
    SB_OT_action_preview_set,
    SB_OT_action_preview_clear,
    SB_OT_spritesheet_rig,
    SB_OT_spritesheet_unrig,
    SB_OT_preferences,
    SB_OT_report,
    # Lists
    SB_UL_animations,
    # Panels
    SB_PT_link,
    SB_PT_animation,
    SB_PT_sprite,
    SB_PT_reference,
    # Menus
    SB_MT_sprite,
    SB_MT_global
)


def parse_translations():
    translation = {}
    for csv in glob(os.path.join("translations", "*.csv")):
        with open(csv) as f:
            locale,_ = os.path.splitext(os.path.split(csv)[1])
            strings = translation[locale] = {}
            line_number = 0

            for line in f:
                line_number += 1
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    ctx, en, tr, *_ = line.split(";")
                    strings[ctx.rstrip(), en.strip()] = tr.strip()
                except ValueError:
                    print(f"Pribambase translation '{locale}' format error at line {line_number}:\n\t{line}")
    return translation


def register():
    async_loop.setup_asyncio_executor()

    bpy.app.translations.register(__name__, parse_translations())

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Scene.sb_state = bpy.props.PointerProperty(type=SB_State)
    bpy.types.Image.sb_props = bpy.props.PointerProperty(type=SB_ImageProperties)
    bpy.types.Action.sb_props = bpy.props.PointerProperty(type=SB_ActionProperties)
    bpy.types.Object.sb_props = bpy.props.PointerProperty(type=SB_ObjectProperties)

    try:
        editor_menus = bpy.types.IMAGE_MT_editor_menus
    except AttributeError:
        editor_menus = bpy.types.MASK_MT_editor_menus
    editor_menus.append(SB_MT_sprite.header_draw)

    bpy.types.VIEW3D_MT_image_add.append(menu_reference_add)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_mesh_add)

    # delay is just in case something else happens at startup
    # `persistent` protects the timer if the user loads a file before it fires
    bpy.app.timers.register(start, first_interval=0.5, persistent=True)


def unregister():
    if addon.server_up:
        addon.stop_server()

    if bpy.app.timers.is_registered(start):
        bpy.app.timers.unregister(start)

    if sb_on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(sb_on_load_post)

    if sb_on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(sb_on_load_pre)

    if sb_on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(sb_on_save_post)

    if sb_on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sb_on_depsgraph_update_post)

    try:
        editor_menus = bpy.types.IMAGE_MT_editor_menus
    except AttributeError:
        editor_menus = bpy.types.MASK_MT_editor_menus
    editor_menus.remove(SB_MT_sprite.header_draw)

    bpy.types.VIEW3D_MT_image_add.remove(menu_reference_add)
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_mesh_add)

    del bpy.types.Scene.sb_state
    del bpy.types.Image.sb_props
    del bpy.types.Action.sb_props
    del bpy.types.Object.sb_props

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    
    bpy.app.translations.unregister(__name__)


# hash for the set of image sources/names that is used to check if new images were added
_images_hv = 0


@persistent
def start():
    # hasn't been called for already loaded file
    sb_on_load_post(None)

    if sb_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(sb_on_load_post)

    if sb_on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(sb_on_load_pre)

    if sb_on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(sb_on_save_post)

    if sb_on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sb_on_depsgraph_update_post)


@persistent
def sb_on_load_post(scene):
    props.migrate()

    global _images_hv
    _images_hv = hash(frozenset(img.sb_props.sync_name for img in bpy.data.images))

    bpy.ops.pribambase.reference_reload_all()

    # these settings aren't supposed to persist but 'SKIP_SAVE' flag didn't do anyhitng so let's clear them manually if needed
    if addon.state.action_preview_enabled:
        bpy.context.scene.use_preview_range = False
    addon.state.action_preview = None
    addon.state.action_preview_enabled = False

    if addon.prefs.autostart:
        addon.start_server()


@persistent
def sb_on_load_pre(scene):
    if addon.server_up:
        addon.stop_server()


@persistent
def sb_on_save_post(scene):
    if addon.server_up:
        bpy.ops.pribambase.send_texture_list()


@persistent
def sb_on_depsgraph_update_post(scene):
    global _images_hv

    dg = bpy.context.evaluated_depsgraph_get()

    if dg.id_type_updated('IMAGE'):
        imgs = frozenset(img.sb_props.sync_name for img in bpy.data.images)
        hv = hash(imgs)

        if _images_hv != hv:
            _images_hv = hv
            if addon.server_up:
                lst = [(img.sb_props.sync_name, img.sb_props.sync_flags) for img in bpy.data.images]
                addon.server.send(encode.texture_list(addon.state.identifier, lst))
