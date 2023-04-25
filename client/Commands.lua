-- Copyright (c) 2021 lampysprites
-- 
-- Permission is hereby granted, free of charge, to any person obtaining a copy
-- of this software and associated documentation files (the "Software"), to deal
-- in the Software without restriction, including without limitation the rights
-- to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
-- copies of the Software, and to permit persons to whom the Software is
-- furnished to do so, subject to the following conditions:
-- 
-- The above copyright notice and this permission notice shall be included in all
-- copies or substantial portions of the Software.
-- 
-- THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
-- IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
-- FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
-- AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
-- LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
-- OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
-- SOFTWARE.

-- globals
pribambase_settings = nil -- refers to plugin.preferences
pribambase_default_settings = {
    host="localhost",
    port="34613",
    layers=false,
    window_persistent=true,
    window_x=0,
    window_y=0
}

function run_script(f) 
    local s = app.fs.joinPath(app.fs.userConfigPath, "extensions", "pribambase", f) .. ".lua"

    return function()
        app.command.RunScript{ filename=s }
    end
end


function init(plugin)

    -- fill the missing settings with default values
    for key,defval in pairs(pribambase_default_settings) do
        if type(plugin.preferences[key]) == "nil" then
            plugin.preferences[key] = defval
        end
    end

    -- expose settings
    pribambase_settings = plugin.preferences

    -- register new menus
    plugin:newCommand{
        id="SbSync",
        title="Sync",
        group="file_export",
        onclick=run_script("Sync")
    }

    plugin:newCommand{
        id="SbSyncSettings",
        title="Pribambase Settings...",
        group="edit_insert",
        onenabled=function() return pribambase_dlg == nil end,
        onclick=run_script("Settings")
    }

    -- os.execute("ping -n 10 localhost > NUL")
end


function exit()
    if pribambase_dlg and pribambase_settings.window_persistent then
        local b = pribambase_dlg.bounds
        pribambase_settings.window_x = b.x
        pribambase_settings.window_y = b.y
    end
end