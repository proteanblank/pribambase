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


if app.apiVersion < 15 then
    app.alert{title="Pribambase: Error", text={"This version of Aseprite is not supported", "",
        "Current", ":  " .. "Version" .. ": " .. tostring(app.version), "  " .. "API version" .. ": " .. tostring(app.apiVersion),
        "", "Required" .. ":", "  " .. "Version: 1.2.30 or 1.3-beta7 or newer", "  " .. "API version: 15 or newer",
    }}
    error()

elseif WebSocket == nil then
    app.alert{title="Pribambase: Error", text={"Websocket functionality is disabled in Aseprite.",
        "If you're compiling it yourself, add" .. ' "-DENABLE_WEBSOCKET=ON" ' .. "to CMake options."}}
    error()

elseif pribambase_dlg then
    -- when everything's already running, only need to pop up the dialog again
    pribambase_dlg:show{ wait = false }

else
    -- start a websocket and change observers

    --[[ global ]] pribambase_docs = pribambase_docs or {} -- used as shadow table for docList, not directly

    local BIT_SYNC_SHEET = 1
    local BIT_SYNC_SHOWUV = 1 << 1
    local BIT_SYNC_LAYERS = 1 << 2

    local settings = pribambase_settings
    local ws
    local connected = false
    -- blender file identifier, unique but not permanent (path or random hex string)
    local blendfile = ""
    -- the list of texures open in blender, structured as { identifier:str=flags:int_bitfield }
    local syncList = {}
    -- the list of currently open sprites ever synced, items structured as { blend:str(uid or file), animated:bool, showUV:bool, layers:bool }
    -- needed to a) avoid syncing same named texture to different docs b) (TODO) when blender is not available, store critical changes to process later
    local docList = {}
    -- map MessageID to handler callback
    local handlers = {}
    -- main dialog, created later
    local dlg = nil
    -- used to track the change of active sprite
    local spr = app.activeSprite
    -- used to track saving the image under a different name
    local sprfile = spr and spr.filename
    -- used to track frame changes
    local frame = -1
    -- used to pause the app from processing updates
    local pause_app_change = false
    local pause_spr_change = false
    local pause_dlg_close = false


    -- Set up an image buffer for two reasons:
    -- a) the active cel might not be the same size as the sprite
    -- b) the sprite might not be in RGBA mode, and it's easier to use ase
    --    than do conversions on the other side.
    local buf = Image(1, 1, ColorMode.RGB)


    local function _eq(a, b)
        return a == b
    end

    -- works around aseprite api raising an error when trying to reference a deleted internal object
    -- note: always false for deleted docobjs. even if they were created from the same one - at this point that information is lost
    local function docobjEquals(a, b)
        -- if internal docobj is deleted, _eq raises an error
        local ok, eq = pcall(_eq, a, b)
        return ok and eq
    end
    
    -- wrap the doc list to turn it into { Sprite => data }  map
    -- ase api creates a new userdata every time it returns a sprite, let's switch to `spr1 == spr2` which uses an internal id check
    setmetatable(docList, {
        __pairs= function(_) return pairs(pribambase_docs) end,
        __newindex= function(_, key, val)
            for k,_ in pairs(pribambase_docs) do
                if docobjEquals(k, key) then
                    pribambase_docs[k] = val
                    return
                end
            end
            pribambase_docs[key] = val
        end,
        __index= function(_, key)
            for k,v in pairs(pribambase_docs) do
                if docobjEquals(k, key) then
                    return v
                end
            end
            return nil
        end })

        
    local function _docListClean(doc)
        local found = false
        for _,s in ipairs(app.sprites) do
            if s == doc then
                found = true
                break
            end
        end
        if not found then
            docList[doc] = nil
        end
    end

    local function docListClean()
        for doc,_ in pairs(docList) do
            -- pcall bc ase  errors when trying to use variables for disposed docs
            pcall(_docListClean, doc)
        end
    end


    local function isUntitled(blend)
        -- hex string means the file is not yet saved
        return not not string.match(blend, "^%x+$")
    end

    -- true for saved sprites, false for unsaved
    local function isSprite(sprName)
        return app.fs.filePath(sprName) and app.fs.isFile(sprName)
    end

    local function findOpenDoc(name, origin)
        for _,s in ipairs(app.sprites) do
            if s.filename == name and (origin == nil or docList[s].blend == origin) then
                return s
            end
        end
        return nil
    end

    local function _repl_next(s)
        return string.format("%03d", tonumber(s) + 1)
    end
    local function unique_name(name)
        if syncList[name] ~= nil and not string.match(name, "%d%d%d$") then
            name = name .. "001"
        end

        while syncList[name] ~= nil do
            name = string.gsub(name, "%d%d%d$", _repl_next)
        end
        return name
    end

    local function _co_ilayers(layers, i)
        for _,layer in ipairs(layers) do
            if layer.isGroup then
                i = _co_ilayers(layer.layers, i)
            elseif not layer.isReference then
                coroutine.yield(i, layer)
                i = i + 1
            end
        end
        return i
    end
    
    -- iterate over all image layers
    local function ilayers(group)
        local co = coroutine.create(function () _co_ilayers(group.layers, 1) end)
        return function ()
          local _ok, i, layer = coroutine.resume(co)
          return i, layer
        end
    end

    --[[
        State-independent messsage packing functions.
        May have multiple returns, WebSocket:send() concatenates its arguments
    ]]

    local function messageActiveSprite(opts)
        local id = string.byte('A')
        local name = opts.name
        return string.pack("<Bs4", id, name)
    end

    local function messageImage(opts)
        local sprite = opts.sprite
        local name = opts.name or ""
        local flags = opts.flags
        local id = string.byte('I')

        if buf.width ~= sprite.width or buf.height ~= sprite.height then
            buf:resize(sprite.width, sprite.height)
        end

        buf:clear()
        buf:drawSprite(sprite, opts.frame)

        return string.pack("<BHHHHs4I4", id, buf.width, buf.height, opts.frame.frameNumber - 1, flags, name, buf.rowStride * buf.height), buf.bytes
    end

    local _frames, _infos = {}, {}
    local function messageSpritesheet(opts)
        local sprite = opts.sprite
        local name = opts.name or ""
        local id = string.byte('G')
        local start = app.preferences.document(sprite).timeline.first_frame -- NOTE someone thought it's funny to allow, for instance "-2" there

        if buf.width ~= sprite.width or buf.height ~= sprite.height then
            buf:resize(sprite.width, sprite.height)
        end

        local nframes = #sprite.frames
        local size = buf.rowStride * buf.height

        for i,frame in ipairs(sprite.frames) do
            buf:clear()
            buf:drawSprite(sprite, i)

            _frames[2 * i - 1] = string.pack("<I4", size)
            _frames[2 * i] = buf.bytes
            _infos[i] = string.pack("<HH", i - 1, math.tointeger(1000 * frame.duration))
        end
        for i=2 * nframes + 1,#_frames do
            _frames[i] = nil
        end

        local ntags = #sprite.tags
        _infos[nframes + 1] = string.pack("<I4s4", ntags, opts.tag)
        for i,tag in ipairs(sprite.tags) do
            local dir = (tag.aniDir == AniDir.PING_PONG and 2 or (tag.aniDir == AniDir.REVERSE and 1 or 0))
            _infos[nframes + 1 + i] = string.pack("<s4HHB", tag.name, tag.fromFrame.frameNumber - 1, tag.toFrame.frameNumber - 1, dir)
        end

        for i=nframes + ntags + 2,#_infos do
            _infos[i] = nil
        end

        return string.pack("<BHHs4i4I4I4", id, buf.width, buf.height, name, start, nframes, opts.frame.frameNumber - 1), table.concat(_infos, ""), table.unpack(_frames)
    end
    
    local function messageFrame(opts)
        local sprite = opts.sprite
        local start = app.preferences.document(sprite).timeline.first_frame -- NOTE same as spritesheet

        for i=1,opts.last - opts.first do
            local frame = opts.first + i
            _infos[i] = string.pack("<HH", frame - 1, math.tointeger(1000 * sprite.frames[frame].duration))
        end

        for i=opts.last - opts.first + 1,#_infos do
            _infos[i] = nil
        end

        return string.pack("<BI4s4HI4", string.byte('F'), opts.frame, sprite.filename, start, #_infos), table.unpack(_infos)
    end

    local function messageImageLayers(opts)
        local sprite = opts.sprite
        local name = opts.name or ""
        local frame = opts.frame
        local flags = opts.flags
        local id = string.byte('L')

        local nlayers = 1
        local group = 0 -- only top level group count. flag increments each time one is encountered, so all layers with the same flag belong to the same top-level group

        for i,layer in ilayers(sprite) do
            local groupVal = 0
            if not docobjEquals(layer.parent, sprite) then
                if docobjEquals(layer.parent.parent, sprite) and layer.stackIndex == 1 then
                    group = group + 1
                    _frames[group] = string.pack("<s4", layer.parent.name)
                end
                groupVal = group
            end
            
            local opacity = layer.isVisible and layer.opacity or 0
            local cel = layer:cel(frame)
            local x, y, w, h, img, dataLen = 0, 0, 0, 0, "", 0

            if cel ~= nil then
                local b = cel.bounds
                x, y, w, h = b.x, b.y, b.width, b.height
                img = cel.image.bytes
                dataLen = cel.image.rowStride * cel.image.height
                opacity = math.tointeger(opacity * cel.opacity / 255)
            end

            _infos[2 * i - 1] = string.pack("<HHHHhhHHs4I4", i-1, layer.blendMode, opacity, groupVal, x, y, w, h, layer.name, dataLen)
            _infos[2 * i] = img
            nlayers = i
        end

        for i=2*nlayers+1,#_infos do
            _infos[i] = nil
        end

        for i=group+1,#_frames do
            _frames[i] = nil
        end

        return string.pack("<BHHs4HI4I4", id, sprite.width, sprite.height, name, flags, group, nlayers), table.concat(_frames, ""), table.unpack(_infos)
    end

    local function messageChangeName(opts)
        return string.pack("<Bs4s4", string.byte('C'), opts.from, opts.to)
    end

    local function messageNewTexture(opts)
        return string.pack("<Bs4s4H", string.byte('O'), opts.name, opts.path, opts.flags)
    end

    local function _messageBatchImpl(msg, ...)
        -- FIXME this is not lisp
        if msg then
            return string.pack("<I4", #msg), msg, _messageBatchImpl(...)
        end
    end

    local function messageBatch(count, ...)
        return string.pack("<BH", string.byte('['), count), _messageBatchImpl(...)
    end


    --[[ Messaging logic ]]

    local function sendImage(name)
        if connected and spr ~= nil then
            local flags = syncList[name] or 0
            ws:sendBinary(messageImage{ sprite=spr, name=name, frame=app.activeFrame, flags=flags})
        end
    end

    local function sendImageLayers(name)
        if connected and spr ~= nil then
            local flags = syncList[name] or 0
            ws:sendBinary(messageImageLayers{ sprite=spr, name=name, frame=app.activeFrame, flags=flags })
        end
    end

    local function sendSpritesheet(name)
        if connected and spr ~= nil then
            tag = ""
            if app.activeTag ~= nil and not app.preferences.editor.play_all then
                tag = app.activeTag.name
            end
            ws:sendBinary(messageSpritesheet{ sprite=spr, name=name, frame=app.activeFrame, tag=tag })
        end
    end

    local function sendActiveSprite(name)
        if connected and spr ~= nil then
            ws:sendBinary(messageActiveSprite{ name=name })
        end
    end

    local function sendNewTexture()
        if spr == nil then
            return
        end

        local popup = Dialog{ title="Choose Texture Name" }
        local file = isSprite(spr.filename)

        if file then
            popup:label{ text=spr.filename }
        else
            popup:entry{ id="name", text=unique_name(spr.filename or "Sprite"), focus=true }
        end
        popup:check{ id="animated", text="Animated", onclick=function() popup:modify{ id="layers", visible = settings.layers and not popup.data.animated } end}
        popup:newrow()
        popup:check{ id="layers", text="Layers", visible=settings.layers, onclick=function() popup:modify{ id="animated", visible = not popup.data.layers } end}
        popup:button{ id="cancel", text= "Cancel"}
        popup:button{ id="ok", text= "OK", focus=true}
        popup:show()

        if popup.data.ok then
            docList[spr] = { blend=blendfile, animated=popup.data.animated, showUV=false, layers=popup.data.layers }
            local flags = (popup.data.animated and BIT_SYNC_SHEET or 0) | (popup.data.layers and BIT_SYNC_LAYERS or 0)

            if file then
                ws:sendBinary(messageNewTexture{ name="", path=spr.filename, flags=flags })
            else
                spr.filename = unique_name(popup.data.name)
                app.command.RunScript() -- refresh name on the tab
                ws:sendBinary(messageNewTexture{ name=spr.filename, path="", flags=flags })
            end
        end
    end


    -- creates a reference layer that is scaled to fill the sprite
    -- it generates several undos - consider wrapping with `app.transaction`
    local function show_uv(w, h, opacity, name, data)
        local refLayer
        local refCel

        -- reuse layer
        -- in this case opacity is kept (it's convenient to change)
        for _,l in ipairs(spr.layers) do
            if l.name == name then
                refLayer = l
                spr:deleteCel(refLayer, 1)
                refCel = spr:newCel(refLayer, 1)
                break
            end
        end

        -- create new
        if refLayer == nil then
            local active = app.activeLayer
            app.command.NewLayer{ reference=true }
            refLayer = app.activeLayer
            refLayer.name = name
            refLayer.opacity = opacity
            refLayer.stackIndex = #app.activeSprite.layers
            refCel = app.activeSprite:newCel(refLayer, 1)
            app.activeLayer = active
        end

        if spr.colorMode == ColorMode.RGB then
            if buf.width ~= w or buf.height ~= h then
                buf:resize(w, h)
            end
            buf.bytes = data

            refCel.image = buf
            refCel.image:resize(spr.width, spr.height)
        else
            -- can't seem to find a way to convert between rgb and indexed in the API rn, so we'll have to do manually
            local idx = -1
            local bestDist = math.maxinteger -- squared distance; looking for best match color to draw the UVs with
            local threshold = 64 -- TODO global const

            local rimg = Image(w, h, ColorMode.INDEXED)

            for i=1,#data//4 do
                local a, b, g, r = string.byte(data, 4 * i, 4 * i + 3)

                if a > threshold then
                    if idx == -1 then
                        -- let's find the best color in the palette that we can use
                        local pal = spr.palettes[1]
                        for n=0,#pal-1 do
                            local col = pal:getColor(n)
                            -- euclidean is dumb af but does something at all
                            local dist = (col.red - r) ^ 2 + (col.green - g) ^ 2 + (col.blue - b) ^ 2
                            if dist < bestDist and n ~= spr.transparentColor then
                                bestDist = dist
                                idx = n
                            end
                        end

                        if idx == -1 then
                            -- indexed mode alsways has at least one color in the palette so just in case
                            idx = 0
                        end
                    end

                    rimg:drawPixel(i % w, i // w, idx)
                end
            end

            refCel.image:resize(spr.width, spr.height)
            refCel.image = rimg
        end

        refCel.position = {0, 0}
        app.refresh()
    end


    -- check if the file got renamed
    local function checkFilename()
        if spr == nil then return end

        local newname = spr.filename
        if spr and spr == app.activeSprite and syncList[sprfile] ~= nil and docList[spr] and docList[spr].blend == blendfile and newname ~= sprfile then
            -- renamed
            if sprfile ~= "" then
                ws:sendBinary(messageChangeName{ from=sprfile, to=newname })
            end

            syncList[newname] = syncList[sprfile]
            syncList[sprfile] = nil

            sprfile = newname
        elseif spr then
            sprfile = newname
        end
    end

    
    -- in versions since 16, name change can be handled immediately via an event
    -- in older version, it can only be checked at some other time (e.g. image update)
    local function watchFilename(s)
        if app.apiVersion >= 16 and s then
            s.events:on("filenamechange", checkFilename)
        end
    end

    local function unwatchFilename(s)
        if app.apiVersion >= 16 and s then
            s.events:off(checkFilename)
        end
    end


    local function syncSprite()
        if spr == nil or pause_spr_change then return end

        checkFilename()

        local s = spr.filename
        if syncList[s] ~= nil and docList[spr] and docList[spr].blend == blendfile then
            if docList[spr].animated then
                sendSpritesheet(s)
            elseif docList[spr].layers then
                sendImageLayers(s)
            else
                sendImage(s)
            end
        end
    end


    local updateDialog = nil -- function(status:string|nil)


    local function onAppChange()
        if pause_app_change then return end

        checkFilename()

        if app.activeSprite ~= spr then
            -- stop watching the hidden sprite
            if spr then
                spr.events:off(syncSprite)
                unwatchFilename()

                -- remove closed docs from docList
                local found = false
                local sprn = spr.filename
                for _,doc in ipairs(app.sprites) do
                    if doc.filename == sprn then
                        found = true
                        break
                    end
                end
                if not found then
                    docList[sprn] = nil
                end
            end

            -- remove closed docs from docList to avoid null doc::Sprite errors
            docListClean()

            -- start watching the active sprite
            -- nil when it's the startpage or empty window
            if app.activeSprite then
                spr = app.activeSprite
                sprfile = app.activeSprite.filename
                frame = app.activeFrame.frameNumber
                spr.events:on("change", syncSprite)
                watchFilename(spr)
                syncSprite()
            end

            -- hopefully this will prevent the closed sprite error
            spr = app.activeSprite
            sprfile = ""

            if spr ~= nil then
                local sf = spr.filename
                if (docList[spr] == nil or isSprite(sf)) and syncList[sf] ~= nil then
                    docList[spr] = { 
                        blend=blendfile, 
                        animated=(syncList[sf] & BIT_SYNC_SHEET ~= 0),
                        showUV=(syncList[sf] & BIT_SYNC_SHOWUV ~= 0),
                        layers=(syncList[sf] & BIT_SYNC_LAYERS ~= 0)}
                end
                sendActiveSprite(sf)
            else
                sendActiveSprite("")
            end

            updateDialog()

        elseif spr and connected and app.activeFrame.frameNumber ~= frame then
            frame = app.activeFrame.frameNumber
            if docList[spr] and docList[spr].animated then
                -- all the data is already there, so we can avoid sending it each frame for a lot better performance
                local first, last = 0, #spr.frames - 1
                if app.activeTag ~= nil and not app.preferences.editor.play_all then
                    first, last = app.activeTag.fromFrame.frameNumber - 1, app.activeTag.toFrame.frameNumber
                end
                -- ignore some weird behavior for activeTag/Frame persisting after frames get deleted
                if math.max(frame, first, last) <= #spr.frames then
                    ws:sendBinary(messageFrame{ sprite=spr, frame=frame, first=first, last=last })
                end
            else
                syncSprite()
            end
        end
    end


    -- stop change handlers while executing code, appChange is called in the end unless supressed
    local function batchAppChanges(fn, supress)
        pause_app_change = true
        fn()
        pause_app_change = false
        if not supress then
            onAppChange()
        end
    end


    -- clean up
    local function cleanup()
        if ws ~= nil then ws:close() end
        if dlg ~= nil then
            local d = dlg -- avoid calling ui onClose callback
            dlg = nil
            d:close()
        end
        pribambase_dlg = nil
        if spr~=nil then 
            spr.events:off(syncSprite)
            unwatchFilename()
        end
        app.events:off(onAppChange)
    end


    --[[ Message handlers  ]]

    local function handleImage(msg)
        local _id, w, h, name, pixels = string.unpack("<BHHs4s4", msg)
        
        local sprite = findOpenDoc(name, blendfile)

        if sprite ~= nil and name ~= "" then
            -- not updating existing images for time being, bc the result is only obvious for 1-layer 1-frame sprites
            app.activeSprite = sprite
        else
            batchAppChanges(function()
                    sprite = Sprite(w, h, ColorMode.RGB)
                    if #name > 0 then
                        sprite.filename = name
                    end
                    app.command.LoadPalette{ preset="default" } -- also functions as a hack to reload tab name and window title
                    -- first cel is created with the sprite
                    ---@diagnostic disable-next-line: need-check-nil
                    sprite.cels[1].image.bytes = pixels
                end)
        end

        syncSprite()
    end


    local function handleUVMap(msg)
        local _id, opacity, w, h, layer, pixels = string.unpack("<BBHHs4s4", msg)

        if spr == nil then
            return
        end

        pause_spr_change = true
        app.transaction(function()
            show_uv(w, h, opacity, layer, pixels)
        end)
        pause_spr_change = false
    end


    local function handleTextureList(msg)
        local ml = #msg
        local synced = spr and syncList[spr.filename]
        local bflen = string.unpack("<I4", msg, 2)
        local offset = 2 + 4 + bflen -- start of the image names

        blendfile = string.unpack("<s4", msg, 2)
        updateDialog("ON: " .. (isUntitled(blendfile) and "untitled" or app.fs.fileName(blendfile)))

        syncList = {}

        while offset < ml do
            local len = string.unpack("<I4", msg, offset)
            local name, flags = string.unpack("<s4I2", msg, offset)
            syncList[name] = flags
            offset = offset + 6 + len -- 6 is string:packsize("<s4I2")
        end

        for _,s in ipairs(app.sprites) do
            local sf = s.filename
            if syncList[sf] ~= nil and (docList[s] == nil or isSprite(sf)) then
                docList[s] = { blend=blendfile, 
                    animated=(syncList[sf] & BIT_SYNC_SHEET ~= 0),
                    showUV=(syncList[sf] & BIT_SYNC_SHOWUV ~= 0),
                    layers=(syncList[sf] & BIT_SYNC_LAYERS ~= 0)}
            end
        end

        if spr and docList[spr] and (
                (not dlg.data.animated and docList[spr].animated) or
                (not dlg.data.layers and docList[spr].layers) or
                (not dlg.data.showuv and docList[spr].showUV)) then
            synced = false
        end
        
        updateDialog()

        if not synced then
            syncSprite()
        end
    end


    local function handleNewSprite(msg)
        -- creating sprite triggers the app change handler several times
        -- let's pause it and call later manually
        batchAppChanges(function()
                local _id, mode, w, h, flags, name = string.unpack("<BBHHHs4", msg)

                if mode == 0 then mode = ColorMode.RGB
                elseif mode == 1 then mode = ColorMode.INDEXED
                elseif mode == 2 then mode = ColorMode.GRAY end

                local create = Sprite(w, h, mode)
                create.filename = name
                app.command.LoadPalette{ preset="default" } -- also functions as a hack to reload tab name and window title
                sprfile = name

                syncList[name] = flags
                docList[create] = {
                    blend=blendfile,
                    animated=(flags & BIT_SYNC_SHEET ~= 0),
                    showUV=(flags & BIT_SYNC_SHOWUV ~= 0),
                    layers=(flags & BIT_SYNC_LAYERS ~= 0)}
            end)
    end


    local function handleFocus(msg)
        local _id, path = string.unpack("<Bs4", msg)

        local s = findOpenDoc(path, isSprite(path) and blendfile or nil)
        if s then
            app.activeSprite = s
        end
    end


    local function handleOpenSprite(msg)
        local _id, flags, path = string.unpack("<BHs4", msg)
        local opened = findOpenDoc(path) -- ignore blendfile origin here bc this message is always file-based

        syncList[path] = flags

        if opened then
            docList[opened] = {
                blend=blendfile,
                animated=(flags & BIT_SYNC_SHEET ~= 0),
                showUV=(flags & BIT_SYNC_SHOWUV ~= 0),
                layers=(flags & BIT_SYNC_LAYERS ~= 0)}

            if app.activeSprite ~= opened then
                app.activeSprite = opened
            else
                syncSprite()
            end
        elseif isSprite(path) then -- check if absolute path; message can't contain rel path, so getting one mean it's a datablock name, and we don't need to open it if it isn't
            batchAppChanges(function()
                    s = Sprite{ fromFile=path }
                    syncList[path] = flags
                    docList[s] = { blend=blendfile, 
                        animated=(flags & BIT_SYNC_SHEET ~= 0),
                        showUV=(flags & BIT_SYNC_SHOWUV ~= 0),
                        layers=(flags & BIT_SYNC_LAYERS ~= 0)}
                end)
        end
    end


    local function handleBatch(msg)
        local count = string.unpack("<BH", msg, 2)
        local offset = 4
        for _=1,count do
            -- peek the data length and id inside the batched command
            local len, id = string.unpack("<I4B", msg, offset)
            -- the command as if it arrived alone
            local message = string.unpack("<s4", msg, offset)
            handlers[id](message)
            -- pcall(handlers[id], message) TODO uncomment
            offset = offset + 4 + len
        end
    end


    local function handlePeek(msg)
        local _id, count = string.unpack("<BH", msg)
        local offset = 4
        batchAppChanges(function()
            for i=1,count do
                local len = string.unpack("<I4", msg, offset)
                local name, flags = string.unpack("<s4I2", msg, offset)
                offset = offset + 6 + len -- 6 is string:packsize("<s4I2")

                local animated = flags & BIT_SYNC_SHEET ~= 0
                local layers = flags & BIT_SYNC_LAYERS ~= 0
                local s = Sprite{fromFile=name}
                local flags = syncList[name] or 0
                if animated then
                    tag = ""
                    if app.activeTag ~= nil and not app.preferences.editor.play_all then
                        tag = app.activeTag.name
                    end
                    ws:sendBinary(messageSpritesheet{ sprite=s, name=name, frame=app.activeFrame, tag=tag })
                elseif layers then
                    ws:sendBinary(messageImageLayers{ sprite=s, name=name, frame=app.activeFrame, flags=flags })
                else
                    ws:sendBinary(messageImage{ sprite=s, name=name, frame=app.activeFrame , flags=flags})
                end
                s:close()
            end
        end, true)
    end


    handlers = {
        [string.byte('I')] = handleImage,
        [string.byte('[')] = handleBatch,
        [string.byte('M')] = handleUVMap,
        [string.byte('L')] = handleTextureList,
        [string.byte('S')] = handleNewSprite,
        [string.byte('O')] = handleOpenSprite,
        [string.byte('F')] = handleFocus,
        [string.byte('P')] = handlePeek,
    }


    --[[ UI callbacks ]]

    -- t is for type, there's already a lua function
    local function receive(t, message)
        if t == WebSocketMessageType.BINARY then
            local id = string.unpack("<B", message)
            handlers[id](message)
            -- pcall(handlers[id], message) TODO uncommet

        elseif t == WebSocketMessageType.OPEN then
            connected = true
            updateDialog("Sync ON")
            -- animated and sendopen are modified during texture list sync

            if spr ~= nil then
                spr.events:on("change", syncSprite)
                watchFilename(spr)
                sendActiveSprite(spr.filename)
            end


        elseif t == WebSocketMessageType.CLOSE and dlg ~= nil then
            connected = false
            updateDialog("Reconnecting...")
            if spr ~= nil then
                spr.events:off(syncSprite)
                unwatchFilename()
            end
        end

        checkFilename()
    end


    local function changeAnimated()
        local val = dlg.data.animated
        local sf = spr.filename
        if syncList[sf] ~= nil then
            syncList[sf] = (val and (syncList[sf] | BIT_SYNC_SHEET) or (syncList[sf] & ~BIT_SYNC_SHEET))
        end
        if docList[spr] ~= nil then
            docList[spr].animated = val
        end
        syncSprite()
        updateDialog()
    end


    local function changeLayers()
        local val = dlg.data.layers
        local sf = spr.filename
        if syncList[sf] ~= nil then
            syncList[sf] = (val and (syncList[sf] | BIT_SYNC_LAYERS) or (syncList[sf] & ~BIT_SYNC_LAYERS))
        end
        if docList[spr] ~= nil then
            docList[spr].layers = val
        end
        syncSprite()
        updateDialog()
    end


    local function changeShowUV()
        local val = dlg.data.showuv
        local sf = spr.filename
        if syncList[sf] ~= nil then
            syncList[sf] = (val and (syncList[sf] | BIT_SYNC_SHOWUV) or (syncList[sf] & ~BIT_SYNC_SHOWUV))
        end
        if docList[spr] ~= nil then
            docList[spr].showUV = val
        end
        
        local s = spr.filename
        if syncList[sf] & BIT_SYNC_LAYERS ~= 0 then
            sendImageLayers(s)
        else
            -- sync non-spritesheet image for spritesheets
            if syncList[s] ~= nil and docList[spr] and docList[spr].blend == blendfile then
                sendImage(s)
            end
        end

        updateDialog()
    end


    local function dlgClose()
        if pause_dlg_close then
            return
        end
        pause_dlg_close = true
        if pribambase_settings.window_persistent then
            local b = dlg.bounds
            pribambase_settings.window_x = b.x
            pribambase_settings.window_y = b.y
        end
        cleanup()
        pause_dlg_close = false
    end


    local function dlgMove()
        -- restore saved position if needed
        -- only call after showing the dialog for the first time, it makes assumptions about default
        -- positioning
        if pribambase_settings.window_persistent then
            local b = dlg.bounds -- looks like this creates a table each time
            local scrw, scrh = b.x * 2 + b.width, b.y * 2 + b.height

            b.x = pribambase_settings.window_x
            b.y = pribambase_settings.window_y

            -- clamp position so that after resizing window the popup stays inside the client area
            if b.x < 0 then b.x = 0 end
            if b.x > scrw - b.width then b.x = scrw - b.width end
            if b.y < 0 then b.y = 0 end
            if b.y > scrh - b.height then b.y = scrh - b.height end

            dlg.bounds = b -- assigning will move dialog
        end
    end


    -- set up a websocket
    ws = WebSocket{
        url=table.concat{"http://", settings.host, ":", settings.port},
        onreceive=receive,
        deflate=false
    }

    -- doclist can have stuff from the last launch
    docListClean()

    app.events:on("sitechange", onAppChange)
    
    -- create an UI
    
    dlg = Dialog{ title="Sync", onclose=dlgClose }
    --[[ global ]] pribambase_dlg = dlg


    updateDialog = function(status)
        local sync = (spr ~= nil and syncList[spr.filename])
        local doc =  (spr ~= nil and docList[spr])

        local layers = (spr ~= nil and doc and doc.layers)
        local animated = (spr ~= nil and doc and doc.animated)

        if status then dlg:modify{ id="status", text=status } end
        dlg:modify{ id="reconnect", visible=(not connected) }
        dlg:modify{ id="animated", visible=(connected and spr ~= nil and sync ~= nil and not layers), selected=animated }
        dlg:modify{ id="showuv", visible=(connected and spr ~= nil and sync ~= nil), selected=(spr and doc and doc.showUV) }
        dlg:modify{ id="layers", visible=(connected and settings.layers and spr ~= nil and sync ~= nil and not animated), selected=layers }
        dlg:modify{ id="sendopen", visible=(connected and spr ~= nil and sync == nil) }
    end


    dlg:label{ id="status", text="Connecting..." }
    dlg:button{ id="reconnect", text="Reconnect", onclick=function() ws:close() ws:connect() end }

    dlg:check{ id="animated", text="Animation", onclick=changeAnimated, selected=(spr and docList[spr] and docList[spr].animated) }

    dlg:newrow()
    dlg:check{ id="layers", text="Layers", onclick=changeLayers, selected=(spr and docList[spr] and docList[spr].layers) }

    dlg:newrow()
    dlg:check{ id="showuv", text="Show UV", onclick=changeShowUV, selected=(spr and docList[spr] and docList[spr].showUV) }
    dlg:button{ id="sendopen", text="Add to Blendfile", onclick=sendNewTexture }

    dlg:newrow()
    dlg:button{ text="X " .. "Stop", onclick=dlgClose }
    dlg:button{ text="_ " .. "Hide", onclick=function() pause_dlg_close = true dlg:close() pause_dlg_close = false end }

    updateDialog()

    -- GO

    if --[[ global ]]pribambase_start then
        -- plugin is loading now
        -- FIXME remove this condition, it's not needed
        if pribambase_settings.autostart then
            ws:connect()

            if pribambase_settings.autoshow then
                dlg:show{ wait=false }
                dlgMove()
            end
        end
    else
        -- launched from the menu (first time)
        ws:connect()
        dlg:show{ wait=false }
        dlgMove()
    end
end