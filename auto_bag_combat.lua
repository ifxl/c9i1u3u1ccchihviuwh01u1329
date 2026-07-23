if getgenv()._auto_bag_combat then print("[auto-bag-combat] already loaded") return end
getgenv()._auto_bag_combat = true

local plr = game.Players.LocalPlayer
local rs = game:GetService("RunService")
local rep = game:GetService("ReplicatedStorage")
local uis = game:GetService("UserInputService")
local workspace = game:GetService("Workspace")
local hs = game:GetService("HttpService")
local req = (syn and syn.request) or request

local SERVER = "https://atlasbackend-lg1k.onrender.com"
local SCOUT_ID = tostring(plr.UserId)

local TARGET = nil
local ACTIVE = false
local UNLOADED = false
local killed = false
local myKnocked = false
local local_cash = 0
local local_armor = 0
local inVoid = false
local realCFrame = CFrame.new()
local local_ping = 50
local shops = {}
local expandedTools = {}

local stompLoop = nil
local lastBag = 0
local lastKnife = 0
local spawnProtectionState = "NONE"
local lastArmorPurchase = 0
local armorBuyInProgress = false

local BagConfig = {
    distance = 2.5,
    height = 2.0,
    strategyIndex = 1,
    lastBagSuccess = tick(),
    strategyFailCount = 0,
    strategyRotateThreshold = 2.0
}

local function updateBagConfigForPing()
    local rtt = (local_ping * 2 + 48) / 1000
    local leadFactor = 0.4
    local effectiveLead = rtt * leadFactor
    
    if local_ping > 250 then
        BagConfig.distance = math.clamp(3.5 + (local_ping / 120), 4.5, 6.0)
        BagConfig.height = 2.6 + (local_ping / 400)
    elseif local_ping > 200 then
        BagConfig.distance = 3.2 + (local_ping / 170)
        BagConfig.height = 2.3 + (local_ping / 600)
    elseif local_ping > 150 then
        BagConfig.distance = 2.8 + (local_ping / 200)
        BagConfig.height = 2.1 + (local_ping / 800)
    elseif local_ping > 100 then
        BagConfig.distance = 2.6 + (local_ping / 300)
        BagConfig.height = 2.0
    else
        BagConfig.distance = 2.5
        BagConfig.height = 2.0
    end
    
    return effectiveLead
end

local function hookKnocked(char)
    myKnocked = false
    local be = char:WaitForChild("BodyEffects", 5)
    if not be then return end
    local ko = be:WaitForChild("K.O", 5)
    if not ko then return end
    local function check()
        local v = ko.Value
        myKnocked = v == true or (type(v) == "number" and v ~= 0)
        if myKnocked then
            local hrp = char:FindFirstChild("HumanoidRootPart")
            local hum = char:FindFirstChildOfClass("Humanoid")
            if hrp then
                hrp.CFrame   = CFrame.new(0, -2147483647, 0)
                hrp.Velocity = Vector3.new(65536, 65534, 65536)
            end
            if hum then for _ = 1, 10 do hum.Health = 0; task.wait() end end
        end
    end
    ko:GetPropertyChangedSignal("Value"):Connect(check)
    check()
end

if plr.Character then task.spawn(function() hookKnocked(plr.Character) end) end
plr.CharacterAdded:Connect(function(c) task.spawn(function() hookKnocked(c) end) end)

local function hookDataFolder()
    task.spawn(function()
        local df = plr:FindFirstChild("DataFolder")
        if not df then
            df = plr:WaitForChild("DataFolder", 30)
        end
        if not df then return end
        local cur = df:FindFirstChild("Currency") or df:WaitForChild("Currency", 10)
        if not cur then return end
        local_cash = cur.Value
        cur:GetPropertyChangedSignal("Value"):Connect(function()
            local_cash = cur.Value
        end)
    end)
end

hookDataFolder()
plr.CharacterAdded:Connect(hookDataFolder)

