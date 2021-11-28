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
import os
from os import path
import tempfile
import numpy as np
import re
import binascii
from typing import Collection, Tuple

from .addon import addon


def unique_name(name:str, collection:Collection[str]) -> str:
    """Imitate belnder behavior for ID names. Returns the name, possibly with a numeric suffix (e.g .001), so that it doesn't match any other strings in the collection"""
    assert name, "Name can not be empty"
    base, count = None, 0

    while name in collection:
        if not base: # do once
            # regexp always matches the first group
            base, suffix = re.match("^(.*?)(?:\.([0-9]{3}))?$", name).groups()
            count = int(suffix) if suffix else 0
        count += 1
        name = f"{base}.{count:03}"
    
    return name


def refresh():
    """Tag the ui for redrawing"""
    ctx = bpy.context
    if not ctx or not ctx.window_manager:
        return
    
    for win in ctx.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class ModalExecuteMixin:
    """
    bpy.types.Operator mixin that makes operator execute once via modal timer, allowing to modify 
    blender state from non-operator code with fewer surprizes. Uses a non-modal fallback for older
    versions. To use, define modal_execute(self, ctx) method
    """

    def modal_execute(self, context):
        raise NotImplementedError()

    def modal(self, context, event):
        if event.type == 'TIMER':
            context.window_manager.event_timer_remove(self.timer)
            self.modal_execute(context)
        return {'FINISHED'}

    def execute(self, context):
        if context and context.window and not addon.prefs.skip_modal:
            context.window_manager.modal_handler_add(self)
            self.timer = context.window_manager.event_timer_add(0.000001, window=context.window)
            return {'RUNNING_MODAL'}
        else:
            return self.modal_execute(context)


def image_name(img):
    fp = img.filepath
    name = img.name

    if img.sb_props.source:
        name = os.path.normpath(img.sb_props.source_abs)

    elif not img.packed_file and fp:
        name = os.path.normpath(bpy.path.abspath(fp) if fp.startswith("//") else fp)

    return name


_empty_png = binascii.a2b_base64('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=')
def pack_empty_png(image):
    """Load 1x1 ARGB png to the image and pack it"""
    # write the file
    tmp = path.join(tempfile.gettempdir(), "__sb__delete_me.png")
    with open(tmp, "wb", ) as f:
        f.write(_empty_png)

    image.filepath = tmp
    image.pack()
    image.filepath=""
    image.use_fake_user = True
    
    os.remove(tmp)


_update_image_args = None
def update_image(w, h, name, frame, pixels):
    # NOTE this operator removes animation flag from image
    global _update_image_args
    _update_image_args = w, h, name, frame, pixels
    bpy.ops.pribambase.update_image()

