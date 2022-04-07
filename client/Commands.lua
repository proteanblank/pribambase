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
    autostart=false,
    autoshow=false
}


-- localization
-- locales are loaded from the same files for both blender and aseprite; only, aseprite's strings are stored in 'ase' context
local loaded_locale = 'en'
local locale_translations = {} -- stores english strings as keys, translated as values

-- load locale translations and mark current locale to be loaded, regardles of whether there's any translations in it
local function load_locale(locale)
    -- reset
    locale_translations = {}
    loaded_locale = locale

    local csv = io.open(app.fs.joinPath(app.fs.userConfigPath, "extensions", "pribambase", "translations", locale .. ".csv"))

    if not csv then
        return -- no translations for the locale
    end

    for line in csv:lines() do
        -- only keep 'ase' context
        en, tr = string.match(line, "^ase;%s*([^;]+);%s*([^;]+)")
        if en then
            en = string.gsub(string.gsub(en, "%s+$", ""), "^%s+", "")
            tr = string.gsub(string.gsub(tr, "%s+$", ""), "^%s+", "")
            locale_translations[en] = tr
        end
    end

    csv:close()
end

-- imitates bpy.app.translations.pgettext
pribambase_gettext = function(str)
    current_locale = app.preferences.general.language
    if current_locale ~= loaded_locale then
        load_locale(current_locale)
    end

    return locale_translations[str] or str
end

-- end localization

function run_script(f) 
    local s = app.fs.joinPath(app.fs.userConfigPath, "extensions", "pribambase", f) .. ".lua"

    return function()
        app.command.RunScript{ filename=s }
    end
end


function init(plugin)
    local tr = pribambase_gettext
    load_locale(app.preferences.general.language)

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
        title=tr("Sync"),
        group="file_export",
        onclick=run_script("Sync")
    }

    plugin:newCommand{
        id="SbSyncSettings",
        title=tr("Sync Settings..."),
        group="file_export",
        onenabled=function() return pribambase_dlg == nil end,
        onclick=run_script("Settings")
    }

    if plugin.preferences.autostart or plugin.preferences.autoshow then
        pribambase_start = true
        local ok, what = pcall(run_script("Sync"))
        if not ok then
            print(tr("Could not start sync") .. ": " .. what)
        end
        pribambase_start = nil
    end
end