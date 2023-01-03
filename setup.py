import bpy
import os
from os import path

from .addon import addon

class SB_OT_setup(bpy.types.Operator):
    bl_idname = "pribambase.setup"
    bl_label = "Setup Pribambase"
    bl_description = "Configure Pribambase for working with Aseprite"

    # dialog settings
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="aseprite.exe;aseprite", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    def find_exe(self):
        paths = (
            "C:\\Program Files\\Aseprite\\aseprite.exe",
            "C:\\Program Files (x86)\\Aseprite\\aseprite.exe",
            "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Aseprite\\aseprite.exe",
            "/Applications/Aseprite.app/Contents/MacOS/aseprite",
            "~/Library/Application Support/Steam/steamapps/common/Aseprite/Aseprite.app/Contents/MacOS/aseprite",
            "~/.steam/debian-installation/steamapps/common/Aseprite/aseprite",
            "/usr/bin/aseprite")
        return next((p for p in paths if path.exists(p)), "")


    @classmethod
    def poll(self, context):
        return not addon.installed


    def execute(self, context):
        from subprocess import check_output
        from re import search
        from shutil import copytree, ignore_patterns

        # extension can be installed by copying files inside aseprite settings subfolder
        # let's do it like that

        info_lua = path.join(path.dirname(__file__), "scripts", "info.lua")
        lines = check_output([self.filepath, "--batch", "--script", info_lua]).decode('utf-8')
        # there can be extra output, such as prints from installed plugins
        p = search("config_path=([^;]+);", lines)

        try:
            conf = p.group(1)
            extfolder = path.join(conf, "extensions", "pribambase")

            self.report({'INFO'}, f"Installing to: {extfolder}")
            copytree(path.join(path.dirname(__file__), "client"), extfolder, dirs_exist_ok=True,
                ignore=ignore_patterns("_pref.lua")) # we'll need to keep settings intact
            self.report({'INFO'}, f"Files copied to {extfolder}")
            
            addon.prefs.executable = self.filepath
            bpy.ops.wm.save_userpref('EXEC_DEFAULT') #otherwise the path will reset next launch
            self.report({'INFO'}, "Installation complete!")

        except:
            self.info({'ERROR'}, "Aseprite extension setup failed.")
            return {'CANCELLED'}

        return {'FINISHED'}


    def invoke(self, context, event):
        exe = self.find_exe()

        if exe:
            self.filepath = exe
            self.report({'INFO'}, f"Aseprite found: {exe}")
            return self.execute(context)
        else:
            self.report({'INFO'}, "Can not find aseprite. Please select 'aseprite.exe'")
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}


class SB_OT_launch(bpy.types.Operator):
    bl_idname = "pribambase.launch"
    bl_label = "Launch Aseprite"
    bl_description = "Launch Aseprite for texture painting"

    @classmethod
    def poll(self, context):
        return addon.installed and not addon.connected

    def execute(self, context):
        if not addon.server_up:
            bpy.ops.pribambase.server_start()
        from subprocess import Popen, DETACHED_PROCESS
        start_lua = path.join(path.dirname(__file__), "scripts", "start.lua")
        Popen([addon.prefs.executable, "--script", start_lua], creationflags=DETACHED_PROCESS)
        return {'FINISHED'}