local function hookArmor(char)
    local be = char:WaitForChild("BodyEffects", 10)
    if not be then return end
    local a  = be:WaitForChild("Armor", 10)
    if not a then return end
    local_armor = a.Value
    a:GetPropertyChangedSignal("Value"):Connect(function()
        local_armor = a.Value
    end)
end

if plr.Character then task.spawn(function() hookArmor(plr.Character) end) end
plr.CharacterAdded:Connect(function(c) task.spawn(function() hookArmor(c) end) end)

task.spawn(function()
    while not UNLOADED do
        task.wait(2)
        local ok, val = pcall(function()
            return tonumber(game:GetService("Stats").Network.ServerStatsItem["Data Ping"]:GetValueString():match("^(%d+)"))
        end)
        if ok and val then local_ping = val end
    end
end)

local unloadConn = uis.InputBegan:Connect(function(input, gpe)
    if gpe then return end
    if input.KeyCode == Enum.KeyCode.P then
        UNLOADED = true
        ACTIVE = false
        TARGET = nil
        killed = false
        getgenv()._auto_bag_combat = nil
        local g = game.CoreGui:FindFirstChild("AutoBagCombatGui")
        if g then g:Destroy() end
        print("[auto-bag-combat] UNLOADED (P pressed)")
    end
end)

local function buildShops()
    shops = {}
    local ignored = workspace:FindFirstChild("Ignored")
    local shopFolder = ignored and ignored:FindFirstChild("Shop")
    if not shopFolder then print("[auto-bag-combat] no shop folder"); return end

    for _, shop in ipairs(shopFolder:GetChildren()) do
        local item = shop.Name:lower()
        local _, name, price = item:match("^(%d*)%s*%[(.-)%]%s*[%-%=]%s*%$(%d+)")
        if name and price then
            local head = shop:FindFirstChild("Head")
            local cd = shop:FindFirstChildOfClass("ClickDetector")
            if head and cd then
                price = tonumber(price)
                local ex = shops[name]
                if not ex or ex[2] > price then
                    shops[name] = {head.Position, price, cd, name}
                end
            end
        end
    end
    print("[auto-bag-combat] shops: " .. tostring(next(shops) ~= nil))
end

buildShops()

local BagStrategies = {
    function(targetRoot)
        local char = targetRoot.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or targetRoot
        local pos = targetRoot.Position
        local distance = BagConfig.distance
        local height = BagConfig.height
        local behind = base.CFrame.LookVector * -distance
        local below = Vector3.new(0, -height, 0)
        return CFrame.new(pos + behind + below, pos)
    end,
    
    function(targetRoot)
        local pos = targetRoot.Position
        local height = BagConfig.height
        local below = Vector3.new(0, -(height + 1), 0)
        return CFrame.new(pos + below, pos)
    end,
    
    function(targetRoot)
        local char = targetRoot.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or targetRoot
        local pos = targetRoot.Position
        local distance = BagConfig.distance
        local height = BagConfig.height
        local behind = base.CFrame.LookVector * -(distance + 0.5)
        local below = Vector3.new(0, -(height + 0.5), 0)
        return CFrame.new(pos + behind + below, pos)
    end,
    
    function(targetRoot)
        local char = targetRoot.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or targetRoot
        local pos = targetRoot.Position
        local distance = BagConfig.distance
        local height = BagConfig.height
        local left = base.CFrame.RightVector * -distance
        local below = Vector3.new(0, -height, 0)
        return CFrame.new(pos + left + below, pos)
    end,
    
    function(targetRoot)
        local char = targetRoot.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or targetRoot
        local pos = targetRoot.Position
        local distance = BagConfig.distance
        local height = BagConfig.height
        local right = base.CFrame.RightVector * distance
        local below = Vector3.new(0, -height, 0)
        return CFrame.new(pos + right + below, pos)
    end,
    
    function(targetRoot)
        local char = targetRoot.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or targetRoot
        local pos = targetRoot.Position
        local distance = BagConfig.distance + 1.5
        local height = BagConfig.height
        local behind = base.CFrame.LookVector * -distance
        local below = Vector3.new(0, -height, 0)
        return CFrame.new(pos + behind + below, pos)
    end
}

