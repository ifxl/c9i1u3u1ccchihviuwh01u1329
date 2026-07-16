-- combat.lua — standalone, no hello.lua needed
-- GUI: pick target → strafe + shoot + auto gun/ammo/armor
-- auto stomp knocked targets
-- void hide when target has spawn protection
-- P = kill
-- When executed manually: shows player list, click to target
-- When loaded via agent.lua / loadstring: auto-targets via /api/assignment

local plr  = game.Players.LocalPlayer
local rs   = game:GetService("RunService")
local uis  = game:GetService("UserInputService")
local rep  = game:GetService("ReplicatedStorage")
local hs   = game:GetService("HttpService")
local req  = (syn and syn.request) or request

-- ── Sniper server config ──────────────────────────────────────
-- Change SERVER to match your deployment URL.
-- When run standalone (manual execute), SCOUT_ID is used to check for an
-- active assignment. If none found, falls back to the player-list GUI.
local SERVER   = "https://sniper-zlqd.onrender.com"
local SCOUT_ID = tostring(plr.UserId)

-- ── BYPASS — full AC kill (3 methods) + report block ─────────
-- Method A: getreg() nullification — replaces AC functions with no-ops in the registry
-- Method B: Framework signal disconnect — walks getconnections and disconnects AC
-- Method C: RBXScriptSignal.__index hook — prevents any future AC Connect calls
-- Report block: __namecall hook drops REPORT_PLAYER/InvokeServer packets targeting you
do
	if not getgenv()._bypass_done then

		-- ── Method A: getreg nullify ──────────────────────────
		local reg = getreg()
		local nulled = 0
		for i, v in pairs(reg) do
			if type(v) == "function" and islclosure(v) then
				local ok, info = pcall(debug.getinfo, v)
				if ok and info and info.source then
					local _, dots = info.source:gsub("%.", "")
					if dots == 1 and not info.source:find("Replicated") then
						if (debug.getupvalues(v) or {})[2] ~= 26 then
							reg[i] = function() end
							nulled += 1
						end
					end
				end
			end
		end

		-- ── Method B: Framework signal disconnect ─────────────
		local disconnected = 0
		local function killConns(sig)
			local ok, conns = pcall(getconnections, sig)
			if not ok then return end
			for _, c in ipairs(conns) do
				if c.Function then
					local ok2, info = pcall(debug.getinfo, c.Function)
					if ok2 and info and info.source
					   and info.source:find("Framework")
					   and not info.source:find("GarageModule") then
						pcall(function() c:Disconnect() end)
						disconnected += 1
					end
				end
			end
		end
		local rs2 = game:GetService("RunService")
		killConns(rs2.Heartbeat)
		killConns(rs2.Stepped)
		killConns(rs2.RenderStepped)
		-- all RemoteEvents
		for _, v in ipairs(game:GetService("ReplicatedStorage"):GetDescendants()) do
			if v:IsA("RemoteEvent") then
				local ok, conns = pcall(getconnections, v.OnClientEvent)
				if ok then
					for _, c in ipairs(conns) do
						if c.Function then
							local ok2, info = pcall(debug.getinfo, c.Function)
							if ok2 and info and info.source and info.source:find("Framework") then
								pcall(function() c:Disconnect() end)
								disconnected += 1
							end
						end
					end
				end
			end
		end

		-- ── Method C: signal.__index hook — block future connects
		pcall(function()
			local signal = getreg()["RBXScriptSignal"]
			local conn   = getreg()["RBXScriptConnection"]
			if signal and signal.__index then
				local old_idx
				old_idx = hookfunction(signal.__index, function(self, index)
					if index == "Connect" or index == "connect" then
						local caller = debug.getinfo(2)
						if caller and caller.source then
							local _, dots = caller.source:gsub("%.", "")
							if dots == 1 and not caller.source:find("Replicated") then
								return function()
									return setrawmetatable(newproxy(), conn)
								end
							end
						end
					end
					return old_idx(self, index)
				end)
			end
		end)

		getgenv()._bypass_done = true
		print(string.format("[bypass] done — nulled:%d disconn:%d", nulled, disconnected))
	else
		print("[bypass] already ran")
	end
end

-- ── REPORT BLOCK ─────────────────────────────────────────────
-- NOTE: uses plr which is declared above in the bypass block's outer scope
-- Blocks REPORT_PLAYER + known AC check packets
do
	if not getgenv()._reportblock_done then
		local BLOCKED = {
			REPORT_PLAYER=true, TeleportDetect=true, CHECKER_1=true,
			CHECKER=true, CHECKER_4=true, GUI_CHECK=true, OneMoreTime=true,
			checkingSPEED=true, BANREMOTE=true, PERMAIDBAN=true,
			KICKREMOTE=true, BR_KICKPC=true, BR_KICKMOBILE=true,
			CalculateShootClient=true,
		}
		local _rb_old
		_rb_old = hookmetamethod(game, "__namecall", function(self, ...)
			local method = getnamecallmethod()
			local args   = {...}
			local packet = tostring(args[1] or "")
			-- block known AC packets
			if BLOCKED[packet] then return end
			-- block report packets targeting local player
			if method == "FireServer" or method == "InvokeServer" then
				local target = tostring(args[2] or ""):lower()
				local lp = game.Players.LocalPlayer
				if lp and (packet == "REPORT_PLAYER" or packet:lower():find("report"))
				   and target == lp.Name:lower() then
					return
				end
			end
			return _rb_old(self, ...)
		end)
		getgenv()._reportblock_done = true
		print("[report_block] active")
	end
end

-- ── all state vars declared FIRST ────────────────────────────
local killed          = false
local targetPlayer    = nil
local strafeAngle     = 0
local strafeT         = 0
local myKnocked       = false
local local_cash      = 0
local local_armor     = 0
local local_reloading = false
local local_guns      = {}
local local_ping         = 50
local local_bought_count = 0
local serverCFrame       = CFrame.new()
local stomping           = false
local in_void            = false
local voidHideEnabled    = true
local autoStompEnabled   = true
local lastStompTick      = 0
local purchasing         = false  -- true while any buy is in progress (blocks auto ammo)

-- ── server position tracker ───────────────────────────────────
-- Only updates when NOT evading so the shoot loop uses real server origin
rs.Heartbeat:Connect(function()
	local c = plr.Character
	local h = c and c:FindFirstChild("HumanoidRootPart")
	if h and not in_void then serverCFrame = h.CFrame end
end)

-- ── cash + inventory — DataFolder ────────────────────────────
-- local_bought_count increments when cash decreases (hello.lua line 25702)
-- inventory used for auto ammo clip counting (hello.lua: inventory[gun.Name].Value)
local inventory = nil
task.spawn(function()
	local df  = plr:WaitForChild("DataFolder", 10)
	if not df then return end
	local cur = df:WaitForChild("Currency", 10)
	if not cur then return end
	local_cash = cur.Value
	cur:GetPropertyChangedSignal("Value"):Connect(function()
		local new_cash = cur.Value
		if new_cash < local_cash then
			local_bought_count += 1
		end
		local_cash = new_cash
	end)
	-- inventory folder: hello.lua uses inventory[gun.Name].Value for ammo counts
	inventory = df:FindFirstChild("Inventory") or df:WaitForChild("Inventory", 10)
end)

-- ── armor — BodyEffects.Armor ─────────────────────────────────
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

-- ── local_guns + reload tracking ─────────────────────────────
local function trackGuns(char)
	local_guns = {}
	local function add(child)
		if not child:IsA("Tool") then return end
		local n = child.Name:lower()
		if n:find("knife") or n:find("bat") or n:find("fist") or n:find("whip") or n:find("taser") or n:find("pipe") then return end
		local handle = child:FindFirstChild("Handle")
		if not handle then return end
		local range = child:FindFirstChild("Range")
		local ammo  = child:FindFirstChild("Ammo")
		local entry = {handle, range and range.Value or 9e9, ammo and ammo.Value or 99}
		if ammo then
			ammo:GetPropertyChangedSignal("Value"):Connect(function() entry[3] = ammo.Value end)
		end
		local_guns[handle] = entry
	end
	local function rem(child)
		if not child:IsA("Tool") then return end
		local h = child:FindFirstChild("Handle")
		if h then local_guns[h] = nil end
	end
	char.ChildAdded:Connect(add)
	char.ChildRemoved:Connect(rem)
	for _, v in ipairs(char:GetChildren()) do add(v) end
	local be = char:WaitForChild("BodyEffects", 5)
	if be then
		local r = be:WaitForChild("Reload", 5)
		if r then
			local_reloading = r.Value
			r:GetPropertyChangedSignal("Value"):Connect(function() local_reloading = r.Value end)
		end
	end
end
if plr.Character then task.spawn(function() trackGuns(plr.Character) end) end
plr.CharacterAdded:Connect(function(c) task.wait(0.3); trackGuns(c) end)

-- ── my knocked + anti-stomp respawn ──────────────────────────
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

-- ── ping tracker ──────────────────────────────────────────────
task.spawn(function()
	while true do
		task.wait(2)
		local ok, val = pcall(function()
			return tonumber(game:GetService("Stats").Network.ServerStatsItem["Data Ping"]:GetValueString():match("^(%d+)"))
		end)
		if ok and val then local_ping = val end
	end
end)

