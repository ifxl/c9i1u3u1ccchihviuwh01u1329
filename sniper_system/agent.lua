local ts      = game:GetService("TeleportService")
local hs      = game:GetService("HttpService")
local rs      = game:GetService("RunService")
local rep     = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local req     = (syn and syn.request) or request

local SERVER   = "https://sniper-zlqd.onrender.com"
local PLACE_ID = game.PlaceId

local lp
repeat lp = Players.LocalPlayer task.wait() until lp
local SCOUT_ID = tostring(lp.UserId)
local USERNAME = lp.Name

local function post(path, data)
	pcall(function()
		req({Url=SERVER..path, Method="POST", Headers={["Content-Type"]="application/json"}, Body=hs:JSONEncode(data)})
	end)
end

local function get(path)
	local ok, res = pcall(function() return req({Url=SERVER..path, Method="GET"}) end)
	if ok and res and res.Body then
		local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
		if ok2 then return d end
	end
	return nil
end

local function makeGui(title, subtitle)
	local g = Instance.new("ScreenGui"); g.Name="agent"; g.ResetOnSpawn=false; g.ZIndexBehavior=Enum.ZIndexBehavior.Sibling; g.Parent=game.CoreGui
	local win = Instance.new("Frame"); win.Size=UDim2.new(0,200,0,130); win.Position=UDim2.new(1,-216,1,-146)
	win.BackgroundColor3=Color3.fromRGB(6,6,6); win.BorderSizePixel=0; win.Active=true; win.Draggable=true; win.Parent=g
	Instance.new("UICorner",win).CornerRadius=UDim.new(0,8)
	local ws=Instance.new("UIStroke"); ws.Color=Color3.fromRGB(22,22,22); ws.Thickness=1; ws.Parent=win
	local hdr=Instance.new("Frame"); hdr.Size=UDim2.new(1,0,0,34); hdr.BackgroundColor3=Color3.fromRGB(11,11,11); hdr.BorderSizePixel=0; hdr.Parent=win
	Instance.new("UICorner",hdr).CornerRadius=UDim.new(0,8)
	local hfix=Instance.new("Frame"); hfix.Size=UDim2.new(1,0,0,8); hfix.Position=UDim2.new(0,0,1,-8); hfix.BackgroundColor3=Color3.fromRGB(11,11,11); hfix.BorderSizePixel=0; hfix.Parent=hdr
	local dot=Instance.new("Frame"); dot.Size=UDim2.new(0,6,0,6); dot.Position=UDim2.new(0,12,0.5,-3); dot.BackgroundColor3=Color3.fromRGB(50,50,50); dot.BorderSizePixel=0; dot.Parent=hdr
	Instance.new("UICorner",dot).CornerRadius=UDim.new(1,0)
	local titleLbl=Instance.new("TextLabel"); titleLbl.Size=UDim2.new(0,100,1,0); titleLbl.Position=UDim2.new(0,26,0,0); titleLbl.BackgroundTransparency=1
	titleLbl.Text=title; titleLbl.TextColor3=Color3.fromRGB(240,240,240); titleLbl.Font=Enum.Font.GothamBold; titleLbl.TextSize=11; titleLbl.TextXAlignment=Enum.TextXAlignment.Left; titleLbl.Parent=hdr
	local idLbl=Instance.new("TextLabel"); idLbl.Size=UDim2.new(0,70,1,0); idLbl.Position=UDim2.new(1,-76,0,0); idLbl.BackgroundTransparency=1
	idLbl.Text="#"..SCOUT_ID:sub(-6); idLbl.TextColor3=Color3.fromRGB(40,40,40); idLbl.Font=Enum.Font.Gotham; idLbl.TextSize=9; idLbl.TextXAlignment=Enum.TextXAlignment.Right; idLbl.Parent=hdr
	local function makeRow(y, key)
		local row=Instance.new("Frame"); row.Size=UDim2.new(1,-24,0,14); row.Position=UDim2.new(0,12,0,y); row.BackgroundTransparency=1; row.Parent=win
		local k=Instance.new("TextLabel"); k.Size=UDim2.new(0,80,1,0); k.BackgroundTransparency=1; k.Text=key; k.TextColor3=Color3.fromRGB(45,45,45); k.Font=Enum.Font.Gotham; k.TextSize=10; k.TextXAlignment=Enum.TextXAlignment.Left; k.Parent=row
		local v=Instance.new("TextLabel"); v.Size=UDim2.new(1,-84,1,0); v.Position=UDim2.new(0,84,0,0); v.BackgroundTransparency=1; v.Text="—"; v.TextColor3=Color3.fromRGB(180,180,180); v.Font=Enum.Font.Gotham; v.TextSize=10; v.TextXAlignment=Enum.TextXAlignment.Right; v.TextTruncate=Enum.TextTruncate.AtEnd; v.Parent=row
		return v, dot
	end
	local r1, _ = makeRow(42, "mode")
	local r2    = makeRow(58, subtitle)
	local r3    = makeRow(74, "status")
	local stopBtn=Instance.new("TextButton"); stopBtn.Size=UDim2.new(1,-24,0,20); stopBtn.Position=UDim2.new(0,12,1,-26)
	stopBtn.BackgroundColor3=Color3.fromRGB(16,16,16); stopBtn.TextColor3=Color3.fromRGB(100,100,100); stopBtn.Font=Enum.Font.GothamBold; stopBtn.TextSize=10; stopBtn.Text="stop"; stopBtn.BorderSizePixel=0; stopBtn.Parent=win
	Instance.new("UICorner",stopBtn).CornerRadius=UDim.new(0,5)
	Instance.new("UIStroke",stopBtn).Color=Color3.fromRGB(22,22,22)
	return g, dot, r1, r2, r3, stopBtn