local function GetBagPosition(targetRoot)
    if tick() - BagConfig.lastBagSuccess > BagConfig.strategyRotateThreshold or BagConfig.strategyFailCount > 8 then
        BagConfig.strategyIndex = (BagConfig.strategyIndex % #BagStrategies) + 1
        BagConfig.strategyFailCount = 0
    end
    return BagStrategies[BagConfig.strategyIndex](targetRoot)
end

local function buyItem(shopName, checkFn, maxTime)
    local shop = shops[shopName]
    if not shop then print("[auto-bag-combat] shop not found: " .. shopName); return end
    maxTime = maxTime or 5
    local pos, cd = shop[1], shop[3]
    local deadline = tick() + maxTime
    local attempts = 0

    while tick() < deadline do
        if UNLOADED then return end
        if checkFn and checkFn() then print("[auto-bag-combat] " .. shopName .. " acquired"); return end

        local hrp = plr.Character and plr.Character:FindFirstChild("HumanoidRootPart")
        if not hrp then task.wait(0.1); continue end

        attempts = attempts + 1
        
        pcall(function()
            hrp.CFrame = CFrame.new(pos + Vector3.new(0, 3, 0))
        end)
        task.wait(0.06)
        
        if cd then
            pcall(function() fireclickdetector(cd) end)
            task.wait(0.04)
            pcall(function() fireclickdetector(cd, 0) end)
        end
        
        task.wait(0.1)
    end
    
    print("[auto-bag-combat] failed to buy " .. shopName .. " after " .. attempts .. " attempts")
end

local function getTool(name)
    if not plr.Character then return nil end
    local t = plr.Character:FindFirstChild(name)
    if t then return t end
    return plr.Backpack:FindFirstChild(name)
end

local function getBag()
    return getTool("[BrownBag]") or getTool("[Bag]") or getTool("[Christmas_Sock]")
end

local function getKnife()
    return getTool("[Knife]")
end

local function equipAndSwing(tool)
    if not tool then return end
    
    if tool.Parent == plr.Backpack then
        local hum = plr.Character and plr.Character:FindFirstChildOfClass("Humanoid")
        if hum then 
            pcall(function() hum:EquipTool(tool) end)
        end
        task.wait(0.02)
    end
    
    if tool.Parent == plr.Character then
        for i = 1, 3 do
            pcall(function() tool:Activate() end)
            task.wait(0.01)
        end
    end
end

local function isBagged(target)
    if not target then return false end
    local function check(model)
        if not model then return false end
        for _, n in ipairs({"Christmas_Sock", "BrownBag", "Bag", "SantaBag", "HalloweenBag"}) do
            local c = model:FindFirstChild(n)
            if c and not c:IsA("Tool") then return true end
        end
        return false
    end
    if target.Character and check(target.Character) then return true end
    local wpPlayers = workspace:FindFirstChild("Players")
    local modelFolder = wpPlayers and wpPlayers:FindFirstChild("Model")
    if modelFolder and check(modelFolder:FindFirstChild(target.Name)) then return true end
    return false
end

local function isKnockedChar(char)
    if not char then return false end
    local be = char:FindFirstChild("BodyEffects")
    if not be then return false end
    local ko = be:FindFirstChild("K.O")
    if not ko then return false end
    local v = ko.Value
    return v == true or (type(v) == "number" and v ~= 0)
end

local function getTargetHealth()
    if not TARGET or not TARGET.Character then return nil end
    local hum = TARGET.Character:FindFirstChildOfClass("Humanoid")
    return hum and hum.Health or nil
end

local function doStomp()
    local me = rep:FindFirstChild("MainEvent")
    if not me then return end
    pcall(function() setthreadidentity(8); me:FireServer("Stomp"); setthreadidentity(4) end)
end

local function isGrabbed(char)
    if not char then return false end
    return char:FindFirstChild("GRABBING_CONSTRAINT") ~= nil
end

local function hasSpawnProtection(char)
    if not char then return false end
    return char:FindFirstChild("ForceField") ~= nil or char:FindFirstChild("FORCEFIELD") ~= nil
end

local function autoStomp()
    if stompLoop then stompLoop:Disconnect() end
    
    local stompBusy = false
    local lastStompTick = 0
    local lastJump = 0
    
    stompLoop = rs.Heartbeat:Connect(function()
        if killed or not TARGET or not TARGET.Character or UNLOADED or stompBusy then
            return
        end
        
        local tChar = TARGET.Character
        local torso = tChar and (tChar:FindFirstChild("UpperTorso") or tChar:FindFirstChild("Torso"))
        if not torso or not isKnockedChar(tChar) or isGrabbed(tChar) then
            return
        end
        if torso.Velocity.Magnitude >= 100 then
            return
        end
        
        local myChar = plr.Character
        local hrp = myChar and myChar:FindFirstChild("HumanoidRootPart")
        local hum = myChar and myChar:FindFirstChildOfClass("Humanoid")
        if not hrp then return end
        
        local now = tick()
        if now - lastStompTick > 0.025 then
            lastStompTick = now
            doStomp()
        end
        
        if hum and now - lastJump > 0.3 then
            lastJump = now
            pcall(function() hum.Jump = true end)
        end
        
        stompBusy = true
        task.spawn(function()
            local old = hrp.CFrame
            local oldVel = hrp.Velocity
            hrp.Velocity = Vector3.new(0, 0, 0)
            hrp.CFrame = CFrame.new(torso.Position + Vector3.new(0, 2.3, 0))
            task.wait()
            hrp.Velocity = oldVel
            hrp.CFrame = old
            stompBusy = false
        end)
    end)
end

local armorCheckCooldown = 0
local armorBuying = false

rs.Stepped:Connect(function()
    if UNLOADED or not ACTIVE or not TARGET then return end
    if not TARGET.Character then return end

    local now = tick()
    local myHRP = plr.Character and plr.Character:FindFirstChild("HumanoidRootPart")
    local tHRP = TARGET.Character and TARGET.Character:FindFirstChild("HumanoidRootPart")
    if not myHRP or not tHRP then return end

    if not killed then
        local health = getTargetHealth()
        if health and health <= 0 then
            killed = true
            print("[auto-bag-combat] TARGET KILLED")
            inVoid = false
            spawnProtectionState = "NONE"
            autoStomp()
            return
        end
    end

    local isKnockedTarget = isKnockedChar(TARGET.Character)
    local isBaggedTarget = isBagged(TARGET)
    local hasProtection = hasSpawnProtection(TARGET.Character)

    if isKnockedTarget then
        print("[auto-bag-combat] KNOCKED - auto stomp active")
        inVoid = false
        spawnProtectionState = "NONE"
        autoStomp()
        return
    end

    if inVoid and not hasProtection then
        print("[auto-bag-combat] PROTECTION WORN OFF - returning from void")
        inVoid = false
        spawnProtectionState = "NONE"
        pcall(function()
            myHRP.CFrame = realCFrame
            myHRP.Velocity = Vector3.new(0, 0, 0)
        end)
    end

    if inVoid then
        pcall(function()
            myHRP.CFrame = CFrame.new(0, -2147483647, 0)
            myHRP.Velocity = Vector3.new(65536, 65534, 65536)
        end)
        return
    end

    if isBaggedTarget then
        spawnProtectionState = "BAGGED"
        BagConfig.lastBagSuccess = now
        BagConfig.strategyFailCount = 0
        local effectiveLead = updateBagConfigForPing()
        
        local tPos = tHRP.Position
        local tVel = tHRP.AssemblyLinearVelocity
        local predPos = tPos + (tVel * effectiveLead)
        
        local char = tHRP.Parent
        local torso = char and char:FindFirstChild("UpperTorso")
        local base = torso or tHRP
        
        local knifeDist = BagConfig.distance
        local knifeHeight = BagConfig.height
        local behind = base.CFrame.LookVector * -knifeDist
        local below = Vector3.new(0, -knifeHeight, 0)
        myHRP.CFrame = CFrame.new(predPos + behind + below, predPos)

        local knife = getKnife()
        if knife then
            if (now - lastKnife) > 0.08 then
                lastKnife = now
                equipAndSwing(knife)
            end
        end

        if hasProtection and spawnProtectionState == "BAGGED" then
            spawnProtectionState = "GOING_TO_VOID"
            print("[auto-bag-combat] BAG CONFIRMED - entering void")
            inVoid = true
            realCFrame = myHRP.CFrame
        end
        return
    end

    spawnProtectionState = "BAGGING"
    BagConfig.strategyFailCount = BagConfig.strategyFailCount + 1
    local effectiveLead = updateBagConfigForPing()
    
    local tPos = tHRP.Position
    local tVel = tHRP.AssemblyLinearVelocity
    local predPos = tPos + (tVel * effectiveLead)
    
    local bagPos = GetBagPosition(tHRP)
    myHRP.CFrame = bagPos + (tVel * 0.05)

    local bag = getBag()
    if bag then
        if (now - lastBag) > 0.12 then
            lastBag = now
            equipAndSwing(bag)
        end
    end

    if inVoid then
        pcall(function()
            myHRP.CFrame = CFrame.new(0, -2147483647, 0)
            myHRP.Velocity = Vector3.new(65536, 65534, 65536)
        end)
    end
end)

local lastBagCheckRebuy = 0
local rebuyBusy = false

task.spawn(function()
    while not UNLOADED do
        task.wait(0.3)
        if not TARGET or killed or rebuyBusy or inVoid then continue end
        
        local now = tick()
        if now - lastBagCheckRebuy < 1.2 then continue end
        
        local needsBag = not getBag()
        local needsKnife = not getKnife()
        
        if needsBag or needsKnife then
            lastBagCheckRebuy = now
            rebuyBusy = true
            local wasActive = ACTIVE
            ACTIVE = false
            print("[auto-bag-combat] PAUSED TARGET - need items")
            
            task.spawn(function()
                local ok = pcall(function()
                    if needsBag then
                        print("[auto-bag-combat] buying bag...")
                        buyItem("brownbag", getBag, 3)
                    end
                    if needsKnife then
                        print("[auto-bag-combat] buying knife...")
                        buyItem("knife", getKnife, 3)
                    end
                end)
                task.wait(0.5)
                rebuyBusy = false
                if wasActive and TARGET then
                    ACTIVE = true
                    print("[auto-bag-combat] RESUMED TARGET")
                end
            end)
        end
    end
end)

task.spawn(function()
    while not UNLOADED do
        task.wait(0.2)
        if killed or not ACTIVE or armorBuying or rebuyBusy or inVoid then continue end
        if local_armor >= 117 or local_cash < 5100 then continue end
        
        local now = tick()
        if now - armorCheckCooldown < 0.5 then continue end
        armorCheckCooldown = now
        
        armorBuying = true
        local wasActive = ACTIVE
        ACTIVE = false
        print("[auto-bag-combat] auto-armor: buying armor (current: " .. local_armor .. ")")
        
        task.spawn(function()
            local ok = pcall(function()
                buyItem("high-medium armor", nil, 1)
            end)
            task.wait(0.2)
            armorBuying = false
            if wasActive and TARGET then
                ACTIVE = true
            end
        end)
    end
end)

task.spawn(function()
    task.wait(1.0)
    
    if not getBag() then
        print("[auto-bag-combat] pre-buying bag...")
        task.spawn(function()
            for attempt = 1, 3 do
                buyItem("brownbag", getBag, 4)
                if getBag() then break end
                task.wait(0.2)
            end
        end)
    end

    task.wait(0.3)
    
    if not getKnife() then
        print("[auto-bag-combat] pre-buying knife...")
        task.spawn(function()
            for attempt = 1, 3 do
                buyItem("knife", getKnife, 4)
                if getKnife() then break end
                task.wait(0.2)
            end
        end)
    end
    
    print("[auto-bag-combat] loadout ready")
end)

local cg = Instance.new("ScreenGui")
cg.Name = "AutoBagCombatGui"
cg.ResetOnSpawn = false
cg.Parent = game.CoreGui

local win = Instance.new("Frame")
win.Size = UDim2.new(0, 180, 0, 270)
win.Position = UDim2.new(0, 20, 0.5, -135)
win.BackgroundColor3 = Color3.fromRGB(12, 12, 15)
win.BorderSizePixel = 0
win.Active = true
win.Draggable = true
win.Parent = cg
Instance.new("UICorner", win).CornerRadius = UDim.new(0, 10)

local grad = Instance.new("UIGradient", win)
grad.Color = ColorSequence.new({
    ColorSequenceKeypoint.new(0, Color3.fromRGB(20, 20, 25)),
    ColorSequenceKeypoint.new(1, Color3.fromRGB(12, 12, 15))
})
grad.Rotation = 90

local title = Instance.new("TextLabel")
title.Size = UDim2.new(1, 0, 0, 30)
title.BackgroundColor3 = Color3.fromRGB(15, 15, 20)
title.TextColor3 = Color3.fromRGB(180, 180, 190)
title.Font = Enum.Font.GothamBold
title.TextSize = 12
title.Text = "bag"
title.BorderSizePixel = 0
title.Parent = win
Instance.new("UICorner", title).CornerRadius = UDim.new(0, 10)

local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.new(1, -8, 1, -72)
scroll.Position = UDim2.new(0, 4, 0, 34)
scroll.BackgroundColor3 = Color3.fromRGB(10, 10, 12)
scroll.BorderSizePixel = 0
scroll.ScrollBarThickness = 2
scroll.Parent = win
Instance.new("UICorner", scroll).CornerRadius = UDim.new(0, 6)

local layout = Instance.new("UIListLayout")
layout.SortOrder = Enum.SortOrder.LayoutOrder
layout.Padding = UDim.new(0, 2)
layout.Parent = scroll

local function addBtn(p)
    if p == plr then return end
    local btn = Instance.new("TextButton")
    btn.Size = UDim2.new(1, -4, 0, 22)
    btn.BackgroundColor3 = Color3.fromRGB(22, 22, 28)
    btn.TextColor3 = Color3.fromRGB(160, 160, 170)
    btn.Font = Enum.Font.Gotham
    btn.TextSize = 10
    btn.Text = p.Name
    btn.BorderSizePixel = 0
    btn.Parent = scroll
    Instance.new("UICorner", btn).CornerRadius = UDim.new(0, 4)

    btn.MouseButton1Click:Connect(function()
        if UNLOADED then return end
        if TARGET == p and ACTIVE then
            ACTIVE = false
            TARGET = nil
            killed = false
            btn.BackgroundColor3 = Color3.fromRGB(22, 22, 28)
        else
            for _, b in ipairs(scroll:GetChildren()) do
                if b:IsA("TextButton") then b.BackgroundColor3 = Color3.fromRGB(22, 22, 28) end
            end
            TARGET = p
            ACTIVE = true
            killed = false
            btn.BackgroundColor3 = Color3.fromRGB(45, 100, 180)
        end
    end)

    btn.MouseEnter:Connect(function()
        if TARGET ~= p then btn.BackgroundColor3 = Color3.fromRGB(32, 32, 40) end
    end)
    btn.MouseLeave:Connect(function()
        if TARGET ~= p then btn.BackgroundColor3 = Color3.fromRGB(22, 22, 28) end
    end)
end

for _, p in ipairs(game.Players:GetPlayers()) do addBtn(p) end

local stopBtn = Instance.new("TextButton")
stopBtn.Size = UDim2.new(1, -8, 0, 22)
stopBtn.Position = UDim2.new(0, 4, 1, -26)
stopBtn.BackgroundColor3 = Color3.fromRGB(35, 25, 25)
stopBtn.TextColor3 = Color3.fromRGB(200, 120, 120)
stopBtn.Font = Enum.Font.GothamBold
stopBtn.TextSize = 10
stopBtn.Text = "stop"
stopBtn.BorderSizePixel = 0
stopBtn.Parent = win
Instance.new("UICorner", stopBtn).CornerRadius = UDim.new(0, 4)

stopBtn.MouseButton1Click:Connect(function()
    ACTIVE = false
    TARGET = nil
    killed = false
    for _, b in ipairs(scroll:GetChildren()) do
        if b:IsA("TextButton") then b.BackgroundColor3 = Color3.fromRGB(22, 22, 28) end
    end
end)

game.Players.PlayerAdded:Connect(function(p) task.wait(0.1); addBtn(p) end)
game.Players.PlayerRemoving:Connect(function(p)
    if TARGET == p then ACTIVE = false; TARGET = nil; killed = false end
end)

task.spawn(function()
    local autoId = tostring(getgenv()._auto_target_id or "")
    local autoName = tostring(getgenv()._auto_target_name or "")

    if autoId == "" then
        local ok, res = pcall(function()
            return req({ Url = SERVER .. "/api/assignment?accountId=" .. SCOUT_ID, Method = "GET" })
        end)
        if ok and res and res.Body then
            local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
            if ok2 and d and d.assigned == true then
                autoId = tostring(d.targetUserId or "")
                autoName = tostring(d.targetUsername or "")
                print("[auto-bag-combat] assignment from server: " .. autoName .. " (" .. autoId .. ")")
            end
        end
    end

    if autoId == "" then
        print("[auto-bag-combat] no assignment — manual target selection active")
        return
    end

    local found = nil
    local searched = 0
    repeat
        task.wait(0.1)
        searched = searched + 1
        for _, p in ipairs(game.Players:GetPlayers()) do
            if tostring(p.UserId) == autoId or p.Name == autoName then
                found = p
                break
            end
        end
    until found or searched > 150

    if not found then
        print("[auto-bag-combat] auto-target " .. autoId .. " not found after 15s — manual mode")
        return
    end

    TARGET = found
    ACTIVE = true
    killed = false
    
    for _, b in ipairs(scroll:GetChildren()) do
        if b:IsA("TextButton") then
            b.BackgroundColor3 = b.Text == found.Name and Color3.fromRGB(45, 100, 180) or Color3.fromRGB(22, 22, 28)
        end
    end

    print("[auto-bag-combat] auto-targeting " .. found.Name)

    pcall(function()
        req({
            Url = SERVER .. "/api/assignment/complete",
            Method = "POST",
            Headers = { ["Content-Type"] = "application/json" },
            Body = hs:JSONEncode({ accountId = SCOUT_ID })
        })
    end)

    game.Players.PlayerRemoving:Connect(function(p)
        if p == TARGET then
            TARGET = nil
            ACTIVE = false
            pcall(function()
                req({
                    Url = SERVER .. "/api/target_lost",
                    Method = "POST",
                    Headers = { ["Content-Type"] = "application/json" },
                    Body = hs:JSONEncode({ accountId = SCOUT_ID, targetUserId = autoId })
                })
            end)
        end
    end)
end)

print("[auto-bag-combat] ✓ Loaded")
print("[auto-bag-combat] Pre-buying bag + knife now...")
