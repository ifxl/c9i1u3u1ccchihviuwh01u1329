local ts  = game:GetService("TeleportService")
local hs  = game:GetService("HttpService")
local rs  = game:GetService("RunService")
local req = (syn and syn.request) or request

local SERVER   = "https://sniper-zlqd.onrender.com"
local PLACE_ID = game.PlaceId

-- Wait for LocalPlayer
local Players = game:GetService("Players")
local lp
repeat lp = Players.LocalPlayer task.wait() until lp
local SCOUT_ID = tostring(lp.UserId)
local USERNAME = lp.Name
local VPS_ID   = "vps-default"

local targets  = {}
local running  = false
local found    = false
local stopped  = false
local hops     = getgenv()._scoutHops or 0
getgenv()._scoutHops = hops
local status   = "connecting"

-- ── gui ───────────────────────────────────────────────────────
local gui = Instance.new("ScreenGui")
gui.Name = "scout"
gui.ResetOnSpawn = false
gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
gui.Parent = game.CoreGui

local win = Instance.new("Frame")
win.Size = UDim2.new(0, 190, 0, 118)
win.Position = UDim2.new(1, -206, 1, -134)
win.BackgroundColor3 = Color3.fromRGB(6, 6, 6)
win.BorderSizePixel = 0
win.Active = true
win.Draggable = true
win.Parent = gui
Instance.new("UICorner", win).CornerRadius = UDim.new(0, 8)

local ws = Instance.new("UIStroke")
ws.Color = Color3.fromRGB(22, 22, 22)
ws.Thickness = 1
ws.Parent = win

local hdr = Instance.new("Frame")
hdr.Size = UDim2.new(1, 0, 0, 34)
hdr.BackgroundColor3 = Color3.fromRGB(11, 11, 11)
hdr.BorderSizePixel = 0
hdr.Parent = win
Instance.new("UICorner", hdr).CornerRadius = UDim.new(0, 8)

local hfix = Instance.new("Frame")
hfix.Size = UDim2.new(1, 0, 0, 8)
hfix.Position = UDim2.new(0, 0, 1, -8)
hfix.BackgroundColor3 = Color3.fromRGB(11, 11, 11)
hfix.BorderSizePixel = 0
hfix.Parent = hdr

local dot = Instance.new("Frame")
dot.Size = UDim2.new(0, 5, 0, 5)
dot.Position = UDim2.new(0, 13, 0.5, -2)
dot.BackgroundColor3 = Color3.fromRGB(50, 50, 50)
dot.BorderSizePixel = 0
dot.Parent = hdr
Instance.new("UICorner", dot).CornerRadius = UDim.new(1, 0)

local nameLbl = Instance.new("TextLabel")
nameLbl.Size = UDim2.new(0, 80, 1, 0)
nameLbl.Position = UDim2.new(0, 25, 0, 0)
nameLbl.BackgroundTransparency = 1
nameLbl.Text = "scout"
nameLbl.TextColor3 = Color3.fromRGB(240, 240, 240)
nameLbl.Font = Enum.Font.GothamBold
nameLbl.TextSize = 11
nameLbl.TextXAlignment = Enum.TextXAlignment.Left
nameLbl.Parent = hdr

local idLbl = Instance.new("TextLabel")
idLbl.Size = UDim2.new(0, 60, 1, 0)
idLbl.Position = UDim2.new(1, -66, 0, 0)
idLbl.BackgroundTransparency = 1
idLbl.Text = "#" .. SCOUT_ID
idLbl.TextColor3 = Color3.fromRGB(40, 40, 40)
idLbl.Font = Enum.Font.Gotham
idLbl.TextSize = 9
idLbl.TextXAlignment = Enum.TextXAlignment.Right
idLbl.Parent = hdr

local function makeRow(yPos, key, defaultVal)
	local row = Instance.new("Frame")
	row.Size = UDim2.new(1, -24, 0, 14)
	row.Position = UDim2.new(0, 12, 0, yPos)
	row.BackgroundTransparency = 1
	row.Parent = win

	local k = Instance.new("TextLabel")
	k.Size = UDim2.new(0, 70, 1, 0)
	k.BackgroundTransparency = 1
	k.Text = key
	k.TextColor3 = Color3.fromRGB(45, 45, 45)
	k.Font = Enum.Font.Gotham
	k.TextSize = 10
	k.TextXAlignment = Enum.TextXAlignment.Left
	k.Parent = row

	local v = Instance.new("TextLabel")
	v.Size = UDim2.new(1, -74, 1, 0)
	v.Position = UDim2.new(0, 74, 0, 0)
	v.BackgroundTransparency = 1
	v.Text = defaultVal
	v.TextColor3 = Color3.fromRGB(180, 180, 180)
	v.Font = Enum.Font.Gotham
	v.TextSize = 10
	v.TextXAlignment = Enum.TextXAlignment.Right
	v.TextTruncate = Enum.TextTruncate.AtEnd
	v.Parent = row
	return v
end

local statusVal = makeRow(42, "status", "connecting")
local hopsVal   = makeRow(60, "hopped", "0")
local serverVal = makeRow(78, "server", "—")