end

-- Show GUI immediately so the user knows the script is running
-- Status updates live as the assignment check progresses
local _earlyGui, _earlyDot, _earlyMode, _earlySub, _earlyStatus, _earlyStop = makeGui("agent", "status")
_earlyMode.Text   = "checking"
_earlySub.Text    = "—"
_earlyStatus.Text = "connecting..."
local _earlyStopped = false
_earlyStop.MouseButton1Click:Connect(function() _earlyStopped = true; _earlyStatus.Text = "stopped" end)

local t0 = 0
rs.RenderStepped:Connect(function(dt)
	t0 += dt
	local v = math.sin(t0 * 3) * 0.5 + 0.5
	_earlyDot.BackgroundColor3 = Color3.new(v, v, v)
end)

-- Check assignment with retries in background — GUI stays responsive.
-- The launch and script injection happen nearly simultaneously, so the first
-- check often fires before the server has recorded the assignment (especially
-- on Render where the server may be cold-starting). Retry generously.
local assignment = nil
local IS_AUTO    = false
do
	for attempt = 1, 15 do
		if _earlyStopped then break end
		_earlyStatus.Text = "check " .. attempt .. "/15"
		local ok, res = pcall(function()
			return req({ Url = SERVER .. "/api/assignment?accountId=" .. SCOUT_ID, Method = "GET" })
		end)
		if ok and res and res.Body then
			local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
			if ok2 and d and d.assigned == true then
				assignment = d
				IS_AUTO    = true
				_earlyStatus.Text = "assigned!"
				print("[agent] assignment found on attempt " .. attempt)
				break
			end
			_earlyStatus.Text = "no assign " .. attempt
		else
			_earlyStatus.Text = "offline " .. attempt
			print("[agent] attempt " .. attempt .. " — server unreachable, retrying...")
		end
		if attempt < 15 then task.wait(3) end
	end

	-- Fallback: check by current job ID
	-- Catches the "Assigned → any" case where server doesn't know our internal ID.
	-- The bot is IN the right server already — just confirm the server has an
	-- assignment for this job and claim it.
	if not IS_AUTO and game.JobId ~= "" then
		_earlyStatus.Text = "job check..."
		local ok, res = pcall(function()
			return req({
				Url    = SERVER .. "/api/assignment/by_job?jobId=" .. game.JobId .. "&accountId=" .. SCOUT_ID,
				Method = "GET"
			})
		end)
		if ok and res and res.Body then
			local ok2, d = pcall(function() return hs:JSONDecode(res.Body) end)
			if ok2 and d and d.assigned == true then
				assignment = d
				IS_AUTO    = true
				_earlyStatus.Text = "assigned (job)!"
				print("[agent] assignment found via job ID fallback")
			end
		end
	end
end

if not IS_AUTO then
	_earlyMode.Text   = "scout"
	_earlyStatus.Text = "scouting"
