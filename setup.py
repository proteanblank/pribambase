import bpy
from os import path
import sys
import webbrowser
from subprocess import Popen

from .addon import addon


class SB_OT_setup(bpy.types.Operator):
    bl_idname = "pribambase.setup"
    bl_label = "Install Aseprite Extension"
    bl_description = "Install an extension to Aseprite, that makes it possible to communicate with Blender"

    def execute(self, context):
        where = path.join(path.dirname(__file__), "aseprite")
        self.report({'INFO'}, f"Opening '{where}'...")
        webbrowser.open(where)
        return {'FINISHED'}


class SB_OT_launch(bpy.types.Operator):
    bl_idname = "pribambase.launch"
    bl_label = "Launch Aseprite"
    bl_description = "Launch Aseprite for texture painting"

    @classmethod
    def poll(self, context):
        return not addon.connected


    def execute(self, context):
        exe = addon.prefs.executable or addon.prefs.executable_auto
        print(addon.prefs.executable_auto)
        if not exe:
            self.report({'ERROR'}, "Please specify a valid path to aseprite exe/app in addon settings.")
            return {'CANCELLED'}

        if not addon.server_up:
            bpy.ops.pribambase.server_start()
        start_lua = path.join(path.dirname(__file__), "scripts", "start.lua")
        if sys.platform == "win32":
            from subprocess import DETACHED_PROCESS
            Popen([exe, "--script", start_lua], creationflags=DETACHED_PROCESS)
        else:
            Popen([exe, "--script", start_lua])
        return {'FINISHED'}