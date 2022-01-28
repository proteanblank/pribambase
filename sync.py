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

from __future__ import annotations
from aiohttp.web_ws import WebSocketResponse

import bpy
import asyncio
import aiohttp
from aiohttp import web
from time import time
from itertools import chain
from bpy.app.translations import pgettext

from . import async_loop
from . import util
from .image import SB_OT_uv_send, uv_lines
from .messaging import encode
from .addon import addon

from typing import Tuple


class Server():
    def __init__(self, host="", port=0):
        self.host = host
        self.port = port
        self._ws = None
        self._server = None
        self._site = None
        self._start_time = 0


    def send(self, msg, binary=True):
        if self._ws is not None:
            if binary:
                asyncio.ensure_future(self._ws.send_bytes(msg, False))
            else:
                asyncio.ensure_future(self._ws.send_str(msg, False))


    @property
    def connected(self):
        return self._ws is not None and not self._ws.closed


    def start(self):
        started = False

        self._start_time = int(time())

        async def _start_a(self):
            nonlocal started
            self._server = web.Server(self._receive)

            runner = web.ServerRunner(self._server)
            await runner.setup()

            self._site = web.TCPSite(runner, self.host, self.port)
            await self._site.start()

            started = True

        async_loop.ensure_async_loop()
        stop = asyncio.wait_for(_start_a(self), timeout=5.0)

        try:
            asyncio.get_event_loop().run_until_complete(stop)
            util.refresh()
        except asyncio.TimeoutError:
            raise RuntimeError(f"{pgettext('Could not start server at')} {self.host}:{self.port}")


    def stop(self):
        async def _stop_a():
            if self._ws is not None:  # no connections happened
                await self._ws.close()
            await self._site.stop()
            await self._site._runner.cleanup()
            await self._server.shutdown()
            addon.active_sprite = None

        asyncio.ensure_future(_stop_a())
        async_loop.erase_async_loop()
        util.refresh()


    async def _receive(self, request) -> WebSocketResponse:
        self._ws = web.WebSocketResponse(max_msg_size=0)

        await self._ws.prepare(request)

        # client connected
        lst = [(img.sb_props.sync_name, img.sb_props.sync_flags) for img in bpy.data.images]
        bf = addon.state.identifier
        await self._ws.send_bytes(encode.texture_list(bf, lst), False)
        bpy.ops.pribambase.report(message_type='INFO', message="Aseprite connected")
        util.refresh()

        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                await addon.handlers.process(msg.data)

            elif msg.type == aiohttp.WSMsgType.ERROR:
                bpy.ops.pribambase.report(message_type='ERROR', message=f"{pgettext('Aseprite connection closed with exception')} {self._ws.exception()}")

        # client disconnected
        bpy.ops.pribambase.report(message_type='INFO', message="Aseprite disconnected")
        util.refresh()

        return self._ws


class UVWatch:
    running = None # only allow one running watch to avoid the confusion, and keep performance acceptable

    PERIOD = 0.05 # seconds between timer updates
    SLEEP = 0.5 # period when timer is skipping the checks (outside of edit/texpaint mode)

    def __init__(self, size:Tuple[int, int], color:Tuple[float,float,float,float], weight:float):
        self.is_running = False

        # uv send properties
        self.size = (*size,) # gotta copy here bc vectors are mutable lists and seem to reset to default value later
        self.color = (*color,)
        self.weight = weight
    

    def start(self):
        assert not self.__class__.running
        self.last_hash = 0
        self.idle_t = 0
        self.send_pending = True
        self.__class__.running = self
        bpy.app.timers.register(self.timer_callback)
        self.timer_callback()
        print("watch start")
    

    def stop(self):
        assert self == self.__class__.running
        self.__class__.running = None
        print("watch stop")


    def timer_callback(self):
        if self != self.__class__.running:
            return None

        self.idle_t += self.PERIOD

        context = bpy.context
        watched = addon.state.uv_watch

        if not self.send_pending:
            # go sleep in several cases that do not imply sending the UVs
            if watched == 'NEVER' \
                    or context.mode not in ('EDIT_MESH', 'PAINT_TEXTURE') \
                    or (watched == 'SHOWN' and not self.active_sprite_open(context)) \
                    or addon.active_sprite_image is None \
                    or ('SHOW_UV' not in addon.active_sprite_image.sb_props.sync_flags):
                return self.SLEEP

            changed = self.update_hash(context) # skip checks when waiting to send
            ## TODO when removing print, use this:
            # self.send_pending = self.send_pending or changed and self.last_hash
            if changed:
                print("changed", self.last_hash)
                if self.last_hash: # have some data
                    self.send_pending = True
        
        if self.send_pending: # not elif!!
            if self.idle_t >= addon.prefs.debounce:
                size = addon.state.uv_size
                if addon.state.uv_is_relative:
                    img = addon.active_sprite_image
                    if img:
                        size = (int(img.size[0] * addon.state.uv_scale), int(img.size[1] * addon.state.uv_scale))

                bpy.ops.pribambase.uv_send(context.copy(), 
                    size=size,
                    color=addon.state.uv_color, 
                    weight=addon.state.uv_weight)
                self.send_pending = False
                self.idle_t = 0
            else:
                print("wait", self.idle_t, self.send_pending)

        return self.PERIOD


    def update_hash(self, context) -> bool:
        meshes = (obj.data for obj in context.selected_objects if obj.type == 'MESH' and obj.data)
        if context.object and context.object.type == 'MESH': 
            meshes = chain(meshes, [context.object])

        lines = frozenset(line for mesh in meshes for line in uv_lines(mesh))
        new_hash = hash(lines) if lines else 0
        changed = (new_hash != self.last_hash)
        self.last_hash = new_hash
        return changed
    

    def active_sprite_open(self, context) -> bool:
        active = addon.active_sprite

        image_editors = (a for window in context.window_manager.windows for a in window.screen.areas if a.type=='IMAGE_EDITOR')

        for area in image_editors:
            image = area.spaces[0].image
            if image and image.sb_props.sync_name == active:
                return True

        return False


class SB_OT_server_start(bpy.types.Operator):
    bl_idname = "pribambase.server_start"
    bl_label = "Open Connection"
    bl_description = "Begin accepting connections from Aseprite"


    @classmethod
    def poll(self, ctx):
        return not addon.server_up


    def execute(self, context):
        addon.start_server()
        return {'FINISHED'}


class SB_OT_server_stop(bpy.types.Operator):
    bl_idname = "pribambase.server_stop"
    bl_label = "Close Connection"
    bl_description = "Disconnect and stop accepting connections from Aseprite"


    @classmethod
    def poll(self, ctx):
        return addon.server_up


    def execute(self, context):
        addon.stop_server()
        return {"FINISHED"}


class SB_OT_send_texture_list(bpy.types.Operator):
    bl_idname = "pribambase.send_texture_list"
    bl_label = "Update Texture List"
    bl_description = "Update Aseprite about which textures are used in the blendfile"
    bl_options = {'INTERNAL'}


    @classmethod
    def poll(self, ctx):
        return addon.server_up


    def execute(self, context):
        if addon.connected:
            images = [(img.sb_props.sync_name, img.sb_props.sync_flags) for img in bpy.data.images]
            bf = addon.state.identifier
            msg = encode.texture_list(bf, images)
            addon.server.send(msg)

        return {'FINISHED'}