local stopBtn = Instance.new("TextButton")
stopBtn.Size = UDim2.new(1, -24, 0, 20)
stopBtn.Position = UDim2.new(0, 12, 1, -26)
stopBtn.BackgroundColor3 = Color3.fromRGB(16, 16, 16)
stopBtn.TextColor3 = Color3.fromRGB(100, 100, 100)
stopBtn.Font = Enum.Font.GothamBold
stopBtn.TextSize = 10
stopBtn.Text = "stop"
stopBtn.BorderSizePixel = 0
stopBtn.Parent = win
Instance.new("UICorner", stopBtn).CornerRadius = UDim.new(0, 5)

local sbs = Instance.new("UIStroke")
sbs.Color = Color3.fromRGB(22, 22, 22)
sbs.Thickness = 1
sbs.Parent = stopBtn

stopBtn.MouseButton1Click:Connect(function()
	stopped = true
	running = false
	status  = "stopped"
	stopBtn.Text = "stopped"
	stopBtn.TextColor3 = Color3.fromRGB(40, 40, 40)
end)

local t = 0
rs.RenderStepped:Connect(function(dt)
	t += dt
	if status == "searching" then
		local v = math.sin(t * 3) * 0.5 + 0.5
		dot.BackgroundColor3 = Color3.new(v, v, v)
	elseif status:find("found") then
		dot.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
	elseif status == "stopped" then
		dot.BackgroundColor3 = Color3.fromRGB(22, 22, 22)
	else
		dot.BackgroundColor3 = Color3.fromRGB(50, 50, 50)
	end
	statusVal.Text = status
	hopsVal.Text   = tostring(hops)
	local jid = game.JobId
	serverVal.Text = jid ~= "" and (jid:sub(1, 16) .. "…") or "—"
end)

-- ── api ───────────────────────────────────────────────────────
local function post(path, data)
	pcall(function()
		req({
			Url = SERVER .. path,
			Method = "POST",
			Headers = {["Content-Type"] = "application/json"},
			Body = hs:JSONEncode(data)
		})
	end)
end

local function get(path)
	local ok, res = pcall(function()
		return req({ Url = SERVER .. path, Method = "GET" })
	end)
	if ok and res and res.Body then
		local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
		if ok2 then return d end
	end
	return nil
end

-- ── role detection ────────────────────────────────────────────
-- Check if this account has a pending assignment (auto role = join & fight)
local assignment = get("/api/assignment?accountId=" .. SCOUT_ID)
local IS_AUTO = assignment and assignment.assigned == true
local AUTO_TARGET_ID = IS_AUTO and tostring(assignment.targetUserId or "") or nil
local AUTO_TARGET_NAME = IS_AUTO and tostring(assignment.targetUsername or "") or nil

if IS_AUTO then
	-- Update GUI to show auto mode
	status = "autoing"
	print("[mode] AUTO — target: " .. (AUTO_TARGET_NAME or AUTO_TARGET_ID or "?"))

	-- Tell server we've started
	post("/api/assignment/complete", { accountId = SCOUT_ID })

	-- ── COMBAT MODE ───────────────────────────────────────────
	-- Wait for character to fully load
	local char = lp.Character or lp.CharacterAdded:Wait()
	local rep = game:GetService("ReplicatedStorage")
	local event = rep:WaitForChild("MainEvent", 15)
	if not event then
		print("[auto] no MainEvent, aborting combat mode")
	else
		-- find target player object
		local function findTarget()
			for _, p in ipairs(game.Players:GetPlayers()) do
				if tostring(p.UserId) == AUTO_TARGET_ID then
					return p
				end
			end
			return nil
		end

		local targetPlayer = findTarget()

		-- wait up to 30s for target to show up
		if not targetPlayer then
			local waited = 0
			repeat task.wait(1); waited += 1
				targetPlayer = findTarget()
			until targetPlayer or waited >= 30
		end

		if not targetPlayer then
			print("[auto] target not found in server after 30s")
		else
			print("[auto] target found: " .. targetPlayer.Name .. " — loading combat")
			-- Load combat.lua via loadstring from the server
			-- This keeps the script size manageable and lets you update combat separately
			local ok, err = pcall(function()
				local combatSrc = game:HttpGet(SERVER .. "/api/combat_script")
				if combatSrc and #combatSrc > 100 then
					getgenv()._auto_target_id   = AUTO_TARGET_ID
					getgenv()._auto_target_name = AUTO_TARGET_NAME
					loadstring(combatSrc)()
				else
					print("[auto] combat script not available from server, using inline")
					-- Fallback: set target globally so combat.lua can pick it up if run separately
					getgenv()._auto_target_id   = AUTO_TARGET_ID
					getgenv()._auto_target_name = AUTO_TARGET_NAME
				end
			end)
			if not ok then print("[auto] combat load error: " .. tostring(err)) end
		end
	end

	-- Keep heartbeating as auto role
	task.spawn(function()
		while true do
			post("/api/heartbeat", {
				scoutId      = SCOUT_ID,
				currentJob   = game.JobId,
				username     = USERNAME,
				robloxUserId = SCOUT_ID,
				vps          = VPS_ID,
				role         = "auto",
				playerCount  = #game.Players:GetPlayers(),
				hops         = 0,
			})
			task.wait(10)
		end
	end)

	return -- don't run scout loop
