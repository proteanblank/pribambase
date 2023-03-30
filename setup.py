import bpy
from os import path
import sys
from subprocess import Popen, PIPE

from .addon import addon
from . import util


def get_extension_folder(aseprite_exe):
    """Raises RutimeError if path not found"""
    info_lua = path.join(path.dirname(__file__), "scripts", "info.lua")
    prefix = "config_path=" # format is `config_path=...;`
    # there can be extra output and errors from installed plugins, so ignore retcode and other lines
    process = Popen([f'"{aseprite_exe}"', "--batch", "--script", f'"{info_lua}"'], stdout=PIPE)
    out, _ = process.communicate()
    print(info_lua, out)
    try:
        # for some reason, a simple regex here failed for some users
        line = next((l for l in out.decode().splitlines() if l.startswith(prefix)))
        return path.join(line[len(prefix):-1], "extensions", "pribambase")
    except StopIteration:
        raise RuntimeError


class SB_OT_setup(bpy.types.Operator):
    bl_idname = "pribambase.setup"
    bl_label = "Setup for Aseprite"
    bl_description = "Configure Pribambase for working with Aseprite"

    # dialog settings
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.exe;*.bat;*.app;*.sh;[Aa]seprite", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    def find_exe(self):
        paths = (
            "C:\\Program Files\\Aseprite\\aseprite.exe",
            "C:\\Program Files (x86)\\Aseprite\\aseprite.exe",
            "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Aseprite\\aseprite.exe",
            "/Applications/Aseprite.app",
            "~/Library/Application Support/Steam/steamapps/common/Aseprite/Aseprite.app",
            "~/.steam/debian-installation/steamapps/common/Aseprite/aseprite",
            "/usr/bin/aseprite")
        return next((p for p in paths if path.exists(p)), "")


    def execute(self, context):
        from shutil import copytree, ignore_patterns

        # extension can be installed by copying files inside aseprite settings subfolder
        # let's do it like that

        try:
            extfolder = get_extension_folder(self.filepath)

            self.report({'INFO'}, f"Installing to: {extfolder}")
            copytree(path.join(path.dirname(__file__), "client"), extfolder, dirs_exist_ok=True,
                ignore=ignore_patterns("__pref.lua")) # we'll need to keep settings intact
            self.report({'INFO'}, f"Files copied to {extfolder}")
            
            addon.prefs.executable = self.filepath
            bpy.ops.wm.save_userpref('EXEC_DEFAULT') #otherwise the path will reset next launch
            addon.check_installed()
            self.report({'INFO'}, "Installation complete!")
            util.refresh() # needed in case setup was launched from operator finder

        except FileNotFoundError:
            self.report({'ERROR'}, "Aseprite extension setup failed. Could not start Aseprite executable.")
            return {'CANCELLED'}

        except RuntimeError:
            self.report({'ERROR'}, "Aseprite extension setup failed. Make sure scripting is enabled in your version of Aseprite.")
            return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, "Aseprite extension setup failed. " + str(e))
            return {'CANCELLED'}

        return {'FINISHED'}


    def invoke(self, context, event):
        exe = self.find_exe()

        if exe:
            if exe.lower().endswith(".app"):
                # McOS .app are folders (which do not open), need to get actual executable inside
                exe = path.join(exe, "Contents/MacOS/aseprite")

            self.filepath = exe
            self.report({'INFO'}, f"Aseprite found: {exe}")
            return self.execute(context)
        else:
            self.report({'INFO'}, "Failed to find aseprite automatically. Please select aseprite executable")
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
        start_lua = path.join(path.dirname(__file__), "scripts", "start.lua")
        if sys.platform == "win32":
            from subprocess import DETACHED_PROCESS
            Popen([addon.prefs.executable, "--script", start_lua], creationflags=DETACHED_PROCESS)
        else:
            Popen([addon.prefs.executable, "--script", start_lua])
        return {'FINISHED'}