end
local pendingAuto = nil

if IS_AUTO then
	local TARGET_ID   = tostring(assignment.targetUserId or "")
	local TARGET_NAME = tostring(assignment.targetUsername or "unknown")
	local JOB_ID      = tostring(assignment.jobId or "")

	-- Destroy the early-check GUI and replace with the proper auto GUI
	if _earlyGui then pcall(function() _earlyGui:Destroy() end) end

	-- Show GUI immediately
	local _, dot, modeVal, targetVal, statusVal, stopBtn = makeGui("auto", "target")
	modeVal.Text   = "combat"
	targetVal.Text = TARGET_NAME
	statusVal.Text = "loading"

	local stopped = false
	stopBtn.MouseButton1Click:Connect(function() stopped=true; statusVal.Text="stopped" end)

	local t=0
	rs.RenderStepped:Connect(function(dt)
		t+=dt
		local v=math.sin(t*3)*0.5+0.5
		dot.BackgroundColor3=Color3.new(v,v,v)
	end)

	-- Wait for game to fully load
	repeat task.wait(0.5) until game:IsLoaded()
	task.wait(1)

	-- Heartbeat loop (runs until stopped)
	task.spawn(function()
		while not stopped do
			post("/api/heartbeat", {
				scoutId      = SCOUT_ID,
				currentJob   = game.JobId,
				username     = USERNAME,
				robloxUserId = SCOUT_ID,
				vps          = "vps-default",
				role         = "auto",
				playerCount  = #Players:GetPlayers(),
				hops         = 0,
			})
			task.wait(10)
		end
	end)

	statusVal.Text = "finding target"

	-- Wait up to 30s for the target to be in the server
	local targetPlayer = nil
	local function findTarget()
		for _, p in ipairs(Players:GetPlayers()) do
			if tostring(p.UserId) == TARGET_ID then return p end
		end
		return nil
	end
	targetPlayer = findTarget()
	if not targetPlayer then
		local waited = 0
		repeat task.wait(1); waited += 1; targetPlayer = findTarget() until targetPlayer or waited >= 30
	end

	if not targetPlayer then
		statusVal.Text = "target not found"
		print("[auto] target " .. TARGET_ID .. " not found in server after 30s")
		return
	end

	-- Tell server we're active
	post("/api/assignment/complete", { accountId = SCOUT_ID })
	statusVal.Text = "active — " .. TARGET_NAME
	print("[auto] target found: " .. TARGET_NAME .. " — loading combat.lua")

	-- Set target globally so combat.lua picks it up on start
	getgenv()._auto_target_id   = TARGET_ID
	getgenv()._auto_target_name = TARGET_NAME

	-- Load combat.lua directly from GitHub (raw URL — always the latest version)
	-- Replace this URL after you push combat.lua to your public GitHub repo
	local COMBAT_URL = "https://raw.githubusercontent.com/ifxl/c9i1u3u1ccchihviuwh01u1329/main/combat.lua"

	local ok, err = pcall(function()
		local src = game:HttpGet(COMBAT_URL, true)
		if not src or #src < 100 then
			error("combat script too short or empty (" .. tostring(#(src or "")) .. " chars) — check the URL")
		end
		loadstring(src)()
	end)

	if not ok then
		statusVal.Text = "combat load failed"
		print("[auto] combat.lua load error: " .. tostring(err))
	end

	return
end

local targets={} local running=false local found=false local stopped=false
local hops=getgenv()._scoutHops or 0; getgenv()._scoutHops=hops

-- Destroy the early-check GUI and replace with the scout GUI
if _earlyGui then pcall(function() _earlyGui:Destroy() end) end

local _, dot, modeVal, hopVal, serverVal, stopBtn = makeGui("scout", "hopped")
modeVal.Text = "scouting"
local t2=0
rs.RenderStepped:Connect(function(dt)
	t2+=dt
	if running then local v=math.sin(t2*3)*0.5+0.5; dot.BackgroundColor3=Color3.new(v,v,v)
	elseif found then dot.BackgroundColor3=Color3.fromRGB(255,255,255)
	elseif stopped then dot.BackgroundColor3=Color3.fromRGB(22,22,22)
	else dot.BackgroundColor3=Color3.fromRGB(50,50,50) end
	hopVal.Text = tostring(hops)
	local jid=game.JobId; serverVal.Text=jid~="" and jid:sub(1,12).."…" or "—"
end)
stopBtn.MouseButton1Click:Connect(function() stopped=true; running=false end)

-- Background assignment poll — runs indefinitely while scouting.
-- If this account gets assigned at any point, stop scout and teleport to the target server.
task.spawn(function()
	while not stopped do
		task.wait(5)
		local res=get("/api/assignment?accountId="..SCOUT_ID)
		if res and res.assigned==true then
			pendingAuto=res
			stopped=true; running=false
			break
		end
	end
end)

local function post2(path,data) post(path,data) end
local function fetchTargets()
	local ok,res=pcall(function() return req({Url=SERVER.."/api/target",Method="GET"}) end)
	if not ok or not res or not res.Body then return false end
	local ok2,d=pcall(function() return hs:JSONDecode(res.Body) end)
	if ok2 and d and d.targets then targets={}; for _,uid in ipairs(d.targets) do targets[tostring(uid)]=true end; return true end
	return false
end
local function getNewServer()
	local ok,res=pcall(function() return req({Url=SERVER.."/api/nextserver?scoutId="..SCOUT_ID,Method="GET"}) end)
	if ok and res and res.StatusCode==200 then
		local ok2,d=pcall(function() return hs:JSONDecode(res.Body) end)
		if ok2 and d and d.jobId then return d.jobId end
	end
	return nil
end
local function scanPlayers()
	for _,p in ipairs(Players:GetPlayers()) do if targets[tostring(p.UserId)] then return tostring(p.UserId) end end
	return nil
end
local function reportFound(uid)
	local keepScanning=false
	pcall(function()
		local res=req({Url=SERVER.."/api/found",Method="POST",Headers={["Content-Type"]="application/json"},Body=hs:JSONEncode({userId=uid,jobId=game.JobId,scoutId=SCOUT_ID})})
		if res and res.Body then local d=hs:JSONDecode(res.Body); keepScanning=d and d.keepScanning==true end
	end)
	local target=(function() for _,p in ipairs(Players:GetPlayers()) do if tostring(p.UserId)==uid then return p end end end)()
	if target and target.Character then
		local hrp=target.Character:FindFirstChild("HumanoidRootPart")
		if hrp then local bv=Instance.new("BodyVelocity"); bv.Velocity=Vector3.new(math.random(-200,200),500,math.random(-200,200)); bv.MaxForce=Vector3.new(math.huge,math.huge,math.huge); bv.Parent=hrp; game:GetService("Debris"):AddItem(bv,0.2) end
	end
	if keepScanning then targets[uid]=nil; found=false; running=true else found=true; running=false end
end

task.spawn(function() while not stopped do post("/api/heartbeat",{scoutId=SCOUT_ID,currentJob=game.JobId,username=USERNAME,robloxUserId=SCOUT_ID,vps="vps-default",role="scout",playerCount=#Players:GetPlayers(),hops=hops}); task.wait(10) end end)
Players.PlayerAdded:Connect(function(p) if running and targets[tostring(p.UserId)] then reportFound(tostring(p.UserId)) end end)

fetchTargets()
while not stopped do
	fetchTargets()
	if next(targets)==nil then running=false; task.wait(1)
	else
		running=true
		local hit=scanPlayers()
		if hit then reportFound(hit); if found then break end; continue end
		hops+=1; getgenv()._scoutHops=hops
		local nextJob=getNewServer()
		if nextJob then
			pcall(function() ts:TeleportToPlaceInstance(PLACE_ID,nextJob,lp) end)
		else
			pcall(function() ts:Teleport(PLACE_ID) end)
		end
	end
end

-- Only switch to combat if the scout loop was stopped by an assignment, not a natural find
if pendingAuto and not found then
	assignment = pendingAuto
	IS_AUTO    = true
	-- re-execute the combat block by reloading the script via loadstring
	-- simplest: just teleport to the assigned server — agent will re-inject as auto on next load
	local jid = assignment.jobId
	if jid and jid ~= "" then
		modeVal.Text = "auto"
		hopVal.Text  = assignment.targetUsername or "?"
		serverVal.Text = "joining..."
		task.wait(1)
		pcall(function() ts:TeleportToPlaceInstance(PLACE_ID, jid, lp) end)
	end
end