class SB_OT_update_image(bpy.types.Operator, ModalExecuteMixin):
    bl_idname = "pribambase.update_image"
    bl_label = "Update Image"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO_GROUPED', 'INTERNAL'}
    bl_undo_group = "pribambase.update_image"

    def modal_execute(self, context):
        """Replace the image with pixel data"""
        img = None
        w, h, name, frame, pixels = self.args

        try:
            img = next(i for i in bpy.data.images if name == image_name(i))
        except StopIteration:
            # to avoid accidentally reviving deleted images, we ignore anything doesn't exist already
            return

        if not img.has_data:
            # load *some* data so that the image can be updated
            pack_empty_png(img)

        elif (img.size[0] != w or img.size[1] != h):
                img.scale(w, h)
        
        if frame != -1:
            img.sb_props.frame = frame
        
        flags = img.sb_props.sync_flags
        if 'SHEET' in flags:
            flags.remove('SHEET')
            img.sb_props.sync_flags = flags

        # convert data to blender accepted floats
        pixels = np.float32(pixels) / 255.0
        # flip y axis ass backwards
        pixels.shape = (h, pixels.size // h)
        pixels = pixels[::-1,:].ravel()

        # change blender data
        try:
            # version >= 2.83; this is much faster
            img.pixels.foreach_set(pixels)
        except AttributeError:
            # version < 2.83
            img.pixels[:] = pixels

        img.update()

        # [#12] for some users viewports do not update from update() alone
        img.update_tag()
        refresh()
        
        self.args = None
        global _update_image_args
        _update_image_args = None

        return {'FINISHED'}


    def execute(self, context):
        self.args = _update_image_args
        return ModalExecuteMixin.execute(self, context)


def update_sheet_animation(anim):
    obj = anim.id_data
    prop_name = anim.prop_name
    img = anim.image

    if prop_name not in obj.modifiers or prop_name not in obj:
        # it's strange if either is removed manually, to be safe let's assume the user no longer wants that animation
        obj.sb_props.animations_remove(anim)

    elif img.sb_props.sheet:
        sheet = img.sb_props.sheet

        start,nframes = sheet.sb_props.sheet_start, sheet.sb_props.animation_length
        rna_ui = obj["_RNA_UI"][prop_name]
        rna_ui["min"] = rna_ui["soft_min"] = start
        rna_ui["max"] = rna_ui["soft_max"] = start + nframes - 1
        obj[prop_name] = max(start, min(obj[prop_name], start + nframes - 1))

        w,h = sheet.sb_props.sheet_size
        uvwarp = obj.modifiers[prop_name]
        uvwarp.scale = (1/w, 1/h)

        if obj.animation_data is None:
            obj.animation_data_create()
        else:
            for driver in obj.animation_data.drivers:
                if driver.data_path == f'modifiers["{prop_name}"].offset':
                    obj.animation_data.drivers.remove(driver)
        
        dx, dy = curves = uvwarp.driver_add("offset")
        for curve in curves:
            # there's a polynomial modifier by default
            curve.modifiers.remove(curve.modifiers[0]) 
            
            # curve shape
            curve.keyframe_points.add(nframes)
            for i,p in enumerate(curve.keyframe_points):
                p.co = (start + i - 0.5, (i % w) if curve == dx else -(i // w))
                p.interpolation = 'CONSTANT'

            # add variable
            driver = curve.driver
            driver.type = 'SUM'
            fv = driver.variables.new()
            fv.name = "frame"
            tgt = fv.targets[0]
            tgt.id_type = 'OBJECT'
            tgt.id = obj
            tgt.data_path = f'["{prop_name}"]'

            curve.update()


_update_spritesheet_args = None
def update_spritesheet(size, count, name, start, frames, tags, current_frame, current_tag, pixels):
    # NOTE this function sets animation flag
    global _update_spritesheet_args
    _update_spritesheet_args = size, count, name, start, frames, tags, current_frame, current_tag, pixels
    bpy.ops.pribambase.update_spritesheet()
    
class SB_OT_update_spritesheet(bpy.types.Operator, ModalExecuteMixin):
    bl_idname = "pribambase.update_spritesheet"
    bl_label = "Update Spritesheet"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO_GROUPED', 'INTERNAL'}
    bl_undo_group = "pribambase.update_spritesheet"


    def update_actions(self, context, img:bpy.types.Image, start:int, frames:Collection[int], current_frame:int, tags:Collection[Tuple[str, int, int, int]], current_tag:str):
        fps = context.scene.render.fps / context.scene.render.fps_base

        # loop tag is the current playing part of the timeline in aseprite
        tag_editor = ("__loop__",)
        if current_tag:
            tag_editor += next((t for t in tags if t[0] == current_tag))[1:]
        else:
            tag_editor += (start, start + len(frames), 0)
        
        # current frame tag just shows the current frame, to allow drawing with spritesheet materials same way as if without animation
        tag_frame = ("__view__", current_frame, current_frame, 0)

        # purge actions for removed tags
        tag_names = ["__loop__"] + [tag[0] for tag in tags]
        for action in bpy.data.actions:
            if action.sb_props.sprite == img and action.sb_props.tag not in tag_names:
                bpy.data.actions.remove(action)

        for tag, tag_first, tag_last, ani_dir in (tag_editor, tag_frame, *tags):
            try:
                action = next(a for a in bpy.data.actions if a.sb_props.sprite == img and a.sb_props.tag == tag)
            except StopIteration:
                action_name = f"{img.name}: {tag}"
                if tag == "__loop__":
                    action_name = f"{img.name} *Loop*"
                elif tag == "__view__":
                    action_name = f"{img.name} *View*"

                action = bpy.data.actions.new(action_name)
                action.id_root = 'OBJECT'
                action.use_fake_user = True
                action.sb_props.tag = tag
                action.sb_props.sprite = img
            
            first = context.scene.frame_start

            tag_frames = frames[tag_first:tag_last + 1]
            if ani_dir == 1:
                tag_frames = tag_frames[::-1]
            elif ani_dir == 2:
                tag_frames = tag_frames + tag_frames[-2:0:-1] # sigh
            
            tag_frames.append(tag_frames[-1]) # one more keyframe to keep the last frame duration inside in the action

            if not action.fcurves:
                fcurve = action.fcurves.new(f'["Frame {img.name}"]')
                fcurve.lock = True

            for fcurve in action.fcurves:
                points = fcurve.keyframe_points
                npoints = len(points)
                nframes = len(tag_frames)
                if npoints < nframes:
                    points.add(nframes - npoints)
                elif npoints > nframes:
                    for _ in range(npoints - nframes):
                        points.remove(points[0], fast=True)

                time = 0
                for point,(y, dt) in zip(points, tag_frames):
                    x = first + time * fps / 1000
                    if addon.prefs.whole_frames:
                        x = round(x)
                    point.co = (x, start + y)
                    point.select_control_point = point.select_left_handle = point.select_right_handle = False
                    point.interpolation = 'CONSTANT'
                    time += dt

                fcurve.update()
            action.update_tag()
        
        scene = context.scene
        if scene.sb_state.action_preview_enabled:
            obj = context.scene.sb_state.action_preview
            if obj and obj.animation_data and obj.animation_data.action:
                scene.frame_preview_start, scene.frame_preview_end = obj.animation_data.action.frame_range
            else:
                scene.sb_state.action_preview_enabled = False


    def modal_execute(self, context):
        size, count, name, start, frames, tags, current_frame, current_tag, pixels = self.args
        tex_w, tex_h = size[0] * count[0], size[1] * count[1]

        # find or prepare sheet image; pixels update will fix its size
        try:
            img = next(i for i in bpy.data.images if name == image_name(i))
        except StopIteration:
            # did not set up the texture first, or deleted it
            return
        
        try:
            sheet = img.sb_props.sheet
            tex_name = sheet.name
        except AttributeError:
            tex_name = img.name + " [sheet]"
            if tex_name not in bpy.data.images:
                tex = bpy.data.images.new(tex_name, tex_w, tex_h, alpha=True)
                pack_empty_png(tex)
            sheet = img.sb_props.sheet = bpy.data.images[tex_name]
        
        sheet.sb_props.is_sheet = True
        sheet.sb_props.animation_length = len(frames)
        sheet.sb_props.sheet_size = count
        sheet.sb_props.sheet_start = start

        self.update_actions(context, img, start, frames, current_frame, tags, current_tag)

        self.args = tex_w, tex_h, tex_name, -1, pixels
        SB_OT_update_image.modal_execute(self, context) # clears self.args

        # cut out the current frame and copy to view image
        frame_x = current_frame % count[0]
        frame_y = current_frame // count[0]
        frame_pixels = np.ravel(pixels[frame_y * size[1] : (frame_y + 1) * size[1], frame_x * size[0] * 4 : (frame_x + 1) * size[0] * 4])
        self.args = *size, name, current_frame, frame_pixels
        SB_OT_update_image.modal_execute(self, context) # clears self.args and animation flag

        flags = img.sb_props.sync_flags
        flags.add('SHEET')
        img.sb_props.sync_flags = flags

        # update rig
        for obj in bpy.data.objects:
            for anim in obj.sb_props.animations:
                if anim.image == img:
                    update_sheet_animation(anim)
            
            obj.update_tag

        # clean up
        global _update_spritesheet_args
        _update_spritesheet_args = None
    
    def execute(self, context):
        self.args = _update_spritesheet_args
        return ModalExecuteMixin.execute(self, context)



_update_frame_args = None
def update_frame(name, frame, start, frames):
    # NOTE this operator removes animation flag from image
    global _update_frame_args
    _update_frame_args = name, frame, start, frames
    bpy.ops.pribambase.update_frame()

class SB_OT_update_frame(bpy.types.Operator, ModalExecuteMixin):
    bl_idname = "pribambase.update_frame"
    bl_label = "Update Frame"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO_GROUPED', 'INTERNAL'}
    bl_undo_group = "pribambase.update_frame"

    def modal_execute(self, context):
        """Copy the frame from spritesheet to the image"""
        name, frame, start, frames = self.args

        try:
            img = next(i for i in bpy.data.images if name == image_name(i))
        except StopIteration:
            # to avoid accidentally reviving deleted images, we ignore anything doesn't exist already
            return

        # TODO getting data from the image might be a pain (it's that opengl thing)
        # might just wait until implementing DNA access

        for action in bpy.data.actions:
            if action.sb_props.sprite == img and action.sb_props.tag == "__view__":
                for fcurve in action.fcurves:
                    for point in fcurve.keyframe_points:
                        point.co = (point.co.x, frame)
                    fcurve.update()
            
            elif action.sb_props.sprite == img and action.sb_props.tag == "__loop__":
                fps = context.scene.render.fps / context.scene.render.fps_base
                frames.append(frames[-1])

                for fcurve in action.fcurves:
                    points = fcurve.keyframe_points
                    npoints = len(points)
                    nframes = len(frames)
                    if npoints < nframes:
                        points.add(nframes - npoints)
                    elif npoints > nframes:
                        for _ in range(npoints - nframes):
                            points.remove(points[0], fast=True)

                    time = 0
                    for point,(y, dt) in zip(points, frames):
                        x = start + time * fps / 1000
                        if addon.prefs.whole_frames:
                            x = round(x)
                        point.co = (x, start + y)
                        point.select_control_point = point.select_left_handle = point.select_right_handle = False
                        point.interpolation = 'CONSTANT'
                        time += dt

        self.args = None
        global _update_frame_args
        _update_frame_args = None

        return {'FINISHED'}


    def execute(self, context):
        self.args = _update_frame_args
        return ModalExecuteMixin.execute(self, context)


class SB_OT_report(bpy.types.Operator, ModalExecuteMixin):
    bl_idname = "pribambase.report"
    bl_label = "Report"
    bl_description = "Report the message"
    bl_options = {'INTERNAL'}

    message_type: bpy.props.StringProperty(name="Message Type", default='INFO')
    message: bpy.props.StringProperty(name="Message", default='Someone forgot to change the message text')

    def modal_execute(self, context):
        self.report({self.message_type}, self.message)
        return {'FINISHED'}