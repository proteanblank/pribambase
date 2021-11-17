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
        "Current:", "  Version: " .. tostring(app.version), "  API version: " .. tostring(app.apiVersion),
        "", "Required:", "  Version: 1.2.30 or 1.3-beta7 or newer", "  API version: 15 or newer",
    }}
    error()

elseif WebSocket == nil then
    app.alert{title="Pribambase: Error", text={"Websocket functionality is disabled in Aseprite.",
        "If you're compiling it yourself, add \"-DENABLE_WEBSOCKET=ON\" to CMake options."}}
    error()

elseif pribambase_dlg then
    -- when everything's already running, only need to pop up the dialog again
    pribambase_dlg:show{ wait = false }

else
    -- start a websocket and change observers

    --[[ global ]] pribambase_docs = pribambase_docs or {} -- used as shadow table for docList, not directly

    local settings = pribambase_settings
    local ws
    local connected = false
    -- blender file identifier, unique but not permanent (path or random hex string)
    local blendfile = ""
    -- the list of texures open in blender, structured as { identifier:str=true }
    local syncList = {}
    -- the list of currently open sprites ever synced, structured as { doc:Sprite=origin:str }
    -- needed to a) avoid syncing same named texture to different docs b) (TODO) when blender is not available, store critical changes to process later
    local docList = {}
    -- map MessageID to handler callback
    local handlers = {}
    -- main dialog
    local dlg = app.isUIAvailable and Dialog()
    -- used to track the change of active sprite
    local spr = app.activeSprite
    -- used to track saving the image under a different name
    local sprfile = spr and spr.filename
    -- used to track frame changes
    local frame = -1
    -- used to pause the app from processing updates
    local pause_app_change = false
    -- Set up an image buffer for two reasons:
    -- a) the active cel might not be the same size as the sprite
    -- b) the sprite might not be in RGBA mode, and it's easier to use ase
    --    than do conversions on the other side.
    local buf = Image(1, 1, ColorMode.RGB)

    
    -- wrap the doc list
    -- the biggest reason for do ing it kike os is index method: ase api creates a new userdata every time it returns a sprite, let's switch to `spr1 == spr2` which uses an internal id check
    setmetatable(docList, {
        __pairs= function(_) return pairs(pribambase_docs) end,
        __newindex= function(_, key, val)
            for k,_ in pairs(pribambase_docs) do
                if k == key then
                    pribambase_docs[k] = val
                    return
                end
            end
            pribambase_docs[key] = val
        end,
        __index= function(_, key)
            for k,v in pairs(pribambase_docs) do
                if k == key then
                    return v
                end
            end
            return nil
        end,
        removeClosed=function(t)
            for doc,_ in pairs(t) do
                pcall(t._remove, t, doc)
            end
        end,
        _remove= function(doc)
            -- impl; use via pcall bc ase is stinky about trying to use old objects
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
        })

    -- clean at start
    docList:removeClosed()


    local function isUntitled(blend)
        -- hex string means the file is not yet saved
        return not not string.match(blend, "^%x+$")
    end

    -- true for saved sprites, false for unsaved
    local function isSprite(sprName)
        return app.fs.filePath(sprName) and app.fs.isFile(sprName)
    end

    --[[
        State-independent messsage packing functions.
        May have multiple returns, WebSocket:send() concatenates its arguments
    ]]

    local function messageImage(opts)
        local sprite = opts.sprite
        local name = opts.name or ""
        local id = string.byte(opts.new and 'N' or 'I')

        if buf.width ~= sprite.width or buf.height ~= sprite.height then
            buf:resize(sprite.width, sprite.height)
        end

        buf:clear()
        buf:drawSprite(sprite, opts.frame)

        return string.pack("<BHHs4I4", id, buf.width, buf.height, name, buf.rowStride * buf.height), buf.bytes
    end


    local function messageChangeName(opts)
        return string.pack("<Bs4s4", string.byte('C'), opts.from, opts.to)
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

    local function sendImage(name, new)
        if connected and spr ~= nil then
            ws:sendBinary(messageImage{ sprite=spr, name=name, frame=app.activeFrame, new = new })
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
        if spr and spr == app.activeSprite and syncList[sprfile] and docList[spr] == blendfile and newname ~= sprfile then
            -- renamed
            if sprfile ~= "" then
                ws:sendBinary(messageChangeName{ from=sprfile, to=newname })
            end

            syncList[newname] = true
            syncList[sprfile] = nil

            sprfile = newname
        elseif spr then
            sprfile = newname
        end
    end


    local function syncSprite()
        if spr == nil then return end

        checkFilename()

        local s = spr.filename
        if syncList[s] and docList[spr] == blendfile then
            sendImage(s)
        end
    end


    -- close connection and ui if the sprite is closed
    local function onAppChange()
        if pause_app_change then return end

        checkFilename()

        if app.activeSprite ~= spr then
            -- stop watching the hidden sprite
            if spr then
                spr.events:off(syncSprite)
            end

            -- remove closed docs from docList to avoid null doc::Sprite errors
            docList:removeClosed()

            -- start watching the active sprite
            -- nil when it's the startpage or empty window
            if app.activeSprite then
                spr = app.activeSprite
                sprfile = app.activeSprite.filename
                frame = app.activeFrame.frameNumber
                spr.events:on("change", syncSprite)
                syncSprite()
            end

            -- hopefully this will prevent the closed sprite error
            spr = app.activeSprite
            sprfile = ""

            if spr ~= nil then
                local sf = spr.filename
                if (docList[spr] == nil or isSprite(sf)) and syncList[sf] ~= nil then
                    docList[spr] = blendfile -- TODO after adding sync props, assign them
                end
            end

        elseif spr and connected and app.activeFrame.frameNumber ~= frame then
            frame = app.activeFrame.frameNumber
            syncSprite()
        end
    end


    -- clean up and exit
    local function cleanup()
        if ws ~= nil then ws:close() end
        if dlg ~= nil then dlg:close() dlg = nil end
        pribambase_dlg = nil
        if spr~=nil then spr.events:off(syncSprite) end
        app.events:off(onAppChange)
    end


    local function createTexture()
        sendImage(spr.filename or "Sprite", true)
    end


    --[[ Message handlers  ]]

    local function handleImage(msg)
        local _id, w, h, name, pixels = string.unpack("<BHHs4s4", msg)
        
        pause_app_change = true

        local sprite = Sprite(w, h, ColorMode.RGB)
        if #name > 0 then
            sprite.filename = name
        end
        app.command.LoadPalette{ preset="default" } -- also functions as a hack to reload tab name and window title
        sprite.cels[1].image.bytes = pixels
        
        pause_app_change = false
        onAppChange()

        syncSprite()
    end


    local function handleUVMap(msg)
        local _id, opacity, w, h, layer, sprite, pixels = string.unpack("<BBHHs4s4s4", msg)

        if sprite ~= "" then
            local found = false

            for _,s in ipairs(app.sprites) do
                if s.filename == sprite then
                    app.activeSprite = s
                    found = true
                    break
                end
            end

            if not found then
                return
            end
        elseif spr == nil then
            return
        end

        app.transaction(function()
            show_uv(w, h, opacity, layer, pixels)
        end)
    end


    local function handleTextureList(msg)
        local _id = string.unpack("<BH", msg)
        local ml = #msg
        local synced = spr and syncList[spr.filename]
        local bflen = string.unpack("<I4", msg, 2)
        local offset = 2 + 4 + bflen -- start of the image names

        blendfile = string.unpack("<s4", msg, 2)
        dlg:modify{ id="status", text=(isUntitled(blendfile) and "ON: untitled" or "ON: " .. app.fs.fileName(blendfile)) }

        syncList = {}

        while offset < ml do
            local len = string.unpack("<I4", msg, offset)
            local name = string.unpack("<s4", msg, offset)
            syncList[name] = true
            offset = offset + 4 + len
        end

        for i,s in ipairs(app.sprites) do
            local sf = s.filename
            if syncList[sf] and (docList[s] == nil or isSprite(sf)) then
                docList[s] = blendfile -- TODO see comment on a similar statement in appchange
            end
        end

        if not synced then
            syncSprite()
        end
    end


    local function handleNewSprite(msg)
        -- creating sprite triggers the app change handler several times
        -- let's pause it and call later manually
        pause_app_change = true
        local _id, mode, w, h, name = string.unpack("<BBHHs4", msg)

        if mode == 0 then mode = ColorMode.RGB
        elseif mode == 1 then mode = ColorMode.INDEXED
        elseif mode == 2 then mode = ColorMode.GRAY end

        local prev = spr
        local create = Sprite(w, h, mode)
        create.filename = name
        app.command.LoadPalette{ preset="default" } -- also functions as a hack to reload tab name and window title
        sprfile = name

        syncList[name] = true
        pause_app_change = false
        onAppChange() -- adds to doclist
    end


    local function handleFocus(msg)
        local _id, path = string.unpack("<Bs4", msg)

        for _,sprite in ipairs(app.sprites) do
            if sprite.filename == path then
                app.activeSprite = sprite
                break
            end
        end
    end


    local function handleOpenSprite(msg)
        local _id, path = string.unpack("<Bs4", msg)

        syncList[path] = true

        local opened
        for _,sprite in ipairs(app.sprites) do
            if sprite.filename == path then
                opened = sprite
                break
            end
        end

        if opened then
            if app.activeSprite ~= opened then
                app.activeSprite = opened
            else
                syncSprite()
            end
        elseif isSprite(path) then -- check if absolute path; message can't contain rel path, so getting one mean it's a datablock name, and we don't need to open it if it isn't
            Sprite{ fromFile = path }
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


    handlers = {
        [string.byte('I')] = handleImage,
        [string.byte('[')] = handleBatch,
        [string.byte('M')] = handleUVMap,
        [string.byte('L')] = handleTextureList,
        [string.byte('S')] = handleNewSprite,
        [string.byte('O')] = handleOpenSprite,
        [string.byte('F')] = handleFocus,
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
            dlg:modify{ id="status", text="Sync ON" }
            dlg:modify{ id="reconnect", visible=false }

            if spr ~= nil then
                spr.events:on("change", syncSprite)
            end

        elseif t == WebSocketMessageType.CLOSE and dlg ~= nil then
            connected = false
            dlg:modify{ id="status", text="Reconnecting..." }
            dlg:modify{ id="reconnect", visible=true }
            if spr ~= nil then
                spr.events:off(syncSprite)
            end
        end

        checkFilename()
    end


    -- set up a websocket
    ws = WebSocket{
        url=table.concat{"http://", settings.host, ":", settings.port},
        onreceive=receive,
        deflate=false
    }

    --[[ global ]] pribambase_dlg = dlg
    app.events:on("sitechange", onAppChange)

    -- create an UI

    dlg:label{ id="status", text="Connecting..." }
    dlg:button{ id="reconnect", text="Reconnect", onclick=function() ws:close() ws:connect() end }
    dlg:newrow()
    dlg:button{ text="X Stop", onclick=cleanup }
    dlg:button{ text="_ Hide" }

    -- GO

    if --[[ global ]]pribambase_start then
        -- plugin is loading now
        -- FIXME remove this condition, it's not needed
        if pribambase_settings.autostart then
            ws:connect()

            if pribambase_settings.autoshow then
                dlg:show{ wait=false }
            end
        end
    else
        -- launched from the menu
        ws:connect()
        dlg:show{ wait=false }
    end
end