-- ── MainEvent ─────────────────────────────────────────────────
local event = rep:WaitForChild("MainEvent", 10)
if not event then print("[combat] no MainEvent"); return end

-- ── helpers ───────────────────────────────────────────────────
local function isKnockedChar(char)
	if not char then return true end
	local be = char:FindFirstChild("BodyEffects"); if not be then return false end
	local ko = be:FindFirstChild("K.O"); if not ko then return false end
	local v = ko.Value
	return v == true or (type(v) == "number" and v ~= 0)
end

local function hasSpawnProtection(char)
	if not char then return false end
	return char:FindFirstChild("ForceField") ~= nil or char:FindFirstChild("FORCEFIELD") ~= nil
end

local function isGrabbed(char)
	if not char then return false end
	return char:FindFirstChild("GRABBING_CONSTRAINT") ~= nil
end

local function findGunAnywhere()
	local function isGun(v)
		if not v:IsA("Tool") or not v:FindFirstChild("Handle") then return false end
		local n = v.Name:lower()
		return not (n:find("knife") or n:find("bat") or n:find("fist") or n:find("whip") or n:find("taser") or n:find("pipe"))
	end
	if plr.Character then
		for _, v in ipairs(plr.Character:GetChildren()) do if isGun(v) then return v end end
	end
	for _, v in ipairs(plr.Backpack:GetChildren()) do if isGun(v) then return v end end
	return nil
end

-- equip via Humanoid:EquipTool — clean, triggers proper animations
-- only use setscriptable for mid-buy temporary moves
local function equipGun(gun)
	local char = plr.Character
	if not char or not gun then return end
	local hum = char:FindFirstChildOfClass("Humanoid")
	if hum then
		pcall(function() hum:EquipTool(gun) end)
	else
		-- fallback if humanoid not found
		pcall(function()
			setscriptable(gun, "Parent", true)
			gun.Parent = char
		end)
	end
end

local function unequipToBackpack(gun)
	if not gun then return end
	pcall(function()
		setscriptable(gun, "Parent", true)
		gun.Parent = plr.Backpack
	end)
end

-- find a rifle specifically (not phone, not cash, not any random tool)
local function findRifleAnywhere()
	local function isRifleTool(v)
		return v:IsA("Tool") and v.Name:lower():find("rifle]", 1, true)
	end
	if plr.Character then
		for _, v in ipairs(plr.Character:GetChildren()) do if isRifleTool(v) then return v end end
	end
	for _, v in ipairs(plr.Backpack:GetChildren()) do if isRifleTool(v) then return v end end
	return nil
end

local function hasRifle()
	local function check(v)
		return v:IsA("Tool") and v.Name:lower():find("rifle]", 1, true)
	end
	if plr.Character then
		for _, v in ipairs(plr.Character:GetChildren()) do if check(v) then return true end end
	end
	for _, v in ipairs(plr.Backpack:GetChildren()) do if check(v) then return true end end
	-- NOTE: do NOT check local_guns here — it can be empty mid-buy (gun temporarily
	-- unequipped during the buy loop) causing a false negative and re-purchasing the rifle
	return false
end

-- ── shop ──────────────────────────────────────────────────────
-- shops[name] = {pos, price, cd, ammoCount|false, category, name, head}
-- matches hello.lua 7-field table; index [6] = name string used in purchasing checks
local shops = {}
local function buildShops()
	shops = {}
	local ignored = workspace:FindFirstChild("Ignored")
	local shopF   = ignored and ignored:FindFirstChild("Shop")
	if not shopF then print("[combat] no Shop folder"); return end
	for _, shop in ipairs(shopF:GetChildren()) do
		local item  = shop.Name:lower()
		local aStr, name, price = item:match("^(%d*)%s*%[(.-)%]%s*[%-%=]%s*%$(%d+)")
		if name and price then
			local head = shop:FindFirstChild("Head")
			local cd   = shop:FindFirstChildOfClass("ClickDetector")
			if head and cd then
				price = tonumber(price)
				local existing = shops[name]
				if not existing or existing[2] > price then
					shops[name] = {
						head.Position,           -- [1]
						price,                   -- [2]
						cd,                      -- [3]
						tonumber(aStr) or false, -- [4] ammo per purchase
						false,                   -- [5] category
						name,                    -- [6] name string (hello.lua purchasing[6])
						head                     -- [7] head part
					}
				end
			end
		end
	end
	print("[combat] shops loaded: " .. tostring(next(shops) ~= nil))
	if shops["high-medium armor"] then
		print("[combat] armor shop $" .. shops["high-medium armor"][2])
	else
		print("[combat] armor shop NOT found — available:")
		for k in pairs(shops) do if k:find("armor") then print("  " .. k) end end
	end
end
buildShops()

-- ── buy — exact hello.lua purchase_function logic ────────────
-- Order: fireclickdetector → teleport HRP → wait one frame → restore
-- Loops until local_bought_count increments (cash decreased) or timeout
-- Timeout: ping*2 + count*0.36s (exact hello.lua formula)
-- Non-armor: unequip guns to backpack first, re-equip after (hello.lua does this)
-- `purchasing` flag: set true while buying, blocks auto ammo / other buys

local function unequipGuns()
	local char    = plr.Character
	local removed = {}
	if not char then return removed end
	for _, tool in ipairs(char:GetChildren()) do
		if tool:IsA("Tool") then
			pcall(function()
				tool.Parent = plr.Backpack
				table.insert(removed, tool)
			end)
		end
	end
	return removed
end

local function reequipTools(tools)
	local char = plr.Character
	if not char then return end
	for _, tool in ipairs(tools) do
		pcall(function() tool.Parent = char end)
	end
end

-- doBuy: the actual loop — matches hello.lua purchase_function exactly
-- isArmor skips gun unequip (hello.lua: skip = purchasing[6]:find("armor"))
local function doBuy(name, count, isArmor)
	local item = shops[name]
	if not item then print("[buy] not found: " .. name); return false end

	local char = plr.Character
	local hrp  = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return false end

	local startCount = local_bought_count
	local target     = startCount + (count or 1)
	local ping       = local_ping / 1000

	-- High-ping aware timeout:
	-- Each purchase attempt takes at least ping*2 for round-trip.
	-- For 10 ammo at 700ms ping: need at least 10 * 1.4s = 14s.
	-- Use: max(30s, ping*2*count + 5s buffer) so it never fails on high ping.
	local timeout = math.max(ping * 2 * (count or 1) + 5, 30)
	local deadline = tick() + timeout

	in_void = false  -- pause evasion during buy

	local removed = {}
	if not isArmor then removed = unequipGuns() end

	-- click every frame — server confirms when local_bought_count increments
	-- don't throttle clicks, high ping needs repeated attempts
	while local_bought_count < target and tick() < deadline do
		if myKnocked then break end
		local c = plr.Character
		hrp = c and c:FindFirstChild("HumanoidRootPart")
		if not hrp then break end
		local oldCF = hrp.CFrame
		pcall(function() fireclickdetector(item[3]) end)
		pcall(function() hrp.CFrame = CFrame.new(item[1] - Vector3.new(0, 8.8, 0)) end)
		task.wait()
		pcall(function() hrp.CFrame = oldCF end)
	end

	in_void = false

	if not isArmor and #removed > 0 and not myKnocked then
		for _, tool in ipairs(removed) do
			if tool and tool.Parent == plr.Backpack then
				pcall(function()
					setscriptable(tool, "Parent", true)
					tool.Parent = plr.Character
				end)
				task.wait(0.03)
			end
		end
	end

	local success = local_bought_count >= target
	print(string.format("[buy] %s — %s (ping:%dms)", name, success and "OK" or "FAILED", local_ping))
	return success
end

local function buy(name, count)
	if purchasing then return end  -- never stack buys
	local isArmor = name:find("armor") ~= nil
	purchasing = true
	task.spawn(function()
		local done = false
		task.delay(60, function() if not done then purchasing = false end end)
		pcall(function() doBuy(name, count or 1, isArmor) end)
		done = true
		purchasing = false
	end)
end

local function buyArmor()
	if purchasing then return end
	purchasing = true
	task.spawn(function()
		local done = false
		task.delay(60, function() if not done then purchasing = false end end)
		pcall(function() doBuy("high-medium armor", 1, true) end)
		done = true
		purchasing = false
	end)
end

-- ── auto armor ────────────────────────────────────────────────
-- hello.lua: threshold = 130 * (pct/100), default was 40% (52)
-- Set to 90% (117) so it tops up immediately after taking any hit
local lastArmor = 0
rs.Heartbeat:Connect(function()
	if killed or myKnocked then return end
	if purchasing and shops["high-medium armor"] and shops["high-medium armor"][6]:find("armor") then return end
	if tick() - lastArmor < 0.05 then return end
	if local_armor < 117 and local_cash > 5000 then  -- 117 = 90% of 130 max
		lastArmor = tick()
		buyArmor()
	end
end)