end

-- ── scout mode from here ──────────────────────────────────────
local function fetchTargets()
	local ok, res = pcall(function()
		return req({Url = SERVER .. "/api/target", Method = "GET"})
	end)
	if not ok or not res or not res.Body then return false end
	local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
	if ok2 and d and d.targets then
		targets = {}
		for _, uid in ipairs(d.targets) do targets[tostring(uid)] = true end
		return true
	end
	return false
end

local function getNewServer()
	local ok, res = pcall(function()
		return req({
			Url = SERVER .. "/api/nextserver?scoutId=" .. SCOUT_ID,
			Method = "GET"
		})
	end)
	if ok and res and res.StatusCode == 200 then
		local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
		if ok2 and d and d.jobId then
			return d.jobId
		end
	end
	return nil
end

local function scanPlayers()
	local playerIds = {}
	for _, p in ipairs(game.Players:GetPlayers()) do
		table.insert(playerIds, tostring(p.UserId))
		if targets[tostring(p.UserId)] then return tostring(p.UserId) end
	end
	print("[scout] targets:", table.concat(next(targets) and (function() local t={} for k in pairs(targets) do table.insert(t,k) end return t end)() or {}, ","))
	print("[scout] players in server:", table.concat(playerIds, ","))
	return nil
end

local function fling(targetUserId)
	local target = game.Players:FindFirstChild(targetUserId) or
		(function()
			for _, p in ipairs(game.Players:GetPlayers()) do
				if tostring(p.UserId) == targetUserId then return p end
			end
		end)()
	if not target or not target.Character then return end
	local hrp = target.Character:FindFirstChild("HumanoidRootPart")
	if not hrp then return end

	local myChar = game.Players.LocalPlayer.Character
	local myHrp = myChar and myChar:FindFirstChild("HumanoidRootPart")
	if myHrp then
		myHrp.CFrame = hrp.CFrame * CFrame.new(0, 0, -2)
	end

	local bv = Instance.new("BodyVelocity")
	bv.Velocity = Vector3.new(math.random(-200,200), 500, math.random(-200,200))
	bv.MaxForce = Vector3.new(math.huge, math.huge, math.huge)
	bv.Parent = hrp
	game:GetService("Debris"):AddItem(bv, 0.2)
end

local function reportFound(uid)
	status = "found"
	print("[scout] found " .. uid .. " in " .. game.JobId)

	-- report to server and check if more targets remain
	local keepScanning = false
	pcall(function()
		local res = req({
			Url     = SERVER .. "/api/found",
			Method  = "POST",
			Headers = {["Content-Type"] = "application/json"},
			Body    = hs:JSONEncode({userId = uid, jobId = game.JobId, scoutId = SCOUT_ID})
		})
		if res and res.Body then
			local d = hs:JSONDecode(res.Body)
			keepScanning = d and d.keepScanning == true
		end
	end)

	task.wait(1)
	fling(uid)

	if keepScanning then
		-- remove found target locally, keep hopping for remaining targets
		targets[uid] = nil
		found   = false
		running = true
		status  = "searching"
		print("[scout] more targets remain, continuing")
	else
		found   = true
		running = false
		status  = "all found"
	end
end

-- ── heartbeat ─────────────────────────────────────────────────
task.spawn(function()
	while not stopped do
		post("/api/heartbeat", {
			scoutId      = SCOUT_ID,
			currentJob   = game.JobId,
			username     = USERNAME,
			robloxUserId = tostring(lp.UserId),
			vps          = VPS_ID,
			role         = "scout",
			playerCount  = #game.Players:GetPlayers(),
			hops         = hops,
		})
		task.wait(10)
	end
end)

-- ── player join watch ─────────────────────────────────────────
game.Players.PlayerAdded:Connect(function(p)
	if running and targets[tostring(p.UserId)] then
		reportFound(tostring(p.UserId))
	end
end)

-- ── main ──────────────────────────────────────────────────────
task.wait(1)
status = fetchTargets() and "connected" or "no connection"

while not stopped do
	fetchTargets()

	if next(targets) == nil then
		status  = "idle"
		running = false
		task.wait(5)
	else
		running = true
		status  = "searching"

		local hit = scanPlayers()
		if hit then
			reportFound(hit)
			if found then break end
			continue
		end

		print("[scout " .. SCOUT_ID .. "] " .. (game.JobId ~= "" and game.JobId:sub(1,8) or "?") .. " — not found")
		hops += 1
		getgenv()._scoutHops = hops

		local nextJob = getNewServer()

		if nextJob then
			local ok, err = pcall(function()
				ts:TeleportToPlaceInstance(PLACE_ID, nextJob, game.Players.LocalPlayer)
			end)
			if not ok then
				print("[scout] teleport failed: " .. tostring(err))
			end
		else
			pcall(function() ts:Teleport(PLACE_ID) end)
		end

		-- Small yield so the teleport can fire before the loop continues
		task.wait(0.2)
	end
end