-- ── auto reload ───────────────────────────────────────────────
local reloadCooldowns = {}
rs.Heartbeat:Connect(function()
	if killed or myKnocked then return end
	if local_reloading then return end
	local now  = tick()
	local char = plr.Character
	-- clean up stale handles periodically
	if now % 5 < 0.1 then
		for h in pairs(reloadCooldowns) do
			if not h.Parent then reloadCooldowns[h] = nil end
		end
	end
	for h, data in pairs(local_guns) do
		local gun = h.Parent; if not gun then continue end
		-- only reload guns actually equipped (in character), not in backpack
		if not char or gun.Parent ~= char then continue end
		if (now - (reloadCooldowns[h] or 0)) < 0.15 then continue end
		local isRifle = gun.Name == "[Rifle]" or gun.Name == "[Flintlock]"
		local needsReload = (isRifle and data[3] <= 1) or (not isRifle and data[3] == 0)
		if needsReload then
			reloadCooldowns[h] = now
			setthreadidentity(8)
			event:FireServer("Reload", gun)
			setthreadidentity(4)
			return
		end
	end
end)

-- ── auto ammo ─────────────────────────────────────────────────
local lastAutoAmmo = 0
rs.Heartbeat:Connect(function()
	-- don't buy ammo while guns are unequipped for a shop buy, or while reloading
	if killed or myKnocked or purchasing or local_reloading then return end
	if tick() - lastAutoAmmo < 1.5 then return end
	if not inventory then return end
	lastAutoAmmo = tick()
	for h, data in pairs(local_guns) do
		local gun = h.Parent
		-- CRITICAL: only buy ammo for guns currently in the CHARACTER, not backpack
		-- buying ammo while gun is in backpack causes the loop to stall
		if not gun then
			local_guns[h] = nil  -- clean dead handle
			continue
		end
		local char = plr.Character
		if not char or gun.Parent ~= char then continue end  -- must be equipped
		local maxAmmoObj = gun:FindFirstChild("MaxAmmo")
		if not maxAmmoObj then continue end
		local invSlot = inventory:FindFirstChild(gun.Name)
		if not invSlot then continue end
		local clips = math.floor(tonumber(invSlot.Value) / math.max(maxAmmoObj.Value, 1))
		if clips < 1 then
			local ammoKey = gun.Name:sub(2, -2):lower() .. " ammo"
			if shops[ammoKey] and local_cash >= shops[ammoKey][2] then
				buy(ammoKey, 10)
				return  -- buy one gun's ammo at a time
			end
		end
	end
end)

-- ── auto loadout ──────────────────────────────────────────────
-- Loadout: rifle, aug, flintlock — matches hello.lua auto_loadout_guns order
-- Each gun: buy if missing, equip via setscriptable, buy ammo if low
local LOADOUT_GUNS = {
	{shopKey = "rifle",     nameMatch = "rifle]",     ammoClips = 10},
	{shopKey = "aug",       nameMatch = "aug]",        ammoClips = 10},
	{shopKey = "flintlock", nameMatch = "flintlock]",  ammoClips = 10},
}

local function findLoadoutGun(nameMatch)
	local function matches(v)
		return v:IsA("Tool") and v.Name:lower():find(nameMatch, 1, true)
	end
	if plr.Character then
		for _, v in ipairs(plr.Character:GetChildren()) do if matches(v) then return v end end
	end
	for _, v in ipairs(plr.Backpack:GetChildren()) do if matches(v) then return v end end
	return nil
end

local function hasLoadoutGun(nameMatch)
	return findLoadoutGun(nameMatch) ~= nil
end

local loadoutBusy = false
local function doLoadout()
	if loadoutBusy then return end
	loadoutBusy = true
	task.spawn(function()
		-- Wait for cash to load before attempting any purchases
		-- local_cash starts at 0 and only updates after DataFolder/Currency resolves
		if local_cash <= 0 then
			local waited = 0
			repeat task.wait(0.5); waited += 0.5 until local_cash > 0 or waited >= 20
		end
		if local_cash <= 0 then
			print("[loadout] cash still 0 after 20s — skipping")
			loadoutBusy = false
			return
		end
		for _, entry in ipairs(LOADOUT_GUNS) do
			if killed then break end

			-- buy if missing — wait for purchasing to clear before continuing
			if not hasLoadoutGun(entry.nameMatch) then
				if shops[entry.shopKey] and local_cash >= shops[entry.shopKey][2] then
					print("[loadout] buying " .. entry.shopKey)
					buy(entry.shopKey)
					-- wait for the buy to fully complete
					local t = 0
					repeat task.wait(0.1); t += 0.1
					until (not purchasing and hasLoadoutGun(entry.nameMatch)) or t > 10
				else
					print("[loadout] skip " .. entry.shopKey .. " — need $" ..
						(shops[entry.shopKey] and shops[entry.shopKey][2] or "?") ..
						" have $" .. local_cash)
				end
			end

			-- equip if in backpack
			local gun = findLoadoutGun(entry.nameMatch)
			if gun and gun.Parent == plr.Backpack then
				equipGun(gun)
				task.wait(0.3)
			end

			-- buy ammo if low — wait for the buy to fully complete
			gun = findLoadoutGun(entry.nameMatch)
			if gun and inventory then
				local maxAmmoObj = gun:FindFirstChild("MaxAmmo")
				local invSlot    = inventory:FindFirstChild(gun.Name)
				if maxAmmoObj and invSlot then
					local clips = math.floor(tonumber(invSlot.Value) / math.max(maxAmmoObj.Value, 1))
					if clips < 1 then
						local ammoKey = gun.Name:sub(2, -2):lower() .. " ammo"
						if shops[ammoKey] and local_cash >= shops[ammoKey][2] then
							print("[loadout] buying ammo: " .. ammoKey)
							buy(ammoKey, entry.ammoClips)
							local t = 0
							repeat task.wait(0.1); t += 0.1 until not purchasing or t > 15
						end
					end
				else
					local ammo = gun:FindFirstChild("Ammo")
					if ammo and ammo.Value < 5 then
						local ammoKey = gun.Name:sub(2, -2):lower() .. " ammo"
						if shops[ammoKey] and local_cash >= shops[ammoKey][2] then
							print("[loadout] buying ammo (fallback): " .. ammoKey)
							buy(ammoKey, entry.ammoClips)
							local t = 0
							repeat task.wait(0.1); t += 0.1 until not purchasing or t > 15
						end
					end
				end
			end
		end
		loadoutBusy = false
	end)
end

-- auto-equip heartbeat: keep loadout guns equipped while targeting
-- throttled — only checks once per second to avoid spamming EquipTool every frame
local lastEquipCheck = 0
rs.Heartbeat:Connect(function()
	if killed or myKnocked or purchasing then return end
	if not targetPlayer then return end
	local now = tick()
	if now - lastEquipCheck < 1 then return end
	lastEquipCheck = now
	local char = plr.Character; if not char then return end
	for _, entry in ipairs(LOADOUT_GUNS) do
		local gun = findLoadoutGun(entry.nameMatch)
		if gun and gun.Parent == plr.Backpack then
			equipGun(gun)
			break  -- equip one at a time per check
		end
	end
end)

task.spawn(function()
	while not killed do
		task.wait(5)
		if not purchasing and local_cash > 0 then
			-- check if any loadout gun is missing and rerun
			for _, entry in ipairs(LOADOUT_GUNS) do
				if not hasLoadoutGun(entry.nameMatch) then
					task.spawn(doLoadout)
					break
				end
			end
		end
	end
end)

plr.CharacterAdded:Connect(function()
	if not killed then task.wait(2); task.spawn(doLoadout) end
end)

-- ── AUTO STOMP ────────────────────────────────────────────────
local stompBusy = false
local lastJump  = 0
task.spawn(function()
	while not killed do
		task.wait(0.016)
		if not autoStompEnabled or myKnocked or in_void then
			stomping = false
			continue
		end
		if not targetPlayer or stompBusy then continue end

		local tChar = targetPlayer.Character
		local torso = tChar and (tChar:FindFirstChild("UpperTorso") or tChar:FindFirstChild("Torso"))
		if not torso or not isKnockedChar(tChar) or isGrabbed(tChar) then
			stomping = false; continue
		end
		if torso.Velocity.Magnitude >= 100 then stomping = false; continue end

		local myChar = plr.Character
		local hrp    = myChar and myChar:FindFirstChild("HumanoidRootPart")
		local hum    = myChar and myChar:FindFirstChildOfClass("Humanoid")
		if not hrp then stomping = false; continue end

		-- fire Stomp packet at 40Hz
		local now = tick()
		if now - lastStompTick > 0.025 then
			lastStompTick = now
			setthreadidentity(8)
			event:FireServer("Stomp")
			setthreadidentity(4)
		end

		-- jump every 0.3s while stomping so it looks natural
		if hum and now - lastJump > 0.3 then
			lastJump = now
			pcall(function() hum.Jump = true end)
		end

		-- teleport on top for one frame then restore
		stomping = true
		stompBusy = true
		task.spawn(function()
			local old    = hrp.CFrame
			local oldVel = hrp.Velocity
			hrp.Velocity = Vector3.new(0, 0, 0)
			hrp.CFrame   = CFrame.new(torso.Position + Vector3.new(0, 2.3, 0))
			task.wait()
			hrp.Velocity = oldVel
			hrp.CFrame   = old
			stompBusy = false
		end)
	end
end)

-- ── FAKE POSITION / EVASION ──────────────────────────────────
-- Active when: target has spawn protection OR we are reloading.
-- PAUSED when: purchasing (buy loop needs the real HRP position to click the shop).
-- After evasion ends while guns are missing, re-equip is triggered automatically.
local evasionBusy = false
local EVASION_OFFSETS = {
	-- Keep offsets small — within normal movement range to avoid velocity-based AC detection
	-- Max ~40 studs, mixed directions so position changes look like rapid movement not teleport
	Vector3.new( 35,  8,  35),
	Vector3.new(-35,  8,  35),
	Vector3.new( 35,  8, -35),
	Vector3.new(-35,  8, -35),
	Vector3.new( 25, 12,   0),
	Vector3.new(-25, 12,   0),
	Vector3.new(  0, 12,  25),
	Vector3.new(  0, 12, -25),
}
local evasionIdx = 0
local wasEvading = false

rs.Heartbeat:Connect(function()
	local shouldEvade = false
	if voidHideEnabled and not purchasing then  -- STOP evasion while buying
		if targetPlayer and hasSpawnProtection(targetPlayer.Character) then
			shouldEvade = true
		end
		if local_reloading then
			shouldEvade = true
		end
		-- stay in evasion while WE are being grabbed (can't fight back anyway)
		local myChar = plr.Character
		if myChar and isGrabbed(myChar) then
			shouldEvade = true
		end
	end

	-- when evasion just ended, check if guns need re-equipping
	if wasEvading and not shouldEvade then
		wasEvading = false
		in_void = false
		-- re-equip any loadout guns that ended up in backpack after evasion
		task.spawn(function()
			task.wait(0.1)
			local char = plr.Character; if not char then return end
			for _, entry in ipairs(LOADOUT_GUNS) do
				local gun = findLoadoutGun(entry.nameMatch)
				if gun and gun.Parent == plr.Backpack then
					equipGun(gun)
					task.wait(0.05)
				end
			end
		end)
	end

	if not shouldEvade or killed or myKnocked or evasionBusy then
		if not shouldEvade then in_void = false end
		return
	end

	local myChar = plr.Character
	local hrp    = myChar and myChar:FindFirstChild("HumanoidRootPart")
	if not hrp then in_void = false; return end

	in_void = true
	wasEvading = true
	evasionBusy = true
	task.spawn(function()
		local realCF  = hrp.CFrame
		local realVel = hrp.Velocity
		evasionIdx = (evasionIdx % #EVASION_OFFSETS) + 1
		local fakePos = EVASION_OFFSETS[evasionIdx] + Vector3.new(
			math.random(-50, 50), math.random(0, 20), math.random(-50, 50)
		)
		hrp.CFrame = CFrame.new(fakePos)
		task.wait()   -- one Heartbeat frame — doesn't stall when standing still
		hrp.CFrame   = realCF
		hrp.Velocity = realVel
		evasionBusy = false
	end)
end)


-- ── SHOOT LOOP ────────────────────────────────────────────────
-- Improvements over previous version:
-- - Fire rate reduced to 0.05s (was 0.07) — more aggressive
-- - Multi-frame velocity history for smoother prediction
-- - Strafe compensation: predict WHERE the target will be based on their strafe pattern
-- - Double-tap rifles: fire the packet twice per tick for better server reg
-- - Aim at UpperTorso as fallback when head is obscured
local lastFire      = 0
local headHistory   = {}   -- rolling buffer of {pos, t} for velocity smoothing
local MAX_HIST      = 6

local function smoothVelocity()
	if #headHistory < 2 then return Vector3.new() end
	local oldest = headHistory[1]
	local newest = headHistory[#headHistory]
	local dt = newest[2] - oldest[2]
	if dt <= 0 then return Vector3.new() end
	return (newest[1] - oldest[1]) / dt
end

task.spawn(function()
	while not killed do
		task.wait(0.016)
		if myKnocked or not targetPlayer then continue end
		if tick() - lastFire < 0.05 then continue end  -- 20Hz max fire rate
		if local_reloading then continue end

		local tChar = targetPlayer.Character
		if not tChar or isKnockedChar(tChar) then continue end
		if hasSpawnProtection(tChar) then continue end

		local myChar = plr.Character
		local myHrp  = myChar and myChar:FindFirstChild("HumanoidRootPart")
		if not myHrp then continue end

		local head  = tChar:FindFirstChild("Head")
		local tHrp  = tChar:FindFirstChild("HumanoidRootPart")
		local torso = tChar:FindFirstChild("UpperTorso") or tChar:FindFirstChild("Torso")
		if not (head or torso) then continue end

		-- update velocity history
		local now      = tick()
		local aimAnchor = head and head.Position or torso.Position
		table.insert(headHistory, {aimAnchor, now})
		if #headHistory > MAX_HIST then table.remove(headHistory, 1) end

		-- smoothed velocity from history
		local vel      = smoothVelocity()
		local speed    = vel.Magnitude
		local ping     = local_ping / 1000
		-- lead time: ping/2 for hitscan reg, clamped
		local leadTime = math.clamp(ping * 0.5, 0.016, 0.12)

		local aimPos
		if speed > 120 then
			-- fast teleport/hacker: aim at torso center + lead, wider target
			local center = tHrp and tHrp.Position or aimAnchor
			aimPos = center + vel * leadTime
		elseif speed > 30 then
			-- strafing: use head + full velocity lead
			aimPos = aimAnchor + vel * leadTime
		else
			-- stationary or slow: aim directly at head, tiny lead
			aimPos = aimAnchor + vel * (leadTime * 0.5)
		end

		-- micro-jitter to avoid identical ray patterns
		aimPos = aimPos + Vector3.new(
			math.random(-2, 2) * 0.008,
			math.random(-1, 1) * 0.006,
			math.random(-1, 1) * 0.006
		)

		local origin = serverCFrame.Position + Vector3.new(0.004, 3.0208, -0.048)
		local dir    = origin - aimPos
		local mag    = dir.Magnitude
		local fDir   = (mag <= 0 or mag ~= mag) and Vector3.new(0, 0, -1) or dir.Unit
		local hitPart = head or torso

		-- Find the single currently equipped gun to fire.
		-- ONLY fire the tool that is actually in Character right now.
		-- Never fire multiple handles — that's what causes the tool error kick.
		-- Priority: rifle/flintlock first (highest DPS), then any other equipped gun.
		local equippedHandle = nil
		local equippedData   = nil
		local char = plr.Character
		if char then
			-- first pass: look for rifle/flintlock specifically
			for h, data in pairs(local_guns) do
				local g = h.Parent
				if g and g.Parent == char then
					if g.Name == "[Rifle]" or g.Name == "[Flintlock]" then
						equippedHandle = h
						equippedData   = data
						break
					end
				end
			end
			-- second pass: any other gun in character (not backpack)
			if not equippedHandle then
				for h, data in pairs(local_guns) do
					local g = h.Parent
					if g and g.Parent == char then
						equippedHandle = h
						equippedData   = data
						break
					end
				end
			end
		end

		if equippedHandle and equippedData and equippedData[3] > 0 then
			lastFire = tick()
			setthreadidentity(8)
			event:FireServer("ShootGun", equippedHandle, origin, aimPos, hitPart, fDir)
			-- double-tap rifles for better server registration
			local gName = equippedHandle.Parent and equippedHandle.Parent.Name or ""
			if gName == "[Rifle]" or gName == "[Flintlock]" then
				event:FireServer("ShootGun", equippedHandle, origin,
					aimPos + Vector3.new(0.002, 0.001, 0), hitPart, fDir)
			end
			setthreadidentity(4)
		end
	end
end)

-- ── STRAFE LOOP ───────────────────────────────────────────────
-- Figure-8 pattern (harder to predict than simple circle)
-- Pauses during stomping, evasion, and buying
-- purchasing MUST pause strafe — doBuy teleports HRP to the shop,
-- and if strafe runs on the same frame it immediately overwrites that
-- position and the click detector never fires at the right spot.
rs.Heartbeat:Connect(function(dt)
	if killed or myKnocked or stomping or in_void or purchasing then return end
	if not targetPlayer then return end
	local myHrp = plr.Character and plr.Character:FindFirstChild("HumanoidRootPart")
	if not myHrp then return end
	local tChar = targetPlayer.Character
	local tHrp  = tChar and tChar:FindFirstChild("HumanoidRootPart")
	if not tHrp then return end
	strafeT     += dt
	strafeAngle += dt * 28  -- slightly faster orbit
	-- figure-8: lemniscate-style pattern using sin(2t) for one axis
	local r = 2.5
	local newPos = tHrp.Position + Vector3.new(
		math.cos(strafeAngle)           * r,
		math.abs(math.sin(strafeT * 3)) * 0.4,  -- gentle bob
		math.sin(strafeAngle * 2) * 0.7 * r
	)
	myHrp.CFrame = CFrame.new(newPos, tHrp.Position)
end)

-- ── BAIT SYSTEM ───────────────────────────────────────────────
-- Creates an invisible anchor Part that sits at your REAL position
-- while you're in evasion. During evasion the anchor stays put,
-- showing exploiters a "ghost" of where you were.
-- Based on Unnamed's desync_setback approach.
-- When NOT evading: anchor tracks your real position normally.
-- baitEnabled toggle in GUI.
local baitEnabled   = false
local baitPart      = Instance.new("Part")
baitPart.Name       = "BaitAnchor"
baitPart.Size       = Vector3.new(2, 5, 1)
baitPart.Anchored   = true
baitPart.CanCollide = false
baitPart.Transparency = 1
baitPart.CastShadow = false
baitPart.Parent     = workspace

-- Highlight on bait so it looks like a real player to exploiter ESPs
local baitHL             = Instance.new("Highlight")
baitHL.DepthMode         = Enum.HighlightDepthMode.AlwaysOnTop
baitHL.FillColor         = Color3.fromRGB(255, 255, 255)
baitHL.OutlineColor      = Color3.fromRGB(255, 255, 255)
baitHL.FillTransparency  = 0.5
baitHL.OutlineTransparency = 0
baitHL.Enabled           = false
baitHL.Adornee           = baitPart
baitHL.Parent            = baitPart

-- Bait line (Drawing) from real pos to bait pos — visible only to you
local baitLine       = Drawing.new("Line")
baitLine.Thickness   = 1
baitLine.Color       = Color3.fromRGB(200, 200, 200)
baitLine.Visible     = false
baitLine.Transparency = 0.6

local lastRealBaitCF = CFrame.new()
rs.RenderStepped:Connect(function()
	if killed then
		baitHL.Enabled = false
		baitLine.Visible = false
		return
	end
	local char = plr.Character
	local hrp  = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return end

	if not evasionBusy then
		-- not evading: anchor follows real position
		lastRealBaitCF = hrp.CFrame
	end
	-- always update anchor to last real position
	baitPart.CFrame = lastRealBaitCF

	-- show highlight + line when evading and bait is enabled
	local evading = in_void and baitEnabled
	baitHL.Enabled = evading
	if evading then
		-- draw line from real pos to bait anchor in screen space
		local cam = workspace.CurrentCamera
		local baitSc, baitVis = cam:WorldToViewportPoint(baitPart.Position)
		local realSc, realVis = cam:WorldToViewportPoint(hrp.Position)
		if baitVis and realVis then
			baitLine.From    = Vector2.new(realSc.X, realSc.Y)
			baitLine.To      = Vector2.new(baitSc.X, baitSc.Y)
			baitLine.Visible = true
		else
			baitLine.Visible = false
		end
	else
		baitLine.Visible = false
	end
end)

-- ── GUI ───────────────────────────────────────────────────────
local old = plr.PlayerGui:FindFirstChild("CombatGUI")
if old then old:Destroy() end

local sg = Instance.new("ScreenGui")
sg.Name           = "CombatGUI"
sg.ResetOnSpawn   = false
sg.IgnoreGuiInset = true
sg.Parent         = plr.PlayerGui

local function mkCorner(r, p)
	local c = Instance.new("UICorner"); c.CornerRadius = UDim.new(0,r); c.Parent = p
end

local BG    = Color3.fromRGB(10,  10,  10)
local CARD  = Color3.fromRGB(18,  18,  18)
local SEP   = Color3.fromRGB(30,  30,  30)
local DIM   = Color3.fromRGB(80,  80,  80)
local WHITE = Color3.fromRGB(235, 235, 235)
local MUTED = Color3.fromRGB(130, 130, 130)
local HI    = Color3.fromRGB(255, 255, 255)
local BLUE  = Color3.fromRGB(80,  140, 255)

-- ════════════════════════════════════════════
-- POPUP SYSTEM
-- ════════════════════════════════════════════
local popupFrame = Instance.new("Frame")
popupFrame.Size             = UDim2.new(0, 200, 0, 32)
popupFrame.Position         = UDim2.new(0.5, -100, 0, 28)
popupFrame.BackgroundColor3 = Color3.fromRGB(16, 16, 16)
popupFrame.BackgroundTransparency = 0.1
popupFrame.BorderSizePixel  = 0
popupFrame.Visible          = false
popupFrame.ZIndex           = 20
popupFrame.Parent           = sg
mkCorner(7, popupFrame)

local popupTxt = Instance.new("TextLabel")
popupTxt.Size               = UDim2.new(1, -16, 1, 0)
popupTxt.Position           = UDim2.new(0, 8, 0, 0)
popupTxt.BackgroundTransparency = 1
popupTxt.Text               = ""
popupTxt.TextColor3         = WHITE
popupTxt.Font               = Enum.Font.GothamBold
popupTxt.TextSize           = 12
popupTxt.TextXAlignment     = Enum.TextXAlignment.Center
popupTxt.ZIndex             = 21
popupTxt.Parent             = popupFrame

local popupQueue = {}
local popupShowing = false
local function showPopup(msg, col)
	table.insert(popupQueue, {msg, col or WHITE})
	if popupShowing then return end
	popupShowing = true
	task.spawn(function()
		while #popupQueue > 0 do
			local item = table.remove(popupQueue, 1)
			popupTxt.Text       = item[1]
			popupTxt.TextColor3 = item[2]
			popupFrame.Visible  = true
			task.wait(1.4)
			popupFrame.Visible  = false
			task.wait(0.1)
		end
		popupShowing = false
	end)
end

-- ════════════════════════════════════════════
-- STATUS TEXT (center screen, always visible)
-- ════════════════════════════════════════════
local statusCenter = Instance.new("TextLabel")
statusCenter.Size               = UDim2.new(0, 300, 0, 24)
statusCenter.Position           = UDim2.new(0.5, -150, 1, -60)
statusCenter.BackgroundTransparency = 1
statusCenter.Text               = ""
statusCenter.TextColor3         = Color3.fromRGB(180, 180, 180)
statusCenter.Font               = Enum.Font.Gotham
statusCenter.TextSize           = 12
statusCenter.TextXAlignment     = Enum.TextXAlignment.Center
statusCenter.ZIndex             = 10
statusCenter.Parent             = sg

-- ════════════════════════════════════════════
-- MAIN WINDOW
-- ════════════════════════════════════════════
local win = Instance.new("Frame")
win.Size             = UDim2.new(0, 224, 0, 420)
win.Position         = UDim2.new(0, 14, 0.5, -210)
win.BackgroundColor3 = BG
win.BorderSizePixel  = 0
win.Active           = true
win.Draggable        = true
win.ClipsDescendants = true
win.Parent           = sg
mkCorner(8, win)

local titleBar = Instance.new("Frame")
titleBar.Size             = UDim2.new(1, 0, 0, 42)
titleBar.BackgroundColor3 = CARD
titleBar.BorderSizePixel  = 0
titleBar.Parent           = win

local titleTxt = Instance.new("TextLabel")
titleTxt.Size               = UDim2.new(1, -14, 0, 20)
titleTxt.Position           = UDim2.new(0, 14, 0, 8)
titleTxt.BackgroundTransparency = 1
titleTxt.Text               = "combat"
titleTxt.TextColor3         = HI
titleTxt.Font               = Enum.Font.GothamBold
titleTxt.TextSize            = 14
titleTxt.TextXAlignment     = Enum.TextXAlignment.Left
titleTxt.Parent             = titleBar

local subTxt = Instance.new("TextLabel")
subTxt.Size               = UDim2.new(1, -14, 0, 12)
subTxt.Position           = UDim2.new(0, 14, 0, 26)
subTxt.BackgroundTransparency = 1
subTxt.Text               = "p to unload"
subTxt.TextColor3         = DIM
subTxt.Font               = Enum.Font.Gotham
subTxt.TextSize           = 10
subTxt.TextXAlignment     = Enum.TextXAlignment.Left
subTxt.Parent             = titleBar

-- sep under title
local function mkSep(y) local d=Instance.new("Frame");d.Size=UDim2.new(1,-24,0,1);d.Position=UDim2.new(0,12,0,y);d.BackgroundColor3=SEP;d.BorderSizePixel=0;d.Parent=win end

mkSep(42)

-- stats row
local statsFrame = Instance.new("Frame")
statsFrame.Size             = UDim2.new(1,-24,0,28)
statsFrame.Position         = UDim2.new(0,12,0,50)
statsFrame.BackgroundTransparency = 1
statsFrame.Parent           = win

local armorLbl = Instance.new("TextLabel")
armorLbl.Size=UDim2.new(0.5,0,1,0); armorLbl.BackgroundTransparency=1
armorLbl.Text="armor  0"; armorLbl.TextColor3=MUTED; armorLbl.Font=Enum.Font.Gotham
armorLbl.TextSize=11; armorLbl.TextXAlignment=Enum.TextXAlignment.Left; armorLbl.Parent=statsFrame

local cashLbl = Instance.new("TextLabel")
cashLbl.Size=UDim2.new(0.5,0,1,0); cashLbl.Position=UDim2.new(0.5,0,0,0); cashLbl.BackgroundTransparency=1
cashLbl.Text="cash  0"; cashLbl.TextColor3=MUTED; cashLbl.Font=Enum.Font.Gotham
cashLbl.TextSize=11; cashLbl.TextXAlignment=Enum.TextXAlignment.Right; cashLbl.Parent=statsFrame

mkSep(84)

-- target row
local targetLbl = Instance.new("TextLabel")
targetLbl.Size=UDim2.new(1,-24,0,30); targetLbl.Position=UDim2.new(0,12,0,90)
targetLbl.BackgroundTransparency=1; targetLbl.Text="no target"
targetLbl.TextColor3=DIM; targetLbl.Font=Enum.Font.GothamBold
targetLbl.TextSize=12; targetLbl.TextXAlignment=Enum.TextXAlignment.Left; targetLbl.Parent=win

local stateLbl = Instance.new("TextLabel")
stateLbl.Size=UDim2.new(0,80,0,30); stateLbl.Position=UDim2.new(1,-92,0,90)
stateLbl.BackgroundTransparency=1; stateLbl.Text=""
stateLbl.TextColor3=DIM; stateLbl.Font=Enum.Font.Gotham
stateLbl.TextSize=10; stateLbl.TextXAlignment=Enum.TextXAlignment.Right; stateLbl.Parent=win

mkSep(126)

-- toggles
local function mkToggle(xOff, w, yPos, label, startOn, cb)
	local btn = Instance.new("TextButton")
	btn.Size=UDim2.new(0,w,0,24); btn.Position=UDim2.new(0,xOff,0,yPos)
	btn.BackgroundColor3=startOn and CARD or BG; btn.BorderSizePixel=0
	btn.AutoButtonColor=false; btn.Text=label
	btn.TextColor3=startOn and WHITE or DIM; btn.Font=Enum.Font.Gotham
	btn.TextSize=11; btn.Parent=win
	mkCorner(5, btn)
	local on=startOn
	btn.MouseButton1Click:Connect(function()
		on=not on
		btn.BackgroundColor3=on and CARD or BG
		btn.TextColor3=on and WHITE or DIM
		cb(on)
	end)
	return btn
end

local TW = 94
mkToggle(12,     TW, 134, "stomp", true, function(v) autoStompEnabled=v; if not v then stomping=false end end)
mkToggle(12+TW+8,TW, 134, "void hide", true, function(v) voidHideEnabled=v; if not v then in_void=false end end)

mkSep(164)

-- refresh
local refreshBtn = Instance.new("TextButton")
refreshBtn.Size=UDim2.new(1,-24,0,24); refreshBtn.Position=UDim2.new(0,12,0,172)
refreshBtn.BackgroundColor3=BG; refreshBtn.BorderSizePixel=0; refreshBtn.AutoButtonColor=false
refreshBtn.Text="refresh players"; refreshBtn.TextColor3=DIM; refreshBtn.Font=Enum.Font.Gotham
refreshBtn.TextSize=11; refreshBtn.Parent=win
mkCorner(5, refreshBtn)
refreshBtn.MouseEnter:Connect(function() refreshBtn.TextColor3=WHITE end)
refreshBtn.MouseLeave:Connect(function() refreshBtn.TextColor3=DIM   end)

mkSep(202)

-- player list
local scroll = Instance.new("ScrollingFrame")
scroll.Size=UDim2.new(1,-24,0,164); scroll.Position=UDim2.new(0,12,0,210)
scroll.BackgroundTransparency=1; scroll.BorderSizePixel=0
scroll.ScrollBarThickness=2; scroll.ScrollBarImageColor3=SEP
scroll.CanvasSize=UDim2.new(0,0,0,0); scroll.Parent=win

local ll = Instance.new("UIListLayout"); ll.SortOrder=Enum.SortOrder.Name; ll.Padding=UDim.new(0,2); ll.Parent=scroll

mkSep(380)

-- deselect
local stopBtn = Instance.new("TextButton")
stopBtn.Size=UDim2.new(1,-24,0,24); stopBtn.Position=UDim2.new(0,12,0,386)
stopBtn.BackgroundColor3=BG; stopBtn.BorderSizePixel=0; stopBtn.AutoButtonColor=false
stopBtn.Text="deselect"; stopBtn.TextColor3=DIM; stopBtn.Font=Enum.Font.Gotham
stopBtn.TextSize=11; stopBtn.Parent=win
mkCorner(5, stopBtn)
stopBtn.MouseEnter:Connect(function() stopBtn.TextColor3=WHITE end)
stopBtn.MouseLeave:Connect(function() stopBtn.TextColor3=DIM   end)

-- ════════════════════════════════════════════
-- ESP + SNAP LINES (Drawing API)
-- ════════════════════════════════════════════
-- Box + health bar + name (Monospace bold font) + snap line
-- Hit detection: tracks target armor each frame, plays sound on drop
-- H key = lock onto closest snap line to crosshair
local cam = workspace.CurrentCamera
local vp  = cam.ViewportSize

local espData = {}

local function mkLine(col, thick)
	local l = Drawing.new("Line")
	l.Color = col; l.Thickness = thick or 1
	l.Transparency = 1; l.Visible = false
	return l
end
local function mkRect(col, thick, filled)
	local r = Drawing.new("Square")
	r.Color = col; r.Thickness = thick or 1
	r.Filled = filled or false
	r.Transparency = 1; r.Visible = false
	return r
end
local function mkText(col, size, font)
	local t = Drawing.new("Text")
	t.Color = col; t.Size = size or 16
	t.Font  = Drawing.Fonts.UI   -- smooth, anti-aliased
	t.Outline = true
	t.OutlineColor = Color3.fromRGB(0, 0, 0)
	t.Visible = false
	return t
end

-- ── HIT SOUND ─────────────────────────────────────────────────
-- Plays a short sound when the target takes damage (armor drops)
-- Uses a Sound instance parented to the local HRP (inaudible to others)
local hitSoundId = "rbxassetid://6534947588"  -- bubble pop (clean, classic)
local lastHitArmor = {}  -- [player] = last known armor value

local function playHitSound()
	local char = plr.Character
	local hrp  = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return end
	local s = Instance.new("Sound")
	s.SoundId = hitSoundId
	s.Volume  = 1
	s.RollOffMaxDistance = 0  -- silent to others
	s.Parent  = hrp
	s:Play()
	game:GetService("Debris"):AddItem(s, 1)
end

-- ── HIT MARKER (Drawing) ──────────────────────────────────────
-- A brief white cross at the centre of screen on hit
local hitMarkerAlpha = 0
local hmLines = {}
for i = 1, 4 do
	local l = Drawing.new("Line")
	l.Thickness = 1.5
	l.Color = Color3.fromRGB(255, 255, 255)
	l.Transparency = 0
	l.Visible = false
	hmLines[i] = l
end

local function showHitMarker()
	hitMarkerAlpha = 1
end

rs.RenderStepped:Connect(function()
	if hitMarkerAlpha <= 0 then
		for _, l in ipairs(hmLines) do l.Visible = false end
		return
	end
	local cx = vp.X / 2
	local cy = vp.Y / 2
	local gap = 4
	local len = 7
	local alpha = hitMarkerAlpha
	-- top, bottom, left, right arms
	local arms = {
		{Vector2.new(cx, cy-gap), Vector2.new(cx, cy-gap-len)},
		{Vector2.new(cx, cy+gap), Vector2.new(cx, cy+gap+len)},
		{Vector2.new(cx-gap, cy), Vector2.new(cx-gap-len, cy)},
		{Vector2.new(cx+gap, cy), Vector2.new(cx+gap+len, cy)},
	}
	for i, arm in ipairs(arms) do
		hmLines[i].From  = arm[1]
		hmLines[i].To    = arm[2]
		hmLines[i].Color = Color3.fromRGB(255, 255, 255)
		hmLines[i].Transparency = 1 - alpha
		hmLines[i].Visible = true
	end
	hitMarkerAlpha = math.max(0, hitMarkerAlpha - 0.08)  -- fade out
end)

local function initESP(p)
	if p == plr or espData[p] then return end
	espData[p] = {
		line   = mkLine(Color3.fromRGB(180,180,180), 1),
		box    = mkRect(Color3.fromRGB(180,180,180), 1),
		hpBg   = mkRect(Color3.fromRGB(20,20,20),   3, true),
		hpFill = mkRect(Color3.fromRGB(80,140,255),  3, true),
		name   = mkText(Color3.fromRGB(255,255,255), 16, Drawing.Fonts.UI),
		dist   = mkText(Color3.fromRGB(160,160,160), 13, Drawing.Fonts.UI),
		scrPos = Vector2.new(),
	}
end

local function clearESP(p)
	local d = espData[p]; if not d then return end
	for _, v in pairs(d) do pcall(function() if type(v) == "userdata" then v:Remove() end end) end
	espData[p] = nil
end

for _, p in ipairs(game.Players:GetPlayers()) do initESP(p) end
game.Players.PlayerAdded:Connect(initESP)
game.Players.PlayerRemoving:Connect(function(p) clearESP(p) end)

-- ESP render loop
rs.RenderStepped:Connect(function()
	if killed then
		for p in pairs(espData) do clearESP(p) end
		return
	end

	vp = cam.ViewportSize
	local botCenter = Vector2.new(vp.X / 2, vp.Y)
	local myChar = plr.Character
	local myHrp  = myChar and myChar:FindFirstChild("HumanoidRootPart")

	for p, d in pairs(espData) do
		local char = p.Character
		local hrp  = char and char:FindFirstChild("HumanoidRootPart")
		local head = char and char:FindFirstChild("Head")
		local hum  = char and char:FindFirstChildOfClass("Humanoid")

		if not hrp or not head then
			d.line.Visible=false; d.box.Visible=false
			d.hpBg.Visible=false; d.hpFill.Visible=false
			d.name.Visible=false; d.dist.Visible=false
			continue
		end

		-- hit detection: track armor drop on the target player
		local be    = char:FindFirstChild("BodyEffects")
		local armor = be and be:FindFirstChild("Armor")
		if armor then
			local curArmor = armor.Value
			local prev     = lastHitArmor[p]
			if prev ~= nil and curArmor < prev then
				-- took damage
				playHitSound()
				showHitMarker()
			end
			lastHitArmor[p] = curArmor
		end

		local headPos3, headVis = cam:WorldToViewportPoint(head.Position + Vector3.new(0, 0.5, 0))
		local feetPos3, feetVis = cam:WorldToViewportPoint(hrp.Position  - Vector3.new(0, 3, 0))
		if not headVis and not feetVis then
			d.line.Visible=false; d.box.Visible=false
			d.hpBg.Visible=false; d.hpFill.Visible=false
			d.name.Visible=false; d.dist.Visible=false
			continue
		end

		local headSc = Vector2.new(headPos3.X, headPos3.Y)
		local feetSc = Vector2.new(feetPos3.X, feetPos3.Y)
		d.scrPos = headSc

		local height = math.max(math.abs(feetSc.Y - headSc.Y), 10)
		local width  = height * 0.45
		local cx     = headSc.X
		local top    = headSc.Y
		local bot    = feetSc.Y
		local left   = cx - width / 2
		local isSel  = (targetPlayer == p)

		local boxCol  = isSel and Color3.fromRGB(255,255,255) or Color3.fromRGB(150,150,150)
		local lineCol = isSel and Color3.fromRGB(255,255,255) or Color3.fromRGB(90,90,90)

		-- snap line
		d.line.From=botCenter; d.line.To=feetSc
		d.line.Color=lineCol; d.line.Thickness=isSel and 1.5 or 1
		d.line.Visible=true

		-- box
		d.box.Position=Vector2.new(left,top); d.box.Size=Vector2.new(width,height)
		d.box.Color=boxCol; d.box.Thickness=isSel and 1.5 or 1
		d.box.Visible=true

		-- health bar
		local hp   = hum and math.clamp(hum.Health / math.max(hum.MaxHealth, 1), 0, 1) or 1
		local barH = height * hp
		d.hpBg.Position=Vector2.new(left-5, top); d.hpBg.Size=Vector2.new(3,height); d.hpBg.Visible=true
		d.hpFill.Position=Vector2.new(left-5, bot-barH); d.hpFill.Size=Vector2.new(3,barH)
		d.hpFill.Color = hp>0.6 and Color3.fromRGB(80,140,255)
		              or hp>0.3 and Color3.fromRGB(130,170,255)
		              or Color3.fromRGB(170,170,200)
		d.hpFill.Visible=true

		-- name — fixed 16px UI font, centered above box, always readable
		d.name.Text     = p.Name
		d.name.Size     = 16
		d.name.Position = Vector2.new(cx, top - 18)
		d.name.Center   = true   -- center horizontally on position
		d.name.Color    = isSel and Color3.fromRGB(255,255,255) or Color3.fromRGB(200,200,200)
		d.name.Visible  = true

		-- distance label below feet
		if myHrp then
			local dist = math.floor((hrp.Position - myHrp.Position).Magnitude)
			d.dist.Text     = dist .. "m"
			d.dist.Size     = 13
			d.dist.Position = Vector2.new(cx, bot + 3)
			d.dist.Center   = true
			d.dist.Color    = Color3.fromRGB(130,130,130)
			d.dist.Visible  = true
		else
			d.dist.Visible = false
		end
	end
end)

-- ════════════════════════════════════════════
-- ════════════════════════════════════════════
-- CAMERA LOCK — prevents camera jerking during evasion/buy teleports
-- Locks CameraSubject to a fixed invisible anchor during teleports
-- so the view never snaps to the fake position
-- ════════════════════════════════════════════
do
	local cam = workspace.CurrentCamera

	-- invisible anchor part that stays at real position
	local camAnchor = Instance.new("Part")
	camAnchor.Name        = "_CamAnchor"
	camAnchor.Anchored    = true
	camAnchor.CanCollide  = false
	camAnchor.Transparency = 1
	camAnchor.Size        = Vector3.new(0.1, 0.1, 0.1)
	camAnchor.Parent      = workspace

	local function attachCamAnchor(char)
		local hrp = char and char:FindFirstChild("HumanoidRootPart")
		if not hrp then return end
		-- keep anchor welded to real hrp position via Heartbeat
		rs.Heartbeat:Connect(function()
			if not in_void and not purchasing then
				camAnchor.CFrame = hrp.CFrame
			end
		end)
	end

	if plr.Character then attachCamAnchor(plr.Character) end
	plr.CharacterAdded:Connect(function(c)
		task.wait(0.5)
		attachCamAnchor(c)
	end)

	-- switch CameraSubject during teleports
	rs.RenderStepped:Connect(function()
		if killed then return end
		if in_void or purchasing then
			-- lock camera to anchor — view stays put
			if cam.CameraSubject ~= camAnchor then
				cam.CameraSubject = camAnchor
			end
		else
			-- restore to humanoid when not teleporting
			local char = plr.Character
			local hum  = char and char:FindFirstChildOfClass("Humanoid")
			if hum and cam.CameraSubject ~= hum then
				cam.CameraSubject = hum
			end
		end
	end)
end

-- ════════════════════════════════════════════
-- EVENT NOTIFICATIONS — fires popups for key events, no always-on status text
-- ════════════════════════════════════════════
local lastStompNotif   = 0
local lastBuyNotif     = 0
local lastReloadNotif  = 0
local lastHideNotif    = 0
local lastKillNotif    = 0
local prevPurchasing   = false
local prevReloading    = false
local prevInVoid       = false
local prevStomping     = false
local prevTargetKnocked = false

task.spawn(function()
	while not killed do
		task.wait(0.1)
		local now = tick()

		-- stomp started
		if stomping and not prevStomping then
			if now - lastStompNotif > 2 then
				showPopup("stomping", Color3.fromRGB(200, 200, 200))
				lastStompNotif = now
			end
		end
		prevStomping = stomping

		-- buy started
		if purchasing and not prevPurchasing then
			if now - lastBuyNotif > 1 then
				showPopup("buying", Color3.fromRGB(160, 160, 160))
				lastBuyNotif = now
			end
		end
		-- buy finished
		if not purchasing and prevPurchasing then
			showPopup("bought", Color3.fromRGB(160, 160, 160))
		end
		prevPurchasing = purchasing

		-- reload started
		if local_reloading and not prevReloading then
			if now - lastReloadNotif > 1 then
				showPopup("reloading", Color3.fromRGB(140, 140, 140))
				lastReloadNotif = now
			end
		end
		prevReloading = local_reloading

		-- hiding (evasion) started
		if in_void and not prevInVoid then
			if now - lastHideNotif > 2 then
				showPopup("hiding", Color3.fromRGB(130, 130, 130))
				lastHideNotif = now
			end
		end
		prevInVoid = in_void

		-- target knocked (killed)
		if targetPlayer then
			local tChar = targetPlayer.Character
			local knocked = tChar and isKnockedChar(tChar)
			if knocked and not prevTargetKnocked then
				if now - lastKillNotif > 2 then
					showPopup("knocked  " .. targetPlayer.Name, WHITE)
					lastKillNotif = now
				end
			end
			prevTargetKnocked = knocked or false
		else
			prevTargetKnocked = false
		end
	end
end)

-- LIVE UPDATE LOOP — only updates stats in the panel, no state text
-- ════════════════════════════════════════════
task.spawn(function()
	while not killed do
		task.wait(0.15)
		armorLbl.Text = "armor  " .. local_armor
		cashLbl.Text  = "cash  " .. local_cash

		if targetPlayer then
			targetLbl.Text       = targetPlayer.Name
			targetLbl.TextColor3 = WHITE
		else
			targetLbl.Text       = "no target"
			targetLbl.TextColor3 = DIM
		end

		-- state label — subtle, right-aligned in panel (not center screen)
		local state = ""
		if myKnocked           then state = "downed"
		elseif stomping        then state = "stomp"
		elseif in_void         then state = "hide"
		elseif purchasing      then state = "buy"
		elseif local_reloading then state = "reload"
		elseif targetPlayer    then state = "active"
		end
		stateLbl.Text = state

		-- center status: only target HP and protection status (no internal states)
		local lines = {}
		if targetPlayer then
			local tChar = targetPlayer.Character
			if tChar then
				local hum = tChar:FindFirstChildOfClass("Humanoid")
				if hum and hum.Health > 0 then
					table.insert(lines, string.format("hp  %.0f", hum.Health))
				end
				if hasSpawnProtection(tChar) then table.insert(lines, "protected") end
				if isGrabbed(tChar)          then table.insert(lines, "grabbed")   end
			end
		end
		statusCenter.Text = table.concat(lines, "  ·  ")
	end
end)

-- ════════════════════════════════════════════
-- INPUT
-- ════════════════════════════════════════════
uis.InputBegan:Connect(function(input, gp)
	if gp then return end
	if input.KeyCode == Enum.KeyCode.P then
		killed = true; targetPlayer = nil; stomping = false; in_void = false
		for p in pairs(espData) do clearESP(p) end
		local g = plr.PlayerGui:FindFirstChild("CombatGUI"); if g then g:Destroy() end
		print("[combat] killed")
	end
end)

-- PLAYER LIST BUILDER
-- ════════════════════════════════════════════
local function buildList()
	for _, v in ipairs(scroll:GetChildren()) do if v:IsA("TextButton") then v:Destroy() end end
	local list = {}
	for _, p in ipairs(game.Players:GetPlayers()) do if p ~= plr then table.insert(list, p) end end
	for _, p in ipairs(list) do
		local sel = targetPlayer == p
		local row = Instance.new("TextButton")
		row.Size=UDim2.new(1,0,0,26); row.BackgroundColor3=sel and CARD or BG
		row.BorderSizePixel=0; row.AutoButtonColor=false; row.Text=""; row.Name=p.Name; row.Parent=scroll
		mkCorner(4, row)
		local nameTxt = Instance.new("TextLabel")
		nameTxt.Size=UDim2.new(1,-12,1,0); nameTxt.Position=UDim2.new(0,10,0,0)
		nameTxt.BackgroundTransparency=1; nameTxt.Text=p.Name
		nameTxt.TextColor3=sel and WHITE or MUTED
		nameTxt.Font=sel and Enum.Font.GothamBold or Enum.Font.Gotham
		nameTxt.TextSize=11; nameTxt.TextXAlignment=Enum.TextXAlignment.Left; nameTxt.Parent=row
		row.MouseEnter:Connect(function() if targetPlayer~=p then row.BackgroundColor3=CARD; nameTxt.TextColor3=WHITE end end)
		row.MouseLeave:Connect(function() if targetPlayer~=p then row.BackgroundColor3=BG;   nameTxt.TextColor3=MUTED end end)
		row.MouseButton1Click:Connect(function()
			if killed then return end
			if targetPlayer == p then
				targetPlayer=nil; stomping=false; in_void=false
				showPopup("cleared", Color3.fromRGB(130,130,130))
			else
				targetPlayer=p; task.spawn(doLoadout)
				showPopup(p.Name, WHITE)
			end
			buildList()
		end)
	end
	scroll.CanvasSize = UDim2.new(0,0,0,#list*28)
end

refreshBtn.MouseButton1Click:Connect(function() buildShops(); buildList() end)
stopBtn.MouseButton1Click:Connect(function()
	targetPlayer=nil; stomping=false; in_void=false
	showPopup("cleared", Color3.fromRGB(130,130,130))
	buildList()
end)
game.Players.PlayerAdded:Connect(function(p)
	if not killed then initESP(p); buildList() end
end)
game.Players.PlayerRemoving:Connect(function(p)
	if targetPlayer==p then targetPlayer=nil; stomping=false; in_void=false end
	clearESP(p)
	if not killed then buildList() end
end)

-- H = lock onto player whose snap line is closest to crosshair
uis.InputBegan:Connect(function(input, gp)
	if gp or input.KeyCode ~= Enum.KeyCode.H then return end
	if killed then return end
	local center   = Vector2.new(vp.X / 2, vp.Y / 2)
	local best, bestDist = nil, math.huge
	for p, d in pairs(espData) do
		if not p.Character then continue end
		local sp = d.scrPos
		if sp == Vector2.new() then continue end
		local dist = (sp - center).Magnitude
		if dist < bestDist then bestDist = dist; best = p end
	end
	if best then
		if targetPlayer == best then
			targetPlayer=nil; stomping=false; in_void=false
			showPopup("cleared", Color3.fromRGB(130,130,130))
		else
			targetPlayer=best; task.spawn(doLoadout)
			showPopup(best.Name, WHITE)
		end
		buildList()
	end
end)

buildList()
task.spawn(doLoadout)

-- ── AUTO-TARGET ───────────────────────────────────────────────
-- Two sources for the target, checked in order:
--   1. getgenv()._auto_target_id  — set by agent.lua before loadstring
--   2. GET /api/assignment        — queried directly (works standalone too)
-- If neither resolves, falls back to the player-list GUI (manual click).
task.spawn(function()
	-- Source 1: passed in by agent.lua
	local autoId   = tostring(getgenv()._auto_target_id   or "")
	local autoName = tostring(getgenv()._auto_target_name or "")

	-- Source 2: query the server directly
	if autoId == "" then
		local ok, res = pcall(function()
			return req({ Url = SERVER .. "/api/assignment?accountId=" .. SCOUT_ID, Method = "GET" })
		end)
		if ok and res and res.Body then
			local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
			if ok2 and d and d.assigned == true then
				autoId   = tostring(d.targetUserId   or "")
				autoName = tostring(d.targetUsername  or "")
				print("[combat] assignment from server: " .. autoName .. " (" .. autoId .. ")")
			end
		end
	end

	-- No assignment found — stay in manual GUI mode
	if autoId == "" then
		print("[combat] no assignment — manual target selection active")
		return
	end

	-- Wait up to 15s for the target player to replicate into the server
	local found  = nil
	local waited = 0
	repeat
		task.wait(0.5); waited += 0.5
		for _, p in ipairs(game.Players:GetPlayers()) do
			if tostring(p.UserId) == autoId then found = p; break end
		end
	until found or waited >= 15

	if not found then
		print("[combat] auto-target " .. autoId .. " not found after 15s — manual mode")
		return
	end

	-- Lock on and go
	targetPlayer = found
	task.spawn(doLoadout)
	buildList()
	showPopup(found.Name, WHITE)
	print("[combat] auto-targeting " .. found.Name)

	-- Tell server combat is confirmed active
	pcall(function()
		req({
			Url     = SERVER .. "/api/assignment/complete",
			Method  = "POST",
			Headers = { ["Content-Type"] = "application/json" },
			Body    = hs:JSONEncode({ accountId = SCOUT_ID }),
		})
	end)

	-- Notify server when target leaves
	game.Players.PlayerRemoving:Connect(function(p)
		if p == targetPlayer then
			targetPlayer = nil
			pcall(function()
				req({
					Url     = SERVER .. "/api/target_lost",
					Method  = "POST",
					Headers = { ["Content-Type"] = "application/json" },
					Body    = hs:JSONEncode({ accountId = SCOUT_ID, userId = autoId }),
				})
			end)
			showPopup("target left", Color3.fromRGB(180, 180, 180))
			print("[combat] target left server")
		end
	end)
end)

-- ── SERVER POSITION INDICATOR ────────────────────────────────
do
	local dot = Instance.new("Part")
	dot.Name         = "_SrvPos"
	dot.Size         = Vector3.new(0.4, 0.4, 0.4)
	dot.Shape        = Enum.PartType.Ball
	dot.Material     = Enum.Material.Neon
	dot.Color        = Color3.fromRGB(200, 200, 200)
	dot.Transparency = 0.2
	dot.CanCollide   = false
	dot.Anchored     = true
	dot.CastShadow   = false
	dot.Parent       = workspace
	local lastRealCF = CFrame.new()
	rs.RenderStepped:Connect(function()
		if killed then pcall(function() dot:Destroy() end); return end
		local char = plr.Character
		local hrp  = char and char:FindFirstChild("HumanoidRootPart")
		if hrp and not evasionBusy then lastRealCF = hrp.CFrame end
		dot.CFrame = lastRealCF
		dot.Color  = (in_void or purchasing or local_reloading)
			and Color3.fromRGB(255, 150, 40)
			or  Color3.fromRGB(200, 200, 200)
	end)
end

-- ── AUTO REDEEM CODES ─────────────────────────────────────────
-- Fires RedeemCode for every known Da Hood promo code on startup.
-- Silently skips already-redeemed codes (server ignores dupes).
-- Add new codes to the list as they drop.
task.spawn(function()
	local me = game:GetService("ReplicatedStorage"):FindFirstChild("MainEvent")
	if not me then return end

	-- known Da Hood promo codes (add new ones here)
	local CODES = {
		"WORLDCUP26",
		"BOSS",
		"BALLON",
		"FREECASH",
		"DAHOOD",
		"DABLOX",
		"MONEY",
		"CASH",
		"DAHOODRESET",
		"RESET",
		"UPDATE",
		"THANKYOU",
		"HOOD",
		"DABUX",
		"FREE",
		"500KLIKES",
		"1MILLIKES",
		"1MILLFAV",
		"2MILLFAV",
		"3MILLFAV",
		"5MILLFAV",
		"10MILLFAV",
		"15MILLFAV",
		"20MILLFAV",
		"25MILLFAV",
		"30MILLFAV",
		"50KLIKES",
		"100KLIKES",
		"200KLIKES",
		"HAPPYNEWYEAR",
		"HAPPYNEWYEAR2023",
		"HAPPYNEWYEAR2024",
		"HAPPYNEWYEAR2025",
		"HALLOWEEN",
		"CHRISTMAS",
		"XMAS",
		"EASTER",
		"THANKSGIVING",
		"BLACKFRIDAY",
		"SUMMERFUN",
		"WINTER",
		"SPRING",
		"NEWMAP",
		"NEWUPDATE",
		"NEWYEAR",
		"GROUPUPDATE",
		"DISCORD",
		"TWITTER",
		"YOUTUBE",
		"TIKTOK",
		"ROBLOX",
	}

	-- wait for the game to be fully loaded before redeeming
	if not game:IsLoaded() then game.Loaded:Wait() end
	task.wait(3)  -- give the game a moment to initialise shops etc

	local redeemed = 0
	for _, code in ipairs(CODES) do
		pcall(function()
			setthreadidentity(8)
			me:FireServer("RedeemCode", code)
			setthreadidentity(4)
		end)
		task.wait(0.2)  -- small gap so server doesn't rate-limit
		redeemed += 1
	end
	print(string.format("[codes] tried %d codes", redeemed))
end)

print("[combat] ready")

