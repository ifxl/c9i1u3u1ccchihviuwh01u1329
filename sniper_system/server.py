from flask import Flask, request, jsonify, render_template_string, send_from_directory, session, redirect, url_for, abort
from flask_cors import CORS
import time, threading, requests, os, secrets

# Absolute path to static files — same folder as server.py in this repo layout
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
# On Render the 309xpz folder doesn't exist — serve dashboard from the embedded HTML.
# Locally: set STATIC_DIR env var to the absolute path of your 309xpz folder.
_static_env = os.environ.get("STATIC_DIR")
if _static_env and os.path.isdir(_static_env):
    STATIC_DIR = _static_env
elif os.path.isdir(os.path.join(os.path.dirname(BASE_DIR), "309xpz")):
    STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "309xpz")
else:
    STATIC_DIR = BASE_DIR  # fallback: serve embedded dashboard from server.py

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static-disabled")
# Allow the frontend (wherever it's hosted) to call the API
CORS(app, supports_credentials=True, origins="*")

# ── Auth config ────────────────────────────────────────────────────────────────
DASHBOARD_PASSWORD = os.environ.get("SNIPER_PASS", "changeme")  # set via env var
SCOUT_API_KEY      = os.environ.get("SCOUT_KEY",   "scout-key-changeme")  # used by Lua scouts

# Stable secret key — env var takes priority (required for Render/cloud deploys)
# Falls back to a local file so sessions survive local restarts too
_key_from_env = os.environ.get("SECRET_KEY")
if _key_from_env:
    app.secret_key = _key_from_env
else:
    _key_file = os.path.join(os.path.dirname(__file__), ".secret_key")
    if os.path.exists(_key_file):
        with open(_key_file, "r") as f:
            app.secret_key = f.read().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        with open(_key_file, "w") as f:
            f.write(app.secret_key)

def require_auth():
    """Returns True if the current request is authenticated."""
    return session.get("authed") is True

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sniper — login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#000;color:#e8e8e8;font-family:'Inter',sans-serif;display:flex;
     align-items:center;justify-content:center;min-height:100vh}
.box{background:#0c0c0c;border:1px solid #1f1f1f;border-radius:10px;padding:36px 32px;width:320px}
.logo{font-size:13px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
      color:#fff;margin-bottom:28px}
.lbl{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1px;
     color:#555;margin-bottom:7px}
.inp{width:100%;background:#141414;border:1px solid #2a2a2a;color:#e8e8e8;
     padding:10px 13px;border-radius:7px;font-size:13px;font-family:'Inter',sans-serif;
     outline:none;transition:border-color .15s}
.inp:focus{border-color:#444}
.btn{margin-top:16px;width:100%;background:#fff;color:#000;border:none;
     padding:11px;border-radius:7px;font-size:13px;font-weight:700;
     font-family:'Inter',sans-serif;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.88}
.err{font-size:11px;color:#f87171;margin-top:10px;min-height:14px}
</style>
</head>
<body>
<div class="box">
  <div class="logo">sniper</div>
  <div class="lbl">Password</div>
  <form method="POST" action="/login">
    <input class="inp" type="password" name="password" autofocus placeholder="enter password">
    <button class="btn" type="submit">Enter</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["authed"] = True
            session.permanent = True
            return redirect("/")
        return render_template_string(LOGIN_PAGE, error="Wrong password")
    if require_auth():
        return redirect("/")
    return render_template_string(LOGIN_PAGE, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")
# ──────────────────────────────────────────────────────────────────────────────

@app.before_request
def check_auth():
    # Always allow login/logout through
    if request.path in ("/login", "/logout"):
        return None
    # OPTIONS preflight
    if request.method == "OPTIONS":
        return None
    # Scout API endpoints — accept X-API-Key header OR allow unauthenticated
    # (scouts run inside Roblox and can't hold session cookies)
    SCOUT_ENDPOINTS = ("/api/heartbeat", "/api/found", "/api/nextserver", "/api/target", "/api/scout/kicked", "/api/assignment", "/api/assignment/complete", "/api/assignment/by_job", "/api/combat_script", "/api/target_lost")
    if request.path in SCOUT_ENDPOINTS:
        return None  # scouts are unauthenticated by design
    # MultiRoblox desktop app endpoints — polled without a browser session.
    # Allow through with Scout API key, valid session, or unconditionally
    # (these routes carry no sensitive data and require knowing the VPS ID).
    DESKTOP_APP_ENDPOINTS = (
        "/api/commands",
        "/api/commands/push",
        "/api/commands/launch",
        "/api/commands/report",
        "/api/altgen/pending",
        "/api/altgen/claim",
        "/api/account/register",
        "/api/account/status",
        "/api/vps",
        "/api/vps/register",
        "/api/scout/start",
        "/api/queue/check",
        "/api/queue/claim",
        "/api/queue/release",
    )
    if request.path in DESKTOP_APP_ENDPOINTS or request.path.startswith("/api/commands"):
        return None  # desktop app doesn't have a session cookie
    # Everything else — must have valid session
    if not require_auth():
        if request.path.startswith("/api/"):
            abort(401)
        return redirect("/login")
    return None

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    return response

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1526445045132034058/9xDuQbo36G-zTr4_n41QawZpNW3ecoXGBJ-QLaAzDfkFPafamBOTk3b1tyD_LKYhRDoC"
PLACE_ID        = 2788229376
SCOUT_TIMEOUT   = 30

# ── State ──────────────────────────────────────────────────────────────────────
# accounts[account_id] = {
#   username, roblox_user_id, role (scout|auto|idle),
#   status (scouting|assigned|autoing|offline|idle),
#   current_server, player_count, assigned_target, last_seen, vps
# }
# targets[user_id]   = {username, avatar, status (searching|found|lost), jobId, joinUrl, ...}
# assignments[acct]  = {targetUserId, jobId, joinUrl, assigned_at}
state = {"targets": {}, "accounts": {}, "history": [], "assignments": {}}
lock  = threading.Lock()

# ── Helpers ────────────────────────────────────────────────────────────────────
def roblox_username(uid):
    try:
        r = requests.post("https://users.roblox.com/v1/users",
            json={"userIds":[int(uid)],"excludeBannedUsers":False}, timeout=8)
        if r.status_code == 200:
            d = r.json().get("data",[])
            if d: return d[0].get("name", str(uid))
    except Exception as e:
        print(f"[!] roblox_username({uid}) failed: {e}")
    return str(uid)

def roblox_avatar(uid):
    try:
        r = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
            f"?userIds={uid}&size=150x150&format=Png", timeout=8)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: return data[0].get("imageUrl", "")
    except Exception as e:
        print(f"[!] roblox_avatar({uid}) failed: {e}")
    return ""

def roblox_lookup(uid):
    return roblox_username(uid), roblox_avatar(uid)

def send_webhook(uid, username, job_id, join_url, assigned_to=None):
    if not DISCORD_WEBHOOK: return
    try:
        desc = f"**{username}** (`{uid}`)\n[Join]({join_url})\n`{job_id}`"
        if assigned_to:
            desc += f"\nAssigned → **{assigned_to}**"
        requests.post(DISCORD_WEBHOOK, json={"embeds":[{
            "title": "Target Found",
            "description": desc,
            "color": 0xffffff
        }]}, timeout=8)
    except: pass

# ── Known VPS registry ────────────────────────────────────────────────────────
# Persists VPS IDs even when their command queue is empty
_known_vps: set = set()

def _pick_auto_account(exclude=None):
    """Pick an available account to dispatch. Prefers 'auto' role, falls back to any idle account,
    then falls back to any MultiRoblox-registered account that isn't already assigned.
    exclude: account_id to skip (e.g. the scout that found the target)."""
    now = time.time()
    # First pass: prefer dedicated auto-role accounts that are online and idle
    for aid, acct in state["accounts"].items():
        if aid == exclude: continue
        if (acct.get("role") == "auto"
                and acct.get("status") in ("idle", "available")
                and (now - acct.get("last_seen", 0)) < SCOUT_TIMEOUT
                and aid not in state["assignments"]):
            return aid
    # Second pass: any account that isn't actively scouting/assigned and is recently seen
    for aid, acct in state["accounts"].items():
        if aid == exclude: continue
        if (acct.get("status") in ("idle", "available")
                and (now - acct.get("last_seen", 0)) < SCOUT_TIMEOUT
                and aid not in state["assignments"]):
            return aid
    # Third pass: any MultiRoblox-registered account not currently assigned
    # (relaxed timeout — MultiRoblox accounts have a 10-min offline window)
    for aid, acct in state["accounts"].items():
        if aid == exclude: continue
        if (acct.get("multiroblox")
                and acct.get("status") not in ("assigned", "autoing")
                and (now - acct.get("last_seen", 0)) < 600
                and aid not in state["assignments"]):
            return aid
    return None

def _mark_account_offline():
    """Background thread — marks accounts offline if no heartbeat.
    Also alerts via webhook if a scout never heartbeated within 90s of launch
    (likely game-banned with Error 600 pre-join screen)."""
    NO_HEARTBEAT_TIMEOUT = 90  # seconds after launch before alerting
    while True:
        time.sleep(15)
        now = time.time()
        to_alert = []
        with lock:
            for aid, acct in state["accounts"].items():
                # Standard offline detection
                timeout = SCOUT_TIMEOUT * 10 if acct.get("multiroblox") else SCOUT_TIMEOUT
                if (now - acct.get("last_seen", 0)) > timeout:
                    if acct.get("status") != "offline":
                        acct["status"] = "offline"
                        # Release any stuck assignment so the account can be re-dispatched
                        state["assignments"].pop(aid, None)
                        print(f"[!] account {aid} ({acct.get('username','?')}) went offline")
                # No-heartbeat-after-launch detection
                launched_at = acct.get("launched_at")
                if (launched_at and
                        not acct.get("heartbeat_alerted") and
                        (now - launched_at) > NO_HEARTBEAT_TIMEOUT):
                    acct["heartbeat_alerted"] = True
                    acct["launched_at"] = None
                    to_alert.append((aid, acct.get("username", aid)))
        # Fire webhooks outside the lock
        for aid, username in to_alert:
            print(f"[!] {username} never heartbeated 90s after launch — possible game ban")
            threading.Thread(
                target=_check_ban_and_webhook,
                args=(aid, username, "game_banned",
                      "Scout never connected 90s after launch — likely game banned (Error 600)"),
                daemon=True
            ).start()

threading.Thread(target=_mark_account_offline, daemon=True).start()

def _check_ban_and_webhook(scout_id, username, reason, message):
    """Send webhook based on kick reason. No external API calls needed — reason comes from the game itself."""
    try:
        import requests as _req

        with lock:
            if scout_id in state["accounts"]:
                state["accounts"][scout_id]["status"] = "game_banned" if reason == "game_banned" else "offline"
                state["accounts"][scout_id]["last_kick_reason"] = reason
                state["accounts"][scout_id]["last_kick_msg"] = message

        if not DISCORD_WEBHOOK:
            return

        if reason == "game_banned":
            color = 0x000000
            title = "Scout — Game Banned"
            desc = f"**{username}**\n```{message[:300] if message else 'No details'}```\nThis account is banned from Da Hood. Remove and replace."
        elif reason == "kicked_anticheat":
            color = 0x111111
            title = "Scout — Anti-Cheat Kick"
            desc = f"**{username}**\n```{message[:300] if message else 'No details'}```\nRelaunching."
        elif reason == "roblox_banned":
            color = 0x000000
            title = "Scout — Account Terminated"
            desc = f"**{username}**\n```{message[:300] if message else 'No details'}```"
        else:
            color = 0x222222
            title = "Scout — Kicked"
            desc = f"**{username}**\n```{message[:300] if message else 'No details'}```\nRelaunching."

        _req.post(DISCORD_WEBHOOK, json={"embeds":[{
            "title": title,
            "description": desc,
            "color": color
        }]}, timeout=8)
    except Exception as e:
        print(f"[!] kick webhook error: {e}")

# ── Scout API ──────────────────────────────────────────────────────────────────
@app.route("/api/combat_script")
def get_combat_script():
    """Serves the combat/rage bot script to auto accounts.
    Priority:
      1. Local file (same dir as server.py, or one level up) — used when running locally
      2. COMBAT_SCRIPT_URL env var — a raw GitHub URL for the private repo (Render/cloud)
    """
    import os

    # ── Local file (development / local server) ───────────────────────────────
    candidates = [
        os.path.join(os.path.dirname(__file__), "combat.lua"),
        os.path.join(os.path.dirname(__file__), "..", "combat.lua"),
    ]
    for script_path in candidates:
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                return f.read(), 200, {"Content-Type": "text/plain"}

    # ── Remote URL (Render / cloud deployment) ────────────────────────────────
    # Set COMBAT_SCRIPT_URL to the raw GitHub URL, e.g.:
    #   https://raw.githubusercontent.com/YOU/dh-scripts/main/combat.lua
    # Set GITHUB_TOKEN to a personal access token with repo read scope.
    script_url   = os.environ.get("COMBAT_SCRIPT_URL", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if script_url:
        try:
            import requests as _req
            headers = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            r = _req.get(script_url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.text, 200, {"Content-Type": "text/plain"}
            print(f"[combat_script] GitHub fetch failed: {r.status_code}")
        except Exception as e:
            print(f"[combat_script] fetch error: {e}")

    return "-- combat script not found", 200, {"Content-Type": "text/plain"}

@app.route("/api/target")
def get_target():
    with lock:
        return jsonify({"targets":[u for u,t in state["targets"].items() if t["status"]=="searching"]})

@app.route("/api/scout/kicked", methods=["POST"])
def scout_kicked():
    d        = request.json or {}
    scout_id = str(d.get("scoutId","")).strip()
    username = d.get("username", scout_id)
    reason   = d.get("reason", "kicked_unknown")
    message  = d.get("message", "")
    job_id   = d.get("jobId", "")

    print(f"[!] scout {username} kicked — reason={reason} msg={message[:80]}")

    with lock:
        if scout_id in state["accounts"]:
            state["accounts"][scout_id]["status"] = "offline"
            state["accounts"][scout_id]["last_kick_reason"] = reason
            state["accounts"][scout_id]["last_kick_msg"] = message

    # Queue a relaunch unless it's a hard ban
    relaunch = reason not in ("game_banned", "roblox_banned")
    if relaunch:
        with lock:
            vps = state["accounts"].get(scout_id, {}).get("vps", next(iter(_known_vps), "vps-b-43"))
        with _command_lock:
            _command_queues.setdefault(vps, []).append({
                "type":      "launch",
                "accountId": scout_id,
                "target":    f"https://www.roblox.com/games/{PLACE_ID}",
                "reason":    "scout_relaunch_after_kick",
            })

    # Fire ban check + webhook in background
    threading.Thread(
        target=_check_ban_and_webhook,
        args=(scout_id, username, reason, message),
        daemon=True
    ).start()

    return jsonify({"ok": True, "relaunch": relaunch})

@app.route("/api/found", methods=["POST"])
def found():
    d   = request.json or {}
    uid = str(d.get("userId","")).strip()
    jid = str(d.get("jobId","")).strip()
    sid = str(d.get("scoutId","unknown"))
    if not uid or not jid: return jsonify({"ok":False}), 400

    url = f"https://www.roblox.com/games/{PLACE_ID}?gameInstanceId={jid}"
    assigned_acct = None
    assigned_name = None

    with lock:
        uname = state["targets"].get(uid,{}).get("username") or uid
        av    = state["targets"].get(uid,{}).get("avatar","")
        if uid in state["targets"]:
            state["targets"][uid].update({"status":"found","jobId":jid,"joinUrl":url,"foundAt":time.time()})

        state["history"].insert(0,{"userId":uid,"username":uname,"avatar":av,
            "jobId":jid,"joinUrl":url,"foundAt":time.time(),"foundBy":sid})
        state["history"] = state["history"][:50]

        # Find the actual account ID of the scout that found the target
        # so we never dispatch the same account to join its own server
        scout_account_id = None
        for aid, acct in state["accounts"].items():
            if (acct.get("roblox_user_id") == sid or
                    acct.get("username") == sid or
                    aid == sid):
                scout_account_id = aid
                break
        # Also try matching by current_server — the scout is in jid right now
        if not scout_account_id:
            for aid, acct in state["accounts"].items():
                if acct.get("current_server") == jid:
                    scout_account_id = aid
                    break

        # Auto-assign an available account — never the scout that found it
        aid = _pick_auto_account(exclude=scout_account_id)
        # Determine which VPS to send the command to
        if aid:
            assigned_vps = state["accounts"][aid].get("vps", "default")
        else:
            with _command_lock:
                known_vps = list(_command_queues.keys())
            assigned_vps = known_vps[0] if known_vps else (_known_vps and next(iter(_known_vps)) or "vps-b-43")

        if aid:
            state["assignments"][aid] = {
                "targetUserId": uid, "targetUsername": uname,
                "jobId": jid, "joinUrl": url, "assigned_at": time.time(),
                # store the Roblox userId of the assigned account so /api/assignment
                # can match even if the account hasn't heartbeated yet
                "robloxUserId": str(state["accounts"][aid].get("roblox_user_id", "")),
            }
            state["accounts"][aid]["status"] = "assigned"
            assigned_acct = aid
            assigned_name = state["accounts"][aid].get("username", aid)
            print(f"[+] {uname} found — queued launch for {assigned_name} on vps={assigned_vps}")
        else:
            # No specific account known yet — store under "any" so the first bot
            # that checks /api/assignment can claim it regardless of its internal ID.
            state["assignments"]["any"] = {
                "targetUserId": uid, "targetUsername": uname,
                "jobId": jid, "joinUrl": url, "assigned_at": time.time(),
                "robloxUserId": "",
            }
            assigned_name = "any"
            print(f"[+] {uname} found — no registered accounts, open-pick assignment stored, launch queued to vps={assigned_vps}")

        # Queue the launch command to MultiRoblox
        with _command_lock:
            _command_queues.setdefault(assigned_vps, []).append({
                "type":           "launch",
                "accountId":      aid,              # None = MultiRoblox picks, but respects excludeAccountId
                "excludeAccountId": scout_account_id,  # never launch the scout that found the target
                "target":         f"https://www.roblox.com/games/{PLACE_ID}?gameInstanceId={jid}",
                "jobId":          jid,
                "reason":         f"target_found:{uname}",
            })

        still_searching = sum(1 for t in state["targets"].values() if t["status"] == "searching")

    threading.Thread(target=send_webhook, args=(uid,uname,jid,url,assigned_name), daemon=True).start()
    return jsonify({"ok":True,"joinUrl":url,"keepScanning":still_searching > 0,"assignedTo":assigned_acct})

@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    d   = request.json or {}
    sid = str(d.get("scoutId",""))
    if not sid: return jsonify({"ok":False}), 400
    with lock:
        acct = state["accounts"].get(sid)
        if acct:
            acct["last_seen"]      = time.time()
            acct["current_server"] = d.get("currentJob")
            acct["player_count"]   = d.get("playerCount", 0)
            acct["hops"]           = d.get("hops", acct.get("hops", 0))
            # Heartbeat received — clear the no-heartbeat alert flag
            acct["launched_at"]        = None
            acct["heartbeat_alerted"]  = False
            if acct.get("status") == "offline":
                acct["status"] = acct.get("role","scout") == "auto" and "idle" or "scouting"
        else:
            # Auto-register if not known
            state["accounts"][sid] = {
                "username":       d.get("username", sid),
                "roblox_user_id": d.get("robloxUserId",""),
                "role":           d.get("role","scout"),
                "status":         d.get("role","scout") == "auto" and "idle" or "scouting",
                "current_server": d.get("currentJob"),
                "player_count":   d.get("playerCount", 0),
                "hops":           d.get("hops", 0),
                "assigned_target":None,
                "last_seen":      time.time(),
                "vps":            d.get("vps","unknown"),
            }
            print(f"[+] new account registered: {d.get('username', sid)} ({d.get('role','scout')})")
    return jsonify({"ok":True})

@app.route("/api/account/register", methods=["POST"])
def register_account():
    d   = request.json or {}
    sid = str(d.get("accountId","")).strip()
    if not sid: return jsonify({"ok":False,"error":"no accountId"}), 400
    with lock:
        state["accounts"][sid] = {
            "username":       d.get("username", sid),
            "roblox_user_id": d.get("robloxUserId",""),
            "role":           d.get("role","scout"),
            "status":         d.get("role","scout") == "auto" and "idle" or "scouting",
            "current_server": None,
            "player_count":   0,
            "assigned_target":None,
            "last_seen":      time.time(),
            "vps":            d.get("vps","unknown"),
        }
        print(f"[+] registered: {d.get('username',sid)} as {d.get('role','scout')}")
    return jsonify({"ok":True})

@app.route("/api/account/status", methods=["POST"])
def update_account_status():
    d   = request.json or {}
    sid = str(d.get("accountId","")).strip()
    with lock:
        if sid in state["accounts"]:
            if "status" in d: state["accounts"][sid]["status"] = d["status"]
            if "currentJob" in d: state["accounts"][sid]["current_server"] = d["currentJob"]
            if "playerCount" in d: state["accounts"][sid]["player_count"] = d["playerCount"]
            state["accounts"][sid]["last_seen"] = time.time()
    return jsonify({"ok":True})

@app.route("/api/assignment")
def get_assignment():
    aid = request.args.get("accountId","")
    with lock:
        now = time.time()
        # Expire assignments older than 5 minutes (account never joined)
        expired = [k for k, v in state["assignments"].items()
                   if (now - v.get("assigned_at", now)) > 300]
        for k in expired:
            state["assignments"].pop(k, None)
            if k in state["accounts"]:
                state["accounts"][k]["status"] = "idle"
            print(f"[assignment] expired stale assignment for {k}")

        print(f"[assignment] lookup aid={aid} assignments={list(state['assignments'].keys())} roblox_ids={[(k, v.get('roblox_user_id','')) for k,v in state['accounts'].items()]}")
        # Direct key match (internal UUID)
        if aid in state["assignments"]:
            return jsonify({"assigned":True, **state["assignments"][aid]})
        # Fallback 1: match by roblox_user_id stored on the account record
        for internal_id, assignment in state["assignments"].items():
            acct = state["accounts"].get(internal_id, {})
            if str(acct.get("roblox_user_id","")) == str(aid):
                return jsonify({"assigned":True, **assignment})
        # Fallback 2: match by roblox_user_id stored directly on the assignment
        # (set at queue time so lookup works even before the account has heartbeated)
        for internal_id, assignment in state["assignments"].items():
            if str(assignment.get("robloxUserId","")) == str(aid):
                return jsonify({"assigned":True, **assignment})
        # Fallback 3: "any" open-pick assignment — first bot to check gets it
        # Claim it by re-keying under this bot's actual ID so nobody else grabs it
        if "any" in state["assignments"]:
            claimed = state["assignments"].pop("any")
            claimed["robloxUserId"] = str(aid)
            state["assignments"][aid] = claimed
            print(f"[assignment] claimed open-pick assignment for {aid}")
            return jsonify({"assigned":True, **claimed})
    return jsonify({"assigned":False})

@app.route("/api/assignment/by_job")
def get_assignment_by_job():
    """Look up an assignment by job ID instead of account ID.
    Used by bots that don't know their internal ID — they check if the server
    they're currently in has an active assignment, and if so claim it."""
    job_id = request.args.get("jobId", "").strip()
    claimer = request.args.get("accountId", "").strip()  # Roblox userId of the bot claiming
    if not job_id:
        return jsonify({"assigned": False})
    with lock:
        now = time.time()
        # Expire old assignments
        expired = [k for k, v in state["assignments"].items()
                   if (now - v.get("assigned_at", now)) > 300]
        for k in expired:
            state["assignments"].pop(k, None)

        # Find any assignment whose jobId matches
        for internal_id, assignment in list(state["assignments"].items()):
            if str(assignment.get("jobId", "")) == str(job_id):
                # Claim it: re-key under the Roblox userId so future lookups work
                if internal_id in ("any", "") and claimer:
                    state["assignments"].pop(internal_id, None)
                    assignment["robloxUserId"] = claimer
                    state["assignments"][claimer] = assignment
                    print(f"[assignment/by_job] claimed job {job_id[:8]} for {claimer}")
                return jsonify({"assigned": True, **assignment})
    return jsonify({"assigned": False})

@app.route("/api/assignment/complete", methods=["POST"])
def complete_assignment():
    """Called by auto account when it has joined the target's server and started."""
    d   = request.json or {}
    aid = str(d.get("accountId",""))
    with lock:
        # Try direct key first, then roblox_user_id fallback
        internal_id = aid if aid in state["assignments"] else None
        if not internal_id:
            for iid, acct in state["accounts"].items():
                if str(acct.get("roblox_user_id","")) == aid:
                    internal_id = iid; break
        a = state["assignments"].pop(internal_id, None) if internal_id else None
        # Always use internal_id to write back — aid may be Roblox UID, not the dict key
        real_id = internal_id or aid
        if real_id in state["accounts"]:
            state["accounts"][real_id]["status"] = "autoing"
            state["accounts"][real_id]["assigned_target"] = a.get("targetUserId") if a else None
    return jsonify({"ok":True})

@app.route("/api/target_lost", methods=["POST"])
def target_lost():
    """Called by auto account or scout when target leaves the server."""
    d   = request.json or {}
    uid = str(d.get("userId","")).strip()
    aid = str(d.get("accountId",""))
    with lock:
        if uid in state["targets"]:
            state["targets"][uid]["status"] = "searching"
            state["targets"][uid].pop("jobId",None)
            state["targets"][uid].pop("joinUrl",None)
        # Resolve internal_id from Roblox UID fallback (same as complete_assignment)
        internal_id = aid if aid in state["accounts"] else None
        if not internal_id:
            for iid, acct in state["accounts"].items():
                if str(acct.get("roblox_user_id","")) == aid:
                    internal_id = iid; break
        real_id = internal_id or aid
        if real_id in state["accounts"]:
            state["accounts"][real_id]["status"] = "idle" if state["accounts"][real_id].get("role")=="auto" else "scouting"
            state["accounts"][real_id]["assigned_target"] = None
        # Pop by both possible keys so it's always cleaned up
        state["assignments"].pop(real_id, None)
        state["assignments"].pop(aid, None)
    print(f"[~] target {uid} lost, account {aid} freed")
    return jsonify({"ok":True})

# ── Target API ─────────────────────────────────────────────────────────────────
@app.route("/api/targets")
def list_targets():
    with lock: return jsonify(state["targets"])

@app.route("/api/targets/add", methods=["POST"])
def add_target():
    uid = str((request.json or {}).get("userId","")).strip()
    if not uid: return jsonify({"ok":False,"error":"no userId"}), 400
    with lock:
        if uid not in state["targets"]:
            state["targets"][uid] = {"username":uid,"avatar":"","added":time.time(),"status":"searching"}
    def resolve():
        uname, av = roblox_lookup(uid)
        with lock:
            if uid in state["targets"]:
                state["targets"][uid]["username"] = uname
                state["targets"][uid]["avatar"]   = av
        print(f"[+] target: {uname} ({uid})")
    threading.Thread(target=resolve, daemon=True).start()
    return jsonify({"ok":True,"username":uid,"avatar":""})

@app.route("/api/targets/remove", methods=["POST"])
def remove_target():
    uid = str((request.json or {}).get("userId","")).strip()
    with lock: state["targets"].pop(uid, None)
    return jsonify({"ok":True})

@app.route("/api/targets/clear", methods=["POST"])
def clear_targets():
    with lock:
        count = len(state["targets"])
        state["targets"] = {}
    return jsonify({"ok":True,"cleared":count})

@app.route("/api/targets/import-friends", methods=["POST"])
def import_friends():
    uid = str((request.json or {}).get("userId","")).strip()
    if not uid: return jsonify({"ok":False,"error":"no userId"}), 400
    def do_scrape():
        added = []
        try:
            r = requests.get(f"https://friends.roblox.com/v1/users/{uid}/friends?limit=200", timeout=15)
            if r.status_code != 200:
                return added, f"Roblox API returned {r.status_code}"
            for friend in r.json().get("data",[]):
                fid  = str(friend["id"])
                name = friend.get("name", fid)
                av   = ""
                try:
                    tr = requests.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={fid}&size=150x150&format=Png", timeout=5)
                    av = tr.json()["data"][0]["imageUrl"]
                except: pass
                with lock:
                    if fid not in state["targets"]:
                        state["targets"][fid] = {"username":name,"avatar":av,"added":time.time(),"status":"searching"}
                    added.append({"id":fid,"username":name})
        except Exception as e:
            return added, str(e)
        return added, None
    added, err = do_scrape()
    if err and not added: return jsonify({"ok":False,"error":err}), 500
    print(f"[+] imported {len(added)} friends")
    return jsonify({"ok":True,"added":len(added),"friends":added})

@app.route("/api/history")
def get_history():
    with lock: return jsonify(state["history"])

@app.route("/api/scouts")
def get_scouts():
    now = time.time()
    with lock:
        result = {}
        for sid, s in state["accounts"].items():
            alive = (now - s.get("last_seen", 0)) < SCOUT_TIMEOUT
            result[sid] = {**s, "alive": alive, "has_assignment": sid in state["assignments"]}
        return jsonify(result)

@app.route("/api/vps/register", methods=["POST"])
def vps_register():
    """MultiRoblox calls this on startup to register itself and its accounts."""
    d      = request.json or {}
    vps_id = str(d.get("vpsId", "default")).strip()
    accts  = d.get("accounts", [])  # [{ id, username }]
    now    = time.time()
    _known_vps.add(vps_id)
    with lock:
        for a in accts:
            aid = str(a.get("id", "")).strip()
            if not aid: continue
            if aid not in state["accounts"]:
                state["accounts"][aid] = {
                    "username":        a.get("username", aid),
                    "roblox_user_id":  str(a.get("userId", "")),
                    "role":            "auto",
                    "status":          "idle",
                    "current_server":  None,
                    "player_count":    0,
                    "assigned_target": None,
                    "last_seen":       now,
                    "vps":             vps_id,
                    "multiroblox":     True,  # flag — offline timeout is relaxed
                }
            else:
                state["accounts"][aid]["last_seen"]       = now
                state["accounts"][aid]["vps"]             = vps_id
                state["accounts"][aid]["multiroblox"]     = True
                # Update userId if we now have it
                if a.get("userId"):
                    state["accounts"][aid]["roblox_user_id"] = str(a.get("userId", ""))
                # Bring back online if it went offline
                if state["accounts"][aid].get("status") == "offline":
                    state["accounts"][aid]["status"] = "idle"
    with _command_lock:
        _command_queues.setdefault(vps_id, [])
    print(f"[vps] registered {vps_id} with {len(accts)} account(s)")
    return jsonify({"ok": True, "vpsId": vps_id, "registered": len(accts)})

@app.route("/api/vps")
def get_vps():
    """Returns all known VPS nodes and their associated accounts + status."""
    now = time.time()
    with lock:
        # Group accounts by vps
        vps_map = {}
        for aid, acct in state["accounts"].items():
            vps_id = acct.get("vps") or "default"
            if vps_id not in vps_map:
                vps_map[vps_id] = {"vps_id": vps_id, "accounts": [], "online": 0, "total": 0}
            alive = (now - acct.get("last_seen", 0)) < SCOUT_TIMEOUT
            entry = {
                "account_id":      aid,
                "username":        acct.get("username", aid[:12]),
                "role":            acct.get("role", "scout"),
                "status":          acct.get("status", "offline"),
                "current_server":  acct.get("current_server", None),
                "player_count":    acct.get("player_count", None),
                "assigned_target": acct.get("assigned_target", None),
                "last_seen":       acct.get("last_seen", 0),
                "alive":           alive,
                "has_assignment":  aid in state["assignments"],
            }
            vps_map[vps_id]["accounts"].append(entry)
            vps_map[vps_id]["total"] += 1
            if alive:
                vps_map[vps_id]["online"] += 1
        # Also include VPS nodes that have a pending command queue but no accounts yet
        with _command_lock:
            for vps_id in _command_queues:
                if vps_id not in vps_map:
                    vps_map[vps_id] = {"vps_id": vps_id, "accounts": [], "online": 0, "total": 0}
        return jsonify(list(vps_map.values()))

@app.route("/api/settings", methods=["GET","POST"])
def api_settings():
    global DISCORD_WEBHOOK, PLACE_ID, SCOUT_TIMEOUT
    if request.method == "POST":
        d = request.json or {}
        if "webhook" in d: DISCORD_WEBHOOK = str(d["webhook"]).strip()
        if "placeId" in d:
            try: PLACE_ID = int(d["placeId"])
            except: pass
        if "timeout" in d:
            try: SCOUT_TIMEOUT = int(d["timeout"])
            except: pass
        return jsonify({"ok":True,"webhook":DISCORD_WEBHOOK,"placeId":PLACE_ID,"timeout":SCOUT_TIMEOUT})
    return jsonify({"webhook":DISCORD_WEBHOOK,"placeId":PLACE_ID,"timeout":SCOUT_TIMEOUT})

# ── MultiRoblox Command Queue ─────────────────────────────────────────────────
# MultiRoblox polls GET /api/commands?vps=<id> every few seconds.
# server.py queues commands here and MultiRoblox dequeues + executes them.
# Commands: { type: "launch", accountId, target } | { type: "kill", accountId } | { type: "kill-all" }

ALTGEN_API_KEY = os.environ.get("ALTGEN_API_KEY", "")  # set via Render env var

_command_queues = {}   # vps_id -> list of pending commands
_command_lock  = threading.Lock()

@app.route("/api/commands")
def get_commands():
    vps = request.args.get("vps", "default")
    with _command_lock:
        cmds = _command_queues.pop(vps, [])
    return jsonify({"ok": True, "commands": cmds})

@app.route("/api/commands/push", methods=["POST"])
def push_command():
    """Push a command to a specific VPS's MultiRoblox instance."""
    d   = request.json or {}
    vps = str(d.get("vps", "default"))
    cmd = d.get("command")
    if not cmd: return jsonify({"ok": False, "error": "no command"}), 400
    with _command_lock:
        if vps not in _command_queues:
            _command_queues[vps] = []
        _command_queues[vps].append(cmd)
    return jsonify({"ok": True})

@app.route("/api/commands/launch", methods=["POST"])
def queue_launch():
    """Queue a launch command for a specific account on a specific VPS."""
    d         = request.json or {}
    vps       = str(d.get("vps", "default"))
    account_id = str(d.get("accountId", ""))
    target    = str(d.get("target", ""))
    if not account_id: return jsonify({"ok": False, "error": "accountId required"}), 400
    cmd = {"type": "launch", "accountId": account_id, "target": target}
    with _command_lock:
        _command_queues.setdefault(vps, []).append(cmd)
    print(f"[cmd] queued launch {account_id} -> {target or '(lobby)'} for vps={vps}")
    return jsonify({"ok": True})

@app.route("/api/commands/report", methods=["POST"])
def report_command_result():
    """MultiRoblox reports back the result of a command."""
    d = request.json or {}
    vps = str(d.get("vps", "default"))
    cmd_type = d.get("type", "")
    account_id = str(d.get("accountId", "") or "")
    success = d.get("success", False)
    error = d.get("error", "")
    print(f"[cmd] result from {vps}: type={cmd_type} acct={account_id} ok={success} err={error}")
    if account_id and success:
        with lock:
            if account_id in state["accounts"]:
                if cmd_type == "launch":
                    state["accounts"][account_id]["status"] = "scouting"
                    # Stamp launch time so we can detect no-heartbeat within 90s
                    state["accounts"][account_id]["launched_at"] = time.time()
                    state["accounts"][account_id]["heartbeat_alerted"] = False
                elif cmd_type in ("kill", "kill-all"):
                    state["accounts"][account_id]["status"] = "offline"
    return jsonify({"ok": True})

# ── AltGen Account Generation ─────────────────────────────────────────────────
# Integrates altgen.me API for automatic Roblox account generation.
# Set ALTGEN_API_KEY environment variable on Render.

ALTGEN_BASE = "https://api.altgen.me/api/v1"

def _altgen_request(method, path, body=None):
    """Make an authenticated request to the AltGen API."""
    if not ALTGEN_API_KEY:
        return {"success": False, "error": {"code": "NO_KEY", "message": "ALTGEN_API_KEY not set"}}
    try:
        headers = {
            "Authorization": f"Bearer {ALTGEN_API_KEY}",
            "Content-Type":  "application/json",
        }
        if method == "GET":
            r = requests.get(ALTGEN_BASE + path, headers=headers, timeout=30)
        else:
            r = requests.post(ALTGEN_BASE + path, headers=headers, json=body, timeout=60)
        return r.json()
    except Exception as e:
        return {"success": False, "error": {"code": "REQUEST_FAILED", "message": str(e)}}

@app.route("/api/altgen/balance")
def altgen_balance():
    """Check AltGen token balance."""
    result = _altgen_request("GET", "/balance")
    return jsonify(result)

@app.route("/api/altgen/generate", methods=["POST"])
def altgen_generate():
    """
    Generate Roblox accounts via AltGen.
    body: { quantity: int (1-100) }
    Returns generated accounts and optionally auto-imports them.
    """
    d        = request.json or {}
    quantity = max(1, min(100, int(d.get("quantity", 1))))
    auto_import = d.get("autoImport", False)  # if true, add cookies to accounts state

    result = _altgen_request("POST", "/generate", {
        "type":     "ROBLOX_NORMAL",
        "quantity": quantity,
    })

    if result.get("success") and auto_import:
        accounts_data = result.get("data", {}).get("accounts", [])
        imported = []
        for acct in accounts_data:
            cookie   = acct.get("cookie") or acct.get("roblosecurity") or ""
            username = acct.get("username") or acct.get("user") or ""
            uid      = str(acct.get("userId") or acct.get("id") or "")
            if cookie:
                acct_id = f"gen_{uid or username or str(int(time.time()))}"
                with lock:
                    state["accounts"][acct_id] = {
                        "username":       username,
                        "roblox_user_id": uid,
                        "role":           "scout",
                        "status":         "idle",
                        "cookie":         cookie,  # stored for MultiRoblox to pick up
                        "current_server": None,
                        "player_count":   0,
                        "assigned_target":None,
                        "last_seen":      0,  # not yet connected
                        "vps":            "unassigned",
                        "generated":      True,
                    }
                imported.append({"id": acct_id, "username": username})
                print(f"[altgen] imported generated account: {username} ({uid})")
        result["imported"] = imported

    return jsonify(result)

@app.route("/api/altgen/pending")
def altgen_pending():
    """
    MultiRoblox calls this to get any newly generated accounts it should add.
    Returns accounts with cookies that haven't been picked up yet by a VPS.
    """
    with lock:
        pending = []
        for aid, acct in state["accounts"].items():
            if acct.get("generated") and acct.get("vps") == "unassigned" and acct.get("cookie"):
                pending.append({
                    "id":       aid,
                    "username": acct.get("username",""),
                    "cookie":   acct["cookie"],
                })
        return jsonify({"ok": True, "accounts": pending})

@app.route("/api/altgen/claim", methods=["POST"])
def altgen_claim():
    """MultiRoblox calls this after it picks up a generated account."""
    d   = request.json or {}
    aid = str(d.get("accountId",""))
    vps = str(d.get("vps","default"))
    with lock:
        if aid in state["accounts"]:
            state["accounts"][aid]["vps"]       = vps
            state["accounts"][aid]["last_seen"] = time.time()
            state["accounts"][aid]["status"]    = "idle"
            # clear cookie from server memory after handoff (security)
            state["accounts"][aid].pop("cookie", None)
    print(f"[altgen] account {aid} claimed by vps={vps}")
    return jsonify({"ok": True})



server_pool = []
server_pool_cursor = None
assigned = {}
visited_globally = set()  # tracks ALL servers given out to ANY scout
scan_status = {"running": False, "total": 0, "progress": 0}
_queue_claims = {}  # jobId -> scoutId: only one scout queues per server
_pool_lock = threading.Lock()  # protects server_pool and visited_globally

def scrape_servers_bg():
    global server_pool
    scan_status["running"] = True
    scan_status["progress"] = 0
    servers = []  # list of (job_id, player_count)
    cursor = None
    while True:
        url = f"https://games.roblox.com/v1/games/{PLACE_ID}/servers/Public?sortOrder=Desc&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code != 200:
                break
            data = r.json()
            for s in data.get("data", []):
                if "id" in s:
                    servers.append((s["id"], s.get("playing", 0)))
            scan_status["progress"] = len(servers)
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(0.3)
        except:
            break
    # sort biggest servers first — more players = higher chance target is in it
    servers.sort(key=lambda x: x[1], reverse=True)
    new_pool = [s[0] for s in servers]
    with _pool_lock:
        server_pool[:] = new_pool
        visited_globally.clear()
        for sid in assigned:
            assigned[sid] = set()
    scan_status["running"] = False
    scan_status["total"] = len(new_pool)
    print(f"[scan] done — {len(new_pool)} servers sorted biggest first")

threading.Thread(target=lambda: [scrape_servers_bg() or time.sleep(300) for _ in iter(int,1)], daemon=True).start()

@app.route("/api/scan", methods=["POST"])
def trigger_scan():
    if not scan_status["running"]:
        threading.Thread(target=scrape_servers_bg, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/queue/check")
def queue_check():
    """Scout checks if a server already has a queue claim from another scout."""
    job_id  = request.args.get("jobId", "")
    scout_id = request.args.get("scoutId", "")
    with lock:
        claim = _queue_claims.get(job_id)
    if claim and claim != scout_id:
        return jsonify({"queued": True, "queuedBy": claim})
    return jsonify({"queued": False})

@app.route("/api/queue/claim", methods=["POST"])
def queue_claim():
    """Scout claims the queue slot for a server (only one scout queues per server)."""
    d        = request.json or {}
    job_id   = str(d.get("jobId", "")).strip()
    scout_id = str(d.get("scoutId", "")).strip()
    if not job_id or not scout_id:
        return jsonify({"ok": False}), 400
    with lock:
        _queue_claims[job_id] = scout_id
    return jsonify({"ok": True})

@app.route("/api/queue/release", methods=["POST"])
def queue_release():
    """Scout releases its queue claim (teleport failed or joined successfully)."""
    d      = request.json or {}
    job_id = str(d.get("jobId", "")).strip()
    with lock:
        _queue_claims.pop(job_id, None)
    return jsonify({"ok": True})

@app.route("/api/scout/start", methods=["POST"])
def scout_start():
    """Queue a scout launch — opens Da Hood in a random server so scout.lua can run."""
    d          = request.json or {}
    vps        = str(d.get("vps", "")).strip()
    account_id = d.get("accountId")  # None = server picks an idle account

    # If no VPS specified, use first known registered VPS
    if not vps:
        if _known_vps:
            vps = next(iter(_known_vps))
        else:
            with _command_lock:
                known = list(_command_queues.keys())
            vps = known[0] if known else "vps-b-43"

    # If no specific account requested, pick one that isn't already scouting/active
    if not account_id:
        now = time.time()
        with lock:
            busy_statuses = {"scouting", "assigned", "autoing"}
            for aid, acct in state["accounts"].items():
                if acct.get("vps") != vps:
                    continue
                if acct.get("status") not in busy_statuses:
                    account_id = aid
                    break

        if not account_id:
            # All accounts on this VPS are already active
            with lock:
                active = sum(1 for a in state["accounts"].values()
                             if a.get("vps") == vps and a.get("status") in {"scouting","assigned","autoing"})
            print(f"[scout] all {active} account(s) on {vps} already active — skipping launch")
            return jsonify({"ok": False, "error": "all accounts already active", "vps": vps})

    cmd = {
        "type":      "launch",
        "accountId": account_id,
        "target":    f"https://www.roblox.com/games/{PLACE_ID}",
        "reason":    "scout_start",
    }
    with _command_lock:
        _command_queues.setdefault(vps, []).append(cmd)

    print(f"[scout] queued scout launch → vps={vps} acct={account_id or 'any'}")
    return jsonify({"ok": True, "vps": vps, "accountId": account_id})

@app.route("/api/scanstatus")
def get_scan_status():
    return jsonify({**scan_status, "queued": len(server_pool)})

@app.route("/api/nextserver")
def next_server():
    scout_id = request.args.get("scoutId", "unknown")
    with _pool_lock:
        if scout_id not in assigned:
            assigned[scout_id] = set()

        # find next server not yet visited by anyone
        for job_id in server_pool:
            if job_id not in visited_globally:
                visited_globally.add(job_id)
                assigned[scout_id].add(job_id)
                return jsonify({"jobId": job_id})

        # all servers exhausted — reset and rescan
        print(f"[scan] all {len(server_pool)} servers visited — resetting and rescanning")
        visited_globally.clear()
        for sid in assigned:
            assigned[sid] = set()

    if not scan_status["running"]:
        threading.Thread(target=scrape_servers_bg, daemon=True).start()

    with _pool_lock:
        if server_pool:
            job_id = server_pool[0]
            visited_globally.add(job_id)
            return jsonify({"jobId": job_id, "cycleReset": True})

    return jsonify({"jobId": None})

DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SNIPER — Dashboard</title>
  <meta name="description" content="Track players, manage scouts, and coordinate server sweeps." />
  
  
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&family=DM+Mono:wght@300;400;500&display=swap');

/* ── Variables ─────────────────────────────────────────── */
:root {
  --bg:           #010103;
  --bg-2:         #06070a;
  --bg-3:         #0e1017;
  --bg-4:         #151822;
  --fg:           #f8fafc;
  --fg-2:         #94a3b8;
  --fg-3:         #475569;
  --accent:       #00a2ff; /* Cyber blue primary accent */
  --accent-dim:   rgba(0, 162, 255, 0.08);
  --accent-glow:  rgba(0, 162, 255, 0.15);
  --gold:         #c9a96e; /* Classic brand gold highlight */
  --gold-dim:     rgba(201, 169, 110, 0.08);
  --gold-glow:    rgba(201, 169, 110, 0.15);
  --border:       rgba(255, 255, 255, 0.06);
  --border-h:     rgba(255, 255, 255, 0.12);

  --font-display: 'Space Grotesk', system-ui, -apple-system, sans-serif;
  --font-mono:    'DM Mono', 'JetBrains Mono', monospace;

  --radius-sm:    4px;
  --radius:       6px;
  --radius-lg:    12px;

  --ease-out:     cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out:  cubic-bezier(0.87, 0, 0.13, 1);

  --nav-h:        72px;
}

/* ── Reset ─────────────────────────────────────────────── */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  scroll-behavior: smooth;
  font-size: 16px;
}

body {
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font-display);
  font-weight: 300;
  line-height: 1.6;
  overflow-x: hidden;
  cursor: none;
  -webkit-font-smoothing: antialiased;
}

body.loading {
  overflow: hidden;
}

img {
  display: block;
  max-width: 100%;
}

a {
  color: inherit;
  text-decoration: none;
}

button {
  background: none;
  border: none;
  cursor: none;
  font-family: var(--font-display);
  color: inherit;
}

ul, ol { list-style: none; }

input, textarea, select {
  font-family: var(--font-display);
  background: none;
  border: none;
  outline: none;
  color: var(--fg);
}

/* ── Custom Cursor ─────────────────────────────────────── */
#cursor {
  position: fixed;
  top: 0; left: 0;
  pointer-events: none;
  z-index: 9999;
  mix-blend-mode: difference;
}

#cursor-dot {
  position: absolute;
  width: 8px; height: 8px;
  background: var(--fg);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: width 0.2s var(--ease-out), height 0.2s var(--ease-out), opacity 0.2s;
}

#cursor-ring {
  position: absolute;
  width: 40px; height: 40px;
  border: 1px solid var(--fg);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: width 0.35s var(--ease-out), height 0.35s var(--ease-out), opacity 0.35s;
}

body.cursor-hover #cursor-dot  { width: 0; height: 0; opacity: 0; }
body.cursor-hover #cursor-ring { width: 64px; height: 64px; }
body.cursor-text  #cursor-ring { width: 2px; height: 28px; border-radius: 1px; }
body.cursor-text  #cursor-dot  { opacity: 0; }

/* ── Page Loader ───────────────────────────────────────── */
#loader {
  position: fixed;
  inset: 0;
  background: var(--bg);
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 32px;
  transition: opacity 0.6s var(--ease-out), transform 0.6s var(--ease-out);
}

#loader.hidden {
  opacity: 0;
  pointer-events: none;
}

.loader-logo {
  font-family: var(--font-display);
  font-size: clamp(2rem, 5vw, 3.5rem);
  font-weight: 300;
  letter-spacing: 0.3em;
  text-transform: uppercase;
}

.loader-bar-wrap {
  width: 200px;
  height: 1px;
  background: var(--border-h);
  overflow: hidden;
}

.loader-bar {
  height: 100%;
  background: var(--accent);
  width: 0%;
  transition: width 0.05s linear;
}

.loader-num {
  font-size: 0.7rem;
  letter-spacing: 0.2em;
  color: var(--fg-2);
}

/* ── Navigation ────────────────────────────────────────── */
#nav {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: var(--nav-h);
  z-index: 100;
  display: flex;
  align-items: center;
  padding: 0 clamp(24px, 5vw, 80px);
  transition: background 0.4s, border-bottom 0.4s, backdrop-filter 0.4s;
}

#nav.scrolled {
  background: rgba(8,8,8,0.85);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
}

.nav-logo {
  font-family: var(--font-display);
  font-size: 1.4rem;
  font-weight: 500;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.nav-logo span { color: var(--accent); }

.nav-links {
  display: flex;
  align-items: center;
  gap: 40px;
  margin: 0 auto;
}

.nav-links li {
  display: flex;
  align-items: center;
}

.nav-links a {
  font-size: 0.72rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-2);
  position: relative;
  transition: color 0.3s;
}

.nav-links a::after {
  content: '';
  position: absolute;
  bottom: -4px; left: 0;
  width: 0; height: 1px;
  background: var(--accent);
  transition: width 0.3s var(--ease-out);
}

.nav-links a:hover { color: var(--fg); }
.nav-links a:hover::after { width: 100%; }
.nav-links a.active { color: var(--fg); }
.nav-links a.active::after { width: 100%; }

/* ── Nav Dropdown ──────────────────────────────────────── */
.nav-dropdown {
  position: relative;
}

.nav-dropdown > a {
  display: flex;
  align-items: center;
  gap: 5px;
}

.nav-dropdown > a::after { display: none; }

.nav-dropdown-chevron {
  display: inline-block;
  font-size: 0.5rem;
  transition: transform 0.25s var(--ease-out);
  color: var(--fg-3);
}

.nav-dropdown:hover .nav-dropdown-chevron { transform: rotate(180deg); }

.nav-dropdown-menu {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%) translateY(-4px);
  min-width: 180px;
  background: rgba(16,16,16,0.95);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-h);
  border-radius: var(--radius);
  padding: 16px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s var(--ease-out), transform 0.2s var(--ease-out);
  z-index: 200;
  /* Bridge the gap with a top pseudo-element so cursor doesn't leave hover zone */
}

.nav-dropdown-menu::before {
  content: '';
  position: absolute;
  top: -12px; left: 0; right: 0;
  height: 12px;
}

.nav-dropdown-menu::after {
  content: '';
  position: absolute;
  top: 6px; left: 50%;
  transform: translateX(-50%);
  width: 10px; height: 6px;
  background: var(--border-h);
  clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
}

.nav-dropdown:hover .nav-dropdown-menu {
  opacity: 1;
  pointer-events: all;
  transform: translateX(-50%) translateY(0);
}

.nav-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-size: 0.68rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-2);
  transition: background 0.2s, color 0.2s;
  white-space: nowrap;
}

.nav-dropdown-item:hover {
  background: var(--bg-3);
  color: var(--fg);
}

.nav-dropdown-item:hover::after { display: none; }

.nav-dropdown-icon {
  font-size: 0.9rem;
  color: var(--accent);
  width: 18px;
  text-align: center;
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 24px;
}

.nav-cart {
  position: relative;
  font-size: 0.72rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-2);
  transition: color 0.3s;
  padding: 4px 18px 4px 0;
}

.nav-cart:hover { color: var(--fg); }

.cart-badge {
  position: absolute;
  top: -6px; right: -14px;
  width: 16px; height: 16px;
  background: var(--accent);
  color: var(--bg);
  border-radius: 50%;
  font-size: 0.6rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
  opacity: 0;
  transform: scale(0);
  transition: opacity 0.3s, transform 0.3s var(--ease-out);
}

.cart-badge.show { opacity: 1; transform: scale(1); }

/* ── Layout Utilities ──────────────────────────────────── */
.container {
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 clamp(24px, 5vw, 80px);
}

.section { padding: clamp(80px, 10vw, 160px) 0; }

.section-label {
  font-size: 0.65rem;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-label::before {
  content: '';
  display: inline-block;
  width: 24px;
  height: 1px;
  background: var(--accent);
}

h1, h2, h3, h4, h5 {
  font-family: var(--font-display);
  font-weight: 300;
  line-height: 1.1;
}

.display-text {
  font-family: var(--font-display);
  font-size: clamp(3.5rem, 8vw, 9rem);
  font-weight: 300;
  line-height: 0.95;
  letter-spacing: -0.02em;
}

.display-text em {
  font-style: italic;
  color: var(--accent);
}

.body-text {
  font-size: 0.85rem;
  line-height: 1.8;
  color: var(--fg-2);
  max-width: 480px;
}

/* ── Dividers ──────────────────────────────────────────── */
.h-line {
  width: 100%;
  height: 1px;
  background: var(--border);
}

/* ── Buttons ───────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 14px 32px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  border-radius: var(--radius-sm);
  position: relative;
  overflow: hidden;
  transition: color 0.3s, transform 0.2s;
  white-space: nowrap;
  cursor: none;
}

.btn-primary {
  background: var(--fg);
  color: var(--bg);
  font-weight: 500;
}

.btn-primary::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--accent);
  transform: translateX(-101%);
  transition: transform 0.4s var(--ease-out);
}

.btn-primary:hover::before { transform: translateX(0); }
.btn-primary span { position: relative; z-index: 1; }

.btn-outline {
  border: 1px solid var(--border-h);
  color: var(--fg-2);
}

.btn-outline::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--bg-3);
  transform: translateX(-101%);
  transition: transform 0.4s var(--ease-out);
}

.btn-outline:hover { color: var(--fg); border-color: var(--border-h); }
.btn-outline:hover::before { transform: translateX(0); }
.btn-outline span { position: relative; z-index: 1; }

.btn-arrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--accent);
  transition: gap 0.3s var(--ease-out);
}

.btn-arrow:hover { gap: 16px; }

.btn-arrow .arrow {
  font-size: 1rem;
  transition: transform 0.3s var(--ease-out);
}

/* ── Marquee ───────────────────────────────────────────── */
.marquee-wrap {
  overflow: hidden;
  padding: 20px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: var(--bg-2);
}

.marquee-track {
  display: flex;
  gap: 0;
  width: max-content;
  animation: marquee 30s linear infinite;
}

.marquee-track:hover { animation-play-state: paused; }

.marquee-item {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 0 40px;
  font-size: 0.65rem;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--fg-3);
  white-space: nowrap;
}

.marquee-dot {
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}

/* ── Stats ─────────────────────────────────────────────── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.stat-card {
  background: var(--bg-2);
  padding: 48px 40px;
  text-align: center;
}

.stat-number {
  font-family: var(--font-display);
  font-size: clamp(2.5rem, 5vw, 4rem);
  font-weight: 300;
  color: var(--fg);
  display: block;
  line-height: 1;
  margin-bottom: 8px;
}

.stat-number .stat-accent { color: var(--accent); }

.stat-label {
  font-size: 0.65rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--fg-3);
}

/* ── Product Cards ─────────────────────────────────────── */
.product-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  position: relative;
  transition: border-color 0.3s, transform 0.4s var(--ease-out);
  transform-style: preserve-3d;
}

.product-card:hover { border-color: var(--border-h); }

.product-img-wrap {
  position: relative;
  aspect-ratio: 4/3;
  background: var(--bg-3);
  overflow: hidden;
}

.product-img-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.6s var(--ease-out);
}

.product-card:hover .product-img-wrap img {
  transform: scale(1.05);
}

.product-img-placeholder {
  width: 100%; height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--fg-3);
  font-size: 0.6rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

.product-badge {
  position: absolute;
  top: 16px; left: 16px;
  padding: 4px 10px;
  background: var(--accent);
  color: var(--bg);
  font-size: 0.55rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  font-weight: 500;
  border-radius: 2px;
}

.product-quick-add {
  position: absolute;
  bottom: 16px; left: 16px; right: 16px;
  padding: 12px;
  background: rgba(8,8,8,0.9);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-h);
  border-radius: var(--radius-sm);
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  text-align: center;
  color: var(--fg);
  transform: translateY(calc(100% + 16px));
  transition: transform 0.4s var(--ease-out);
}

.product-card:hover .product-quick-add { transform: translateY(0); }

.product-info {
  padding: 24px;
}

.product-category {
  font-size: 0.6rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--fg-3);
  margin-bottom: 8px;
}

.product-name {
  font-family: var(--font-display);
  font-size: 1.4rem;
  font-weight: 400;
  margin-bottom: 8px;
  line-height: 1.2;
}

.product-desc {
  font-size: 0.75rem;
  color: var(--fg-2);
  line-height: 1.6;
  margin-bottom: 20px;
}

.product-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.product-price {
  font-family: var(--font-display);
  font-size: 1.6rem;
  font-weight: 300;
}

.product-price .currency {
  font-size: 0.9rem;
  vertical-align: super;
  color: var(--fg-2);
}

/* ── Grid Layouts ──────────────────────────────────────── */
.products-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.products-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

/* ── Testimonial ───────────────────────────────────────── */
.testimonial-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 40px;
}

.testimonial-stars {
  color: var(--accent);
  font-size: 0.8rem;
  letter-spacing: 4px;
  margin-bottom: 20px;
}

.testimonial-text {
  font-family: var(--font-display);
  font-size: 1.1rem;
  font-weight: 300;
  line-height: 1.5;
  font-style: italic;
  margin-bottom: 24px;
  color: var(--fg);
}

.testimonial-author {
  display: flex;
  align-items: center;
  gap: 12px;
}

.testimonial-avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--bg-4);
  border: 1px solid var(--border-h);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  color: var(--fg-2);
}

.testimonial-name {
  font-size: 0.72rem;
  letter-spacing: 0.1em;
  margin-bottom: 2px;
}

.testimonial-role {
  font-size: 0.65rem;
  color: var(--fg-3);
}

/* ── Footer ────────────────────────────────────────────── */
footer {
  background: var(--bg-2);
  border-top: 1px solid var(--border);
  padding: 80px 0 40px;
}

.footer-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  gap: 60px;
  margin-bottom: 60px;
}

.footer-brand-name {
  font-family: var(--font-display);
  font-size: 1.8rem;
  font-weight: 300;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  margin-bottom: 16px;
}

.footer-brand-name span { color: var(--accent); }

.footer-desc {
  font-size: 0.75rem;
  line-height: 1.8;
  color: var(--fg-2);
  max-width: 280px;
  margin-bottom: 32px;
}

.newsletter-input-wrap {
  display: flex;
  border: 1px solid var(--border-h);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.newsletter-input {
  flex: 1;
  padding: 12px 16px;
  font-size: 0.72rem;
  background: transparent;
  color: var(--fg);
}

.newsletter-input::placeholder { color: var(--fg-3); }

.newsletter-btn {
  padding: 12px 20px;
  background: var(--accent);
  color: var(--bg);
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  font-weight: 500;
  transition: background 0.3s;
  cursor: none;
}

.newsletter-btn:hover { background: var(--fg); }

.footer-col-title {
  font-size: 0.65rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--fg-3);
  margin-bottom: 20px;
}

.footer-links { display: flex; flex-direction: column; gap: 10px; }

.footer-links a {
  font-size: 0.78rem;
  color: var(--fg-2);
  transition: color 0.2s, padding-left 0.2s var(--ease-out);
}

.footer-links a:hover { color: var(--fg); padding-left: 6px; }

.footer-bottom {
  padding-top: 32px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.footer-copy {
  font-size: 0.65rem;
  color: var(--fg-3);
  letter-spacing: 0.1em;
}

.footer-legal {
  display: flex;
  gap: 24px;
}

.footer-legal a {
  font-size: 0.65rem;
  color: var(--fg-3);
  letter-spacing: 0.1em;
  transition: color 0.2s;
}

.footer-legal a:hover { color: var(--fg-2); }

/* ── Reveal Animations ─────────────────────────────────── */
.reveal {
  opacity: 0;
  transform: translateY(32px);
  transition: opacity 0.8s var(--ease-out), transform 0.8s var(--ease-out);
}

.reveal.revealed {
  opacity: 1;
  transform: translateY(0);
}

.reveal-left {
  opacity: 0;
  transform: translateX(-32px);
  transition: opacity 0.8s var(--ease-out), transform 0.8s var(--ease-out);
}

.reveal-left.revealed { opacity: 1; transform: translateX(0); }

.reveal-right {
  opacity: 0;
  transform: translateX(32px);
  transition: opacity 0.8s var(--ease-out), transform 0.8s var(--ease-out);
}

.reveal-right.revealed { opacity: 1; transform: translateX(0); }

.reveal-scale {
  opacity: 0;
  transform: scale(0.92);
  transition: opacity 0.8s var(--ease-out), transform 0.8s var(--ease-out);
}

.reveal-scale.revealed { opacity: 1; transform: scale(1); }

[data-delay="1"] { transition-delay: 0.1s; }
[data-delay="2"] { transition-delay: 0.2s; }
[data-delay="3"] { transition-delay: 0.3s; }
[data-delay="4"] { transition-delay: 0.4s; }
[data-delay="5"] { transition-delay: 0.5s; }
[data-delay="6"] { transition-delay: 0.6s; }

/* ── Filter Bar ────────────────────────────────────────── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-btn {
  padding: 8px 20px;
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  border: 1px solid var(--border);
  border-radius: 100px;
  color: var(--fg-2);
  transition: all 0.25s;
  cursor: none;
}

.filter-btn:hover { border-color: var(--border-h); color: var(--fg); }
.filter-btn.active { background: var(--fg); color: var(--bg); border-color: var(--fg); }

/* ── Breadcrumb ────────────────────────────────────────── */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  color: var(--fg-3);
  margin-bottom: 40px;
}

.breadcrumb a { transition: color 0.2s; }
.breadcrumb a:hover { color: var(--fg); }
.breadcrumb .sep { color: var(--fg-3); }

/* ── Toast ─────────────────────────────────────────────── */
.toast {
  position: fixed;
  bottom: 32px; right: 32px;
  background: var(--bg-3);
  border: 1px solid var(--border-h);
  border-radius: var(--radius);
  padding: 16px 24px;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 9000;
  transform: translateY(100px);
  opacity: 0;
  transition: transform 0.4s var(--ease-out), opacity 0.4s;
  pointer-events: none;
}

.toast.show { transform: translateY(0); opacity: 1; }

.toast-icon {
  width: 20px; height: 20px;
  background: var(--accent);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  color: var(--bg);
  flex-shrink: 0;
}

/* ── Page Header ───────────────────────────────────────── */
.page-header {
  padding: calc(var(--nav-h) + 60px) 0 60px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 80px;
}

.page-header h1 {
  font-family: var(--font-display);
  font-size: clamp(2.5rem, 6vw, 5rem);
  font-weight: 300;
  margin-bottom: 12px;
}

.page-header p {
  font-size: 0.8rem;
  color: var(--fg-2);
}

/* ── Cart Page ─────────────────────────────────────────── */
.cart-layout {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 40px;
  align-items: start;
}

.cart-items { display: flex; flex-direction: column; gap: 1px; }

.cart-item {
  display: grid;
  grid-template-columns: 80px 1fr auto;
  gap: 20px;
  align-items: center;
  padding: 24px;
  background: var(--bg-2);
  border-radius: var(--radius);
  transition: background 0.2s;
}

.cart-item-img {
  width: 80px; height: 80px;
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.cart-item-img img { width: 100%; height: 100%; object-fit: cover; }

.cart-item-name {
  font-family: var(--font-display);
  font-size: 1.1rem;
  margin-bottom: 4px;
}

.cart-item-meta {
  font-size: 0.65rem;
  color: var(--fg-3);
  letter-spacing: 0.1em;
}

.qty-ctrl {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 12px;
}

.qty-btn {
  width: 28px; height: 28px;
  border: 1px solid var(--border-h);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  color: var(--fg-2);
  transition: all 0.2s;
  cursor: none;
}

.qty-btn:hover { border-color: var(--fg); color: var(--fg); }

.qty-num { font-size: 0.85rem; min-width: 20px; text-align: center; }

.cart-item-price {
  font-family: var(--font-display);
  font-size: 1.3rem;
  text-align: right;
}

.cart-remove {
  font-size: 0.6rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
  display: block;
  margin-top: 8px;
  text-align: right;
  transition: color 0.2s;
  cursor: none;
}

.cart-remove:hover { color: #c0392b; }

.order-summary {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px;
  position: sticky;
  top: calc(var(--nav-h) + 24px);
}

.summary-title {
  font-family: var(--font-display);
  font-size: 1.3rem;
  margin-bottom: 24px;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  font-size: 0.78rem;
  color: var(--fg-2);
  border-bottom: 1px solid var(--border);
}

.summary-row:last-of-type { border-bottom: none; }

.summary-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 0 24px;
}

.summary-total-label {
  font-size: 0.72rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.summary-total-price {
  font-family: var(--font-display);
  font-size: 2rem;
}

.checkout-btn {
  width: 100%;
  padding: 18px;
  background: var(--fg);
  color: var(--bg);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  font-weight: 500;
  border-radius: var(--radius-sm);
  transition: background 0.3s, transform 0.2s;
  cursor: none;
  text-align: center;
}

.checkout-btn:hover { background: var(--accent); transform: translateY(-1px); }

.secure-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
  font-size: 0.6rem;
  color: var(--fg-3);
  letter-spacing: 0.1em;
}

/* ── Empty State ───────────────────────────────────────── */
.empty-state {
  text-align: center;
  padding: 120px 20px;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 24px;
  opacity: 0.2;
}

.empty-title {
  font-family: var(--font-display);
  font-size: 2rem;
  margin-bottom: 12px;
}

.empty-desc {
  font-size: 0.78rem;
  color: var(--fg-2);
  margin-bottom: 32px;
}

/* ── Product Detail ────────────────────────────────────── */
.detail-layout {
  display: grid;
  grid-template-columns: 1fr 480px;
  gap: 80px;
  align-items: start;
}

.detail-gallery {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-main-img {
  aspect-ratio: 1;
  background: var(--bg-3);
  border-radius: var(--radius);
  overflow: hidden;
}

.detail-main-img img { width: 100%; height: 100%; object-fit: cover; }

.detail-thumbs {
  display: flex;
  gap: 10px;
}

.detail-thumb {
  width: 80px; height: 80px;
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  overflow: hidden;
  cursor: none;
  transition: border-color 0.2s;
}

.detail-thumb.active, .detail-thumb:hover { border-color: var(--accent); }
.detail-thumb img { width: 100%; height: 100%; object-fit: cover; }

.detail-info { padding-top: 8px; }

.detail-category {
  font-size: 0.6rem;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 12px;
}

.detail-name {
  font-family: var(--font-display);
  font-size: clamp(2rem, 4vw, 3rem);
  font-weight: 300;
  line-height: 1.1;
  margin-bottom: 16px;
}

.detail-price-wrap {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 24px 0;
}

.detail-price {
  font-family: var(--font-display);
  font-size: 2.5rem;
  font-weight: 300;
}

.detail-price-orig {
  font-size: 1.2rem;
  color: var(--fg-3);
  text-decoration: line-through;
}

.detail-desc {
  font-size: 0.8rem;
  line-height: 1.8;
  color: var(--fg-2);
  margin-bottom: 32px;
  padding-bottom: 32px;
  border-bottom: 1px solid var(--border);
}

.detail-options { margin-bottom: 24px; }

.option-label {
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
  margin-bottom: 10px;
}

.option-swatches {
  display: flex;
  gap: 8px;
}

.swatch {
  width: 32px; height: 32px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: none;
  transition: border-color 0.2s, transform 0.2s;
}

.swatch:hover { transform: scale(1.1); }
.swatch.active { border-color: var(--fg); }

.detail-add-btn {
  width: 100%;
  padding: 18px;
  background: var(--fg);
  color: var(--bg);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  font-weight: 500;
  border-radius: var(--radius-sm);
  transition: background 0.3s, transform 0.2s;
  cursor: none;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.detail-add-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--accent);
  transform: translateX(-101%);
  transition: transform 0.4s var(--ease-out);
}

.detail-add-btn:hover::before { transform: translateX(0); }
.detail-add-btn span { position: relative; z-index: 1; }

.detail-features {
  margin-top: 32px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.feature-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.75rem;
  color: var(--fg-2);
}

.feature-icon {
  width: 20px; height: 20px;
  border: 1px solid var(--border-h);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.55rem;
  color: var(--accent);
  flex-shrink: 0;
}

/* ── Tabs ──────────────────────────────────────────────── */
.tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 40px;
}

.tab-btn {
  padding: 14px 28px;
  font-size: 0.68rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.2s, border-color 0.2s;
  cursor: none;
}

.tab-btn.active { color: var(--fg); border-bottom-color: var(--accent); }

.tab-panel { display: none; }
.tab-panel.active { display: block; }

.spec-table { width: 100%; border-collapse: collapse; }
.spec-table tr { border-bottom: 1px solid var(--border); }
.spec-table td { padding: 14px 0; font-size: 0.78rem; vertical-align: top; }
.spec-table td:first-child { color: var(--fg-3); width: 40%; }

/* ── Responsive ────────────────────────────────────────── */
@media (max-width: 1024px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .footer-grid { grid-template-columns: 1fr 1fr; gap: 40px; }
  .products-grid-3 { grid-template-columns: repeat(2, 1fr); }
  .cart-layout { grid-template-columns: 1fr; }
  .detail-layout { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .nav-links { display: none; }
  .products-grid-3 { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: 1fr 1fr; }
  .footer-grid { grid-template-columns: 1fr; }
}

/* ── Mobile Nav ────────────────────────────────────────── */
.nav-hamburger {
  display: none;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  width: 36px;
  height: 36px;
  padding: 6px;
  cursor: none;
  margin-left: auto;
}

.nav-hamburger span {
  display: block;
  height: 1px;
  background: var(--fg);
  transition: transform 0.35s var(--ease-out), opacity 0.25s, width 0.3s var(--ease-out);
  transform-origin: center;
}

.nav-hamburger span:nth-child(3) { width: 60%; }

.nav-hamburger.open span:nth-child(1) { transform: translateY(6px) rotate(45deg); }
.nav-hamburger.open span:nth-child(2) { opacity: 0; }
.nav-hamburger.open span:nth-child(3) { transform: translateY(-6px) rotate(-45deg); width: 100%; }

.mobile-menu {
  position: fixed;
  inset: 0;
  background: var(--bg);
  z-index: 99;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(32px, 8vw, 80px);
  transform: translateX(100%);
  transition: transform 0.5s var(--ease-out);
  pointer-events: none;
}

.mobile-menu.open {
  transform: translateX(0);
  pointer-events: all;
}

.mobile-menu-links {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 48px;
}

.mobile-menu-link {
  font-family: var(--font-display);
  font-size: clamp(2.2rem, 8vw, 3.5rem);
  font-weight: 300;
  color: var(--fg-2);
  line-height: 1.2;
  transition: color 0.2s, padding-left 0.3s var(--ease-out);
  display: block;
  border-bottom: 1px solid var(--border);
  padding: 16px 0;
}

.mobile-menu-link:hover { color: var(--fg); padding-left: 12px; }

.mobile-menu-sub {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-left: 20px;
  margin-top: -4px;
  margin-bottom: 4px;
}

.mobile-menu-sub a {
  font-size: 0.75rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
  padding: 8px 0;
  transition: color 0.2s;
  border-bottom: 1px solid var(--border);
}

.mobile-menu-sub a:hover { color: var(--accent); }

.mobile-menu-footer {
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
}

@media (max-width: 768px) {
  .nav-links { display: none !important; }
  .nav-hamburger { display: flex; }
}

/* ── Search Bar ────────────────────────────────────────── */
.search-wrap {
  position: relative;
  max-width: 360px;
}

.search-input {
  width: 100%;
  padding: 10px 40px 10px 16px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 100px;
  font-size: 0.72rem;
  letter-spacing: 0.05em;
  color: var(--fg);
  transition: border-color 0.2s, background 0.2s;
}

.search-input::placeholder { color: var(--fg-3); }
.search-input:focus { border-color: var(--border-h); background: var(--bg-3); outline: none; }

.search-icon {
  position: absolute;
  right: 14px; top: 50%;
  transform: translateY(-50%);
  font-size: 0.8rem;
  color: var(--fg-3);
  pointer-events: none;
}

.no-results {
  grid-column: 1 / -1;
  text-align: center;
  padding: 80px 20px;
}

.no-results-title {
  font-family: var(--font-display);
  font-size: 1.5rem;
  margin-bottom: 8px;
}

.no-results-desc { font-size: 0.78rem; color: var(--fg-2); }

/* ── Qty Selector ──────────────────────────────────────── */
.qty-selector {
  display: flex;
  align-items: center;
  gap: 0;
  border: 1px solid var(--border-h);
  border-radius: var(--radius-sm);
  overflow: hidden;
  width: fit-content;
}

.qty-selector-btn {
  width: 40px; height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  color: var(--fg-2);
  background: var(--bg-3);
  transition: background 0.2s, color 0.2s;
  cursor: none;
  border: none;
  font-family: var(--font-mono);
}

.qty-selector-btn:hover { background: var(--bg-4); color: var(--fg); }

.qty-selector-num {
  width: 48px;
  text-align: center;
  font-size: 0.85rem;
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Sale badge variant ────────────────────────────────── */
.product-badge.sale { background: #c0392b; }
.product-badge.new  { background: var(--accent); }
.product-badge.limited { background: var(--fg-3); }

/* ── Card sale price ───────────────────────────────────── */
.product-price-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.product-price-orig {
  font-size: 0.75rem;
  color: var(--fg-3);
  text-decoration: line-through;
  line-height: 1;
}

/* ── Checkout Page ─────────────────────────────────────── */
.checkout-layout {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 40px;
  align-items: start;
}

.checkout-section {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px;
  margin-bottom: 20px;
  position: relative;
  z-index: 1;
  overflow: visible;
}

.checkout-section:focus-within {
  z-index: 10;
}

.checkout-section-title {
  font-family: var(--font-display);
  font-size: 1.2rem;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 12px;
}

.checkout-step-num {
  width: 24px; height: 24px;
  background: var(--accent);
  color: var(--bg);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  font-weight: 500;
  flex-shrink: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-grid.full { grid-template-columns: 1fr; }

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field.span-2 { grid-column: span 2; }

.form-label {
  font-size: 0.62rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
}

.form-input {
  padding: 12px 14px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
  color: var(--fg);
  font-family: var(--font-mono);
  transition: border-color 0.2s;
}

.form-input:focus { border-color: var(--accent); outline: none; }
.form-input::placeholder { color: var(--fg-3); }

.form-select {
  padding: 12px 14px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
  color: var(--fg);
  font-family: var(--font-mono);
  appearance: none;
  cursor: none;
}

.payment-method-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 20px;
}

.payment-method {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  text-align: center;
  cursor: none;
  transition: border-color 0.2s, background 0.2s;
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--fg-2);
}

.payment-method.active {
  border-color: var(--accent);
  background: var(--accent-dim);
  color: var(--fg);
}

.payment-method-icon { font-size: 1.2rem; margin-bottom: 6px; }

.checkout-summary-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.checkout-summary-img {
  width: 52px; height: 52px;
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  color: var(--fg-3);
  flex-shrink: 0;
}

.checkout-summary-name {
  font-family: var(--font-display);
  font-size: 0.95rem;
  flex: 1;
}

.checkout-summary-meta {
  font-size: 0.6rem;
  color: var(--fg-3);
  margin-top: 2px;
}

.checkout-summary-price {
  font-family: var(--font-display);
  font-size: 1rem;
  flex-shrink: 0;
}

/* ── Confirmation Page ─────────────────────────────────── */
.confirmation-wrap {
  min-height: 80vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 80px 20px;
}

.confirmation-icon {
  width: 80px; height: 80px;
  border: 1px solid var(--accent);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.8rem;
  color: var(--accent);
  margin: 0 auto 32px;
  animation: scaleIn 0.6s var(--ease-out) both;
}

.confirmation-title {
  font-family: var(--font-display);
  font-size: clamp(2rem, 5vw, 4rem);
  font-weight: 300;
  margin-bottom: 16px;
}

.confirmation-desc {
  font-size: 0.82rem;
  line-height: 1.8;
  color: var(--fg-2);
  max-width: 480px;
  margin: 0 auto 40px;
}

.order-ref {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  color: var(--accent);
  padding: 8px 20px;
  border: 1px solid var(--accent-glow);
  border-radius: 100px;
  margin-bottom: 40px;
  display: inline-block;
}

.confirmation-steps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  max-width: 600px;
  margin: 40px auto;
  text-align: left;
}

.confirmation-step {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
}

.confirmation-step-num {
  font-size: 0.6rem;
  letter-spacing: 0.2em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.confirmation-step-title {
  font-family: var(--font-display);
  font-size: 1rem;
  margin-bottom: 4px;
}

.confirmation-step-desc {
  font-size: 0.7rem;
  color: var(--fg-3);
  line-height: 1.6;
}

/* ── 404 Page ──────────────────────────────────────────── */
.not-found-wrap {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
  position: relative;
}

.not-found-num {
  font-family: var(--font-display);
  font-size: clamp(8rem, 20vw, 18rem);
  font-weight: 300;
  line-height: 1;
  color: var(--bg-3);
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  user-select: none;
  pointer-events: none;
  z-index: 0;
}

.not-found-content {
  position: relative;
  z-index: 1;
}

.not-found-title {
  font-family: var(--font-display);
  font-size: clamp(1.8rem, 4vw, 3rem);
  font-weight: 300;
  margin-bottom: 12px;
}

.not-found-desc {
  font-size: 0.8rem;
  color: var(--fg-2);
  margin-bottom: 40px;
}

/* ── Clear cart ────────────────────────────────────────── */
.clear-cart-btn {
  font-size: 0.62rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-3);
  transition: color 0.2s;
  cursor: none;
  padding: 4px 0;
}

.clear-cart-btn:hover { color: #c0392b; }

@media (max-width: 768px) {
  .checkout-layout { grid-template-columns: 1fr; }
  .form-grid { grid-template-columns: 1fr; }
  .form-field.span-2 { grid-column: span 1; }
  .payment-method-grid { grid-template-columns: 1fr 1fr; }
  .confirmation-steps { grid-template-columns: 1fr; }
}

/* ── Custom Select ─────────────────────────────────────── */
.custom-select {
  position: relative;
  user-select: none;
}

.custom-select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
  color: var(--fg);
  font-family: var(--font-mono);
  cursor: none;
  transition: border-color 0.2s;
}

.custom-select.open .custom-select-trigger,
.custom-select-trigger:hover {
  border-color: var(--border-h);
}

.custom-select.open .custom-select-trigger {
  border-color: var(--accent);
  border-bottom-color: transparent;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}

.custom-select-arrow {
  font-size: 0.55rem;
  color: var(--fg-3);
  transition: transform 0.25s var(--ease-out);
  flex-shrink: 0;
  margin-left: 8px;
}

.custom-select.open .custom-select-arrow {
  transform: rotate(180deg);
  color: var(--accent);
}

.custom-select-dropdown {
  position: absolute;
  top: 100%;
  left: 0; right: 0;
  background: var(--bg-3);
  border: 1px solid var(--accent);
  border-top: none;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
  max-height: 240px;
  overflow-y: auto;
  z-index: 1000;
  opacity: 0;
  transform: translateY(-4px);
  pointer-events: none;
  transition: opacity 0.2s var(--ease-out), transform 0.2s var(--ease-out);
}

.custom-select.open .custom-select-dropdown {
  opacity: 1;
  transform: translateY(0);
  pointer-events: all;
}

/* Scrollbar */
.custom-select-dropdown::-webkit-scrollbar { width: 4px; }
.custom-select-dropdown::-webkit-scrollbar-track { background: transparent; }
.custom-select-dropdown::-webkit-scrollbar-thumb { background: var(--border-h); border-radius: 2px; }

.custom-select-option {
  padding: 11px 14px;
  font-size: 0.78rem;
  font-family: var(--font-mono);
  color: var(--fg-2);
  cursor: none;
  transition: background 0.15s, color 0.15s;
  border-bottom: 1px solid var(--border);
}

.custom-select-option:last-child { border-bottom: none; }

.custom-select-option:hover {
  background: var(--bg-4);
  color: var(--fg);
}

.custom-select-option.selected {
  color: var(--accent);
  background: var(--accent-dim);
}

/* ── Search Overlay ────────────────────────────────────── */
.search-overlay {
  position: fixed;
  inset: 0;
  background: rgba(8,8,8,0.97);
  z-index: 500;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 120px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.35s var(--ease-out);
}

.search-overlay.open {
  opacity: 1;
  pointer-events: all;
}

.search-overlay-inner {
  width: 100%;
  max-width: 720px;
  padding: 0 clamp(24px, 5vw, 80px);
}

.search-overlay-label {
  font-size: 0.6rem;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--fg-3);
  margin-bottom: 20px;
}

.search-overlay-input-wrap {
  display: flex;
  align-items: center;
  gap: 20px;
  border-bottom: 1px solid var(--border-h);
  padding-bottom: 20px;
  margin-bottom: 40px;
}

.search-overlay-input {
  flex: 1;
  font-family: var(--font-display);
  font-size: clamp(1.8rem, 5vw, 3.5rem);
  font-weight: 300;
  color: var(--fg);
  background: none;
  border: none;
  outline: none;
}

.search-overlay-input::placeholder {
  color: var(--fg-3);
}

.search-overlay-close {
  font-size: 1.5rem;
  color: var(--fg-3);
  cursor: none;
  transition: color 0.2s;
  flex-shrink: 0;
  background: none;
  border: none;
  font-family: var(--font-mono);
  line-height: 1;
}

.search-overlay-close:hover { color: var(--fg); }

.search-overlay-results {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.search-overlay-hint {
  font-size: 0.72rem;
  color: var(--fg-3);
  text-align: center;
  padding: 40px 0;
}

.search-result-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.2s;
  cursor: none;
}

.search-result-item:hover { border-color: var(--border-h); }

.search-result-img {
  width: 48px; height: 48px;
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  color: var(--fg-3);
  flex-shrink: 0;
}

.search-result-name {
  font-family: var(--font-display);
  font-size: 0.95rem;
  margin-bottom: 2px;
}

.search-result-price {
  font-size: 0.7rem;
  color: var(--accent);
}

.nav-search-btn {
  background: none;
  border: none;
  cursor: none;
  font-size: 0.75rem;
  color: var(--fg-2);
  transition: color 0.2s;
  padding: 4px;
  display: flex;
  align-items: center;
}

.nav-search-btn:hover { color: var(--fg); }

/* ── Form Validation ───────────────────────────────────── */
.form-input.error { border-color: #c0392b; }
.form-input.valid { border-color: #27ae60; }

.form-error-msg {
  font-size: 0.62rem;
  color: #c0392b;
  margin-top: 4px;
  letter-spacing: 0.05em;
  display: none;
}

.form-field.has-error .form-error-msg { display: block; }
.form-field.has-error .form-input { border-color: #c0392b; }

/* ── Skeleton Loading ──────────────────────────────────── */
.skeleton-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.skeleton-img {
  aspect-ratio: 4/3;
  background: var(--bg-3);
  animation: shimmer 1.4s ease-in-out infinite;
  background: linear-gradient(90deg, var(--bg-3) 0%, var(--bg-4) 50%, var(--bg-3) 100%);
  background-size: 200% 100%;
}

.skeleton-body { padding: 24px; }

.skeleton-line {
  height: 10px;
  border-radius: 4px;
  margin-bottom: 10px;
  animation: shimmer 1.4s ease-in-out infinite;
  background: linear-gradient(90deg, var(--bg-3) 0%, var(--bg-4) 50%, var(--bg-3) 100%);
  background-size: 200% 100%;
}

.skeleton-line.short { width: 40%; }
.skeleton-line.medium { width: 70%; }
.skeleton-line.full { width: 100%; }
.skeleton-line.tall { height: 16px; margin-bottom: 16px; }

/* ── Newsletter success ────────────────────────────────── */
.newsletter-success {
  display: none;
  align-items: center;
  gap: 10px;
  font-size: 0.72rem;
  color: var(--accent);
  padding: 12px 0;
}

.newsletter-success.show { display: flex; }

/* ── Mobile product card always show add btn ───────────── */
@media (hover: none) {
  .product-quick-add {
    transform: translateY(0) !important;
  }
}

/* ── Hero product showcase ─────────────────────────────── */
.hero-showcase {
  position: absolute;
  right: clamp(24px, 5vw, 80px);
  top: 50%;
  transform: translateY(-50%);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: clamp(260px, 30vw, 420px);
  opacity: 0;
  transition: opacity 0.8s 1s var(--ease-out);
}

.hero-showcase.visible { opacity: 1; }

.hero-showcase-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.3s, transform 0.4s var(--ease-out);
  cursor: none;
}

.hero-showcase-card:hover {
  border-color: var(--border-h);
  transform: translateY(-4px);
}

.hero-showcase-card:nth-child(2) { margin-top: 24px; }
.hero-showcase-card:nth-child(4) { margin-top: -24px; }

.hero-showcase-icon {
  font-size: 1.4rem;
  color: var(--fg-3);
  margin-bottom: 4px;
}

.hero-showcase-name {
  font-family: var(--font-display);
  font-size: 0.9rem;
  font-weight: 400;
  line-height: 1.2;
}

.hero-showcase-price {
  font-size: 0.7rem;
  color: var(--accent);
  letter-spacing: 0.05em;
}

@media (max-width: 1024px) {
  .hero-showcase { display: none; }
}

/* ── Journal Page ──────────────────────────────────────── */
.journal-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.journal-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 0.3s;
  cursor: none;
}

.journal-card:hover { border-color: var(--border-h); }

.journal-card-img {
  aspect-ratio: 16/9;
  background: var(--bg-3);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.journal-card-img svg {
  width: 100%; height: 100%;
  opacity: 0.6;
  transition: transform 0.6s var(--ease-out);
}

.journal-card:hover .journal-card-img svg { transform: scale(1.05); }

.journal-card-body { padding: 28px; }

.journal-tag {
  font-size: 0.58rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 10px;
}

.journal-card-title {
  font-family: var(--font-display);
  font-size: 1.3rem;
  font-weight: 400;
  line-height: 1.2;
  margin-bottom: 10px;
  transition: color 0.2s;
}

.journal-card:hover .journal-card-title { color: var(--accent); }

.journal-card-excerpt {
  font-size: 0.75rem;
  line-height: 1.8;
  color: var(--fg-2);
  margin-bottom: 20px;
}

.journal-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.62rem;
  color: var(--fg-3);
  letter-spacing: 0.1em;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.journal-featured {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

.journal-featured-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  display: grid;
  grid-template-columns: 1fr 1fr;
  transition: border-color 0.3s;
  cursor: none;
  grid-column: span 2;
}

.journal-featured-card:hover { border-color: var(--border-h); }

.journal-featured-img {
  background: var(--bg-3);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  min-height: 320px;
}

.journal-featured-img svg { width: 100%; height: 100%; opacity: 0.5; }

.journal-featured-body {
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.journal-featured-title {
  font-family: var(--font-display);
  font-size: clamp(1.5rem, 3vw, 2.2rem);
  font-weight: 300;
  line-height: 1.2;
  margin-bottom: 16px;
}

.journal-featured-card:hover .journal-featured-title { color: var(--accent); }

/* ── About Page ────────────────────────────────────────── */
.about-hero {
  min-height: 60vh;
  display: flex;
  align-items: flex-end;
  padding-top: var(--nav-h);
  padding-bottom: 80px;
  position: relative;
  overflow: hidden;
  border-bottom: 1px solid var(--border);
}

.about-values {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-top: 80px;
}

.about-value-card {
  background: var(--bg-2);
  padding: 40px 32px;
}

.about-value-num {
  font-size: 0.6rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 16px;
}

.about-value-title {
  font-family: var(--font-display);
  font-size: 1.3rem;
  font-weight: 400;
  margin-bottom: 10px;
}

.about-value-desc {
  font-size: 0.75rem;
  line-height: 1.8;
  color: var(--fg-2);
}

.about-team-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.team-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.team-card-img {
  aspect-ratio: 1;
  background: var(--bg-3);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.team-card-img svg { width: 100%; height: 100%; opacity: 0.3; }

.team-card-body { padding: 24px; }

.team-name {
  font-family: var(--font-display);
  font-size: 1.2rem;
  margin-bottom: 4px;
}

.team-role {
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 12px;
}

.team-bio {
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--fg-2);
}

.about-manifesto {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: clamp(40px, 6vw, 80px);
  text-align: center;
}

.manifesto-text {
  font-family: var(--font-display);
  font-size: clamp(1.5rem, 4vw, 3rem);
  font-weight: 300;
  line-height: 1.3;
  max-width: 800px;
  margin: 0 auto 32px;
}

.manifesto-text em { color: var(--accent); font-style: italic; }

@media (max-width: 1024px) {
  .about-values { grid-template-columns: repeat(2, 1fr); }
  .about-team-grid { grid-template-columns: repeat(2, 1fr); }
  .journal-featured-card { grid-template-columns: 1fr; grid-column: span 1; }
  .journal-featured-img { min-height: 200px; }
  .journal-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .about-values { grid-template-columns: 1fr; }
  .about-team-grid { grid-template-columns: 1fr; }
  .journal-grid { grid-template-columns: 1fr; }
  .journal-featured { grid-template-columns: 1fr; }
  .journal-featured-card { grid-column: span 1; grid-template-columns: 1fr; }
  .search-overlay-results { grid-template-columns: 1fr 1fr; }
}

/* ── Shake animation for validation ───────────────────── */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20%       { transform: translateX(-6px); }
  40%       { transform: translateX(6px); }
  60%       { transform: translateX(-4px); }
  80%       { transform: translateX(4px); }
}

/* ── Sniper Dashboard Specific Overlays & Layouts ────────────────────── */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 40px;
}

@media (max-width: 900px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

.dashboard-stat-card {
  background: var(--bg-2);
  border: 1px solid rgba(0, 162, 255, 0.15);
  box-shadow: 0 0 15px rgba(0, 162, 255, 0.04), inset 0 0 15px rgba(0, 162, 255, 0.02);
  border-radius: var(--radius);
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.dashboard-stat-card:hover {
  border-color: rgba(0, 162, 255, 0.4);
  box-shadow: 0 0 25px rgba(0, 162, 255, 0.15), inset 0 0 20px rgba(0, 162, 255, 0.04);
}

.dashboard-stat-label {
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--fg-2);
}

.dashboard-stat-value {
  font-size: 3rem;
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--fg);
  line-height: 1;
}

/* Badge System */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 0.65rem;
  text-transform: uppercase;
  font-family: var(--font-mono);
  font-weight: 500;
  letter-spacing: 0.05em;
}

.badge-searching {
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid rgba(0, 162, 255, 0.2);
}

.badge-searching::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: blink 1.5s infinite;
}

.badge-located {
  background: var(--gold-dim);
  color: var(--gold);
  border: 1px solid rgba(201, 169, 110, 0.2);
}

.badge-located::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--gold);
}

.badge-offline {
  background: rgba(255, 255, 255, 0.05);
  color: var(--fg-3);
  border: 1px solid var(--border);
}

.badge-offline::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--fg-3);
}

@keyframes blink {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

/* Scout Cards Grid */
.scout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.scout-card {
  background: var(--bg-2);
  border: 1px solid rgba(0, 162, 255, 0.15);
  box-shadow: 0 0 15px rgba(0, 162, 255, 0.04), inset 0 0 15px rgba(0, 162, 255, 0.02);
  border-radius: var(--radius);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.scout-card:hover {
  border-color: rgba(0, 162, 255, 0.4);
  box-shadow: 0 0 25px rgba(0, 162, 255, 0.15), inset 0 0 20px rgba(0, 162, 255, 0.04);
}

.scout-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.scout-id {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  color: var(--fg);
  font-weight: 500;
}

.scout-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.scout-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
}

.scout-lbl {
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.scout-val {
  color: var(--fg-2);
  font-family: var(--font-mono);
}

/* Forms & Inputs for Dashboard */
.dash-form-row {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}

.dash-input {
  flex: 1;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px 16px;
  font-size: 0.8rem;
  color: var(--fg);
  font-family: var(--font-mono);
  transition: border-color 0.2s;
}

.dash-input:focus {
  border-color: var(--border-h);
}

/* Radar Scan Widget */
.radar-box {
  position: relative;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  border: 1px solid var(--border-h);
  overflow: hidden;
  margin: 0 auto 20px;
}

.radar-sweep {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  background: conic-gradient(from 0deg, transparent 50%, var(--accent-glow) 100%);
  transform-origin: 0% 0%;
  animation: radar-spin 3s linear infinite;
  border-radius: 50%;
}

@keyframes radar-spin {
  0% { transform: translate(-50%, -50%) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg); }
}

/* Table Style for Timelines */
.intel-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 20px;
}

.intel-table th, .intel-table td {
  padding: 16px 20px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

.intel-table th {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--fg-3);
  font-weight: 500;
}

.intel-table td {
  font-size: 0.78rem;
  color: var(--fg-2);
}

.intel-table tr {
  transition: background 0.2s;
}

.intel-table tr:hover {
  background: var(--bg-2);
}

.intel-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-3);
  border: 1px solid var(--border);
}

/* ── Container Glow Overrides ─────────────────────────── */
.dashboard-stat-card, .scout-card, .about-manifesto, .product-card {
  position: relative;
  overflow: hidden;
  background: var(--bg-2) !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
  transition: border-color 0.3s, box-shadow 0.3s, transform 0.6s var(--ease-out) !important;
}

.dashboard-stat-card::before, .scout-card::before, .about-manifesto::before, .product-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(280px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), rgba(0, 162, 255, 0.15), transparent 80%);
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.4s ease;
  z-index: 0;
}

/* Force inner content above glow overlay */
.dashboard-stat-card > *, .scout-card > *, .about-manifesto > *, .product-card > * {
  position: relative;
  z-index: 1;
}

.dashboard-stat-card:hover, .scout-card:hover, .about-manifesto:hover, .product-card:hover {
  border-color: rgba(0, 162, 255, 0.45) !important;
  box-shadow: 0 0 35px rgba(0, 162, 255, 0.18), inset 0 0 30px rgba(0, 162, 255, 0.2) !important;
}

.dashboard-stat-card:hover::before, .scout-card:hover::before, .about-manifesto:hover::before, .product-card:hover::before {
  opacity: 1;
}
/* ── Keyframes ─────────────────────────────────────────── */

@keyframes marquee {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(40px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-20px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.9); }
  to   { opacity: 1; transform: scale(1); }
}

@keyframes textReveal {
  from { clip-path: inset(0 100% 0 0); }
  to   { clip-path: inset(0 0% 0 0); }
}

@keyframes lineGrow {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-10px); }
}

@keyframes shimmer {
  0%   { background-position: -200% center; }
  100% { background-position:  200% center; }
}

@keyframes borderPulse {
  0%, 100% { border-color: var(--border); }
  50%       { border-color: var(--accent-glow); }
}

@keyframes glitch {
  0%   { clip-path: inset(20% 0 60% 0); transform: translate(-4px, 0); }
  25%  { clip-path: inset(40% 0 20% 0); transform: translate(4px, 0); }
  50%  { clip-path: inset(10% 0 70% 0); transform: translate(-2px, 0); }
  75%  { clip-path: inset(60% 0 10% 0); transform: translate(2px, 0); }
  100% { clip-path: inset(20% 0 60% 0); transform: translate(0, 0); }
}

@keyframes heroLineIn {
  from { transform: scaleX(0); transform-origin: left; }
  to   { transform: scaleX(1); transform-origin: left; }
}

/* ── Hero Entrance Sequence ────────────────────────────── */
.hero-line {
  overflow: hidden;
}

.hero-line-inner {
  display: block;
  transform: translateY(110%);
  transition: transform 1s var(--ease-out);
}

.hero-line-inner.in { transform: translateY(0); }

/* Stagger children for hero text lines */
.hero-line:nth-child(2) .hero-line-inner { transition-delay: 0.1s; }
.hero-line:nth-child(3) .hero-line-inner { transition-delay: 0.2s; }
.hero-line:nth-child(4) .hero-line-inner { transition-delay: 0.3s; }

/* ── Shimmer Effect ────────────────────────────────────── */
.shimmer {
  background: linear-gradient(
    90deg,
    var(--bg-3) 0%,
    var(--bg-4) 50%,
    var(--bg-3) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 2s linear infinite;
}

/* ── Floating Label Decor ──────────────────────────────── */
.float-label {
  animation: float 6s ease-in-out infinite;
}

/* ── Noise Overlay ─────────────────────────────────────── */
.noise-overlay {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 256px;
}

/* ── Glow Effect ───────────────────────────────────────── */
.glow {
  position: relative;
}

.glow::after {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  background: linear-gradient(135deg, var(--accent-glow), transparent, var(--accent-glow));
  opacity: 0;
  transition: opacity 0.4s;
  z-index: -1;
  filter: blur(8px);
}

.glow:hover::after { opacity: 1; }

/* ── Scroll Progress ───────────────────────────────────── */
#scroll-progress {
  position: fixed;
  top: 0; left: 0;
  height: 2px;
  background: var(--accent);
  z-index: 101;
  transform-origin: left;
  transform: scaleX(0);
  transition: transform 0.1s linear;
}

/* ── Magnetic Hover ────────────────────────────────────── */
.magnetic {
  transition: transform 0.3s var(--ease-out);
}

/* ── Number Count Anim ─────────────────────────────────── */
.count-target {
  display: inline-block;
}

/* ── Image Parallax Container ──────────────────────────── */
.parallax-wrap {
  overflow: hidden;
}

.parallax-img {
  transform-origin: center;
  transition: transform 0.1s linear;
  will-change: transform;
}

/* ── Split Text Chars ──────────────────────────────────── */
.char {
  display: inline-block;
  overflow: hidden;
}

.char-inner {
  display: inline-block;
  transform: translateY(100%);
  transition: transform 0.6s var(--ease-out);
}

.chars-revealed .char-inner { transform: translateY(0); }

/* ── Accordion ─────────────────────────────────────────── */
.accordion-item {
  border-bottom: 1px solid var(--border);
}

.accordion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 0;
  cursor: none;
  user-select: none;
}

.accordion-title {
  font-size: 0.85rem;
  letter-spacing: 0.05em;
  transition: color 0.2s;
}

.accordion-header:hover .accordion-title { color: var(--accent); }

.accordion-icon {
  width: 20px; height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-h);
  border-radius: 50%;
  font-size: 0.8rem;
  color: var(--fg-2);
  flex-shrink: 0;
  transition: transform 0.3s var(--ease-out), background 0.3s, color 0.3s;
}

.accordion-item.open .accordion-icon {
  transform: rotate(45deg);
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
}

.accordion-body {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.4s var(--ease-out);
}

.accordion-body-inner {
  padding-bottom: 20px;
  font-size: 0.78rem;
  line-height: 1.8;
  color: var(--fg-2);
}

/* ── Hover line underline ──────────────────────────────── */
.hover-line {
  position: relative;
  display: inline-block;
}

.hover-line::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0;
  width: 100%; height: 1px;
  background: currentColor;
  transform: scaleX(0);
  transform-origin: right;
  transition: transform 0.4s var(--ease-out);
}

.hover-line:hover::after {
  transform: scaleX(1);
  transform-origin: left;
}

/* ── Grid line decorations ─────────────────────────────── */
.grid-decor {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 80px 80px;
  opacity: 0.4;
  mask-image: radial-gradient(ellipse 60% 80% at 50% 50%, black 40%, transparent 100%);
}

/* ── Loading States ────────────────────────────────────── */
.skeleton {
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  animation: shimmer 1.5s linear infinite;
}
</style>
</head>
<body>

<!-- Noise overlay -->
<div class="noise-overlay"></div>

<!-- Random ambient blue glows -->
<div style="position:fixed;pointer-events:none;z-index:0;inset:0;overflow:hidden;">
  <div style="position:absolute;top:-10%;left:-5%;width:600px;height:600px;background:radial-gradient(circle,rgba(0,162,255,0.07) 0%,transparent 70%);border-radius:50%;"></div>
  <div style="position:absolute;top:30%;right:-8%;width:500px;height:500px;background:radial-gradient(circle,rgba(0,162,255,0.05) 0%,transparent 70%);border-radius:50%;"></div>
  <div style="position:absolute;bottom:-5%;left:20%;width:700px;height:700px;background:radial-gradient(circle,rgba(0,162,255,0.06) 0%,transparent 70%);border-radius:50%;"></div>
  <div style="position:absolute;top:55%;left:40%;width:400px;height:400px;background:radial-gradient(circle,rgba(0,162,255,0.04) 0%,transparent 70%);border-radius:50%;"></div>
  <div style="position:absolute;top:10%;right:25%;width:350px;height:350px;background:radial-gradient(circle,rgba(0,162,255,0.04) 0%,transparent 70%);border-radius:50%;"></div>
</div>

<!-- Scroll progress -->
<div id="scroll-progress"></div>

<!-- Custom cursor -->
<div id="cursor">
  <div id="cursor-dot"></div>
  <div id="cursor-ring"></div>
</div>

<!-- Loader -->
<div id="loader">
  <div class="loader-logo" style="font-family: var(--font-display); letter-spacing: 0.4em;">SNIPER</div>
  <div class="loader-bar-wrap">
    <div class="loader-bar"></div>
  </div>
  <div class="loader-num">0%</div>
</div>

<!-- Navigation -->
<nav id="nav">
  <a href="/" class="nav-logo">SNIPER<span>.</span></a>
  <ul class="nav-links">
    <li><a href="/" class="active">Dashboard</a></li>
    <li class="nav-dropdown">
      <a href="products.html">Targets <span class="nav-dropdown-chevron">▾</span></a>
      <div class="nav-dropdown-menu">
        <a href="products.html" class="nav-dropdown-item">All Tracked</a>
        <a href="products.html" class="nav-dropdown-item">Locating</a>
        <a href="products.html" class="nav-dropdown-item">Located</a>
      </div>
    </li>
    <li><a href="cart.html">Accounts</a></li>
    <li><a href="instances.html">Instances</a></li>
    <li><a href="about.html">Specs</a></li>
    <li><a href="journal.html">History</a></li>
  </ul>
  <div class="nav-actions">
    <a href="cart.html" class="nav-cart">
      Scouts
      <span class="cart-badge">0</span>
    </a>
    <button id="nav-search-btn" class="nav-search-btn" aria-label="Search">&#9906;</button>
    <button class="nav-hamburger" id="hamburger" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
  </div>
</nav>

<!-- Mobile Menu -->
<div class="mobile-menu" id="mobile-menu">
  <div class="mobile-menu-links">
    <a href="/" class="mobile-menu-link active">Dashboard</a>
    <a href="products.html" class="mobile-menu-link">Targets</a>
    <div class="mobile-menu-sub">
      <a href="products.html">All Tracked</a>
      <a href="products.html">Locating</a>
      <a href="products.html">Located</a>
    </div>
    <a href="cart.html" class="mobile-menu-link">Accounts</a>
    <a href="about.html" class="mobile-menu-link">Specs</a>
    <a href="journal.html" class="mobile-menu-link">History</a>
  </div>
  <div class="mobile-menu-footer">© 2026 SNIPER System Corp — Berlin, DE</div>
</div>

<!-- Search Overlay -->
<div id="search-overlay" class="search-overlay">
  <div class="search-overlay-inner">
    <div class="search-overlay-label">Search Targets</div>
    <div class="search-overlay-input-wrap">
      <input id="search-overlay-input" class="search-overlay-input" type="text" placeholder="Type target username…" autocomplete="off" />
      <button id="search-overlay-close" class="search-overlay-close">&#215;</button>
    </div>
    <div id="search-overlay-results" class="search-overlay-results">
      <div class="search-overlay-hint">Start typing to search active targets…</div>
    </div>
  </div>
</div>

<!-- ── CONSOLE DASHBOARD ─────────────────────────────────────────────── -->
<section id="hero" style="min-height: 100vh; padding-top: var(--nav-h); position: relative; overflow: hidden;">
  <!-- Background grid decor -->
  <div class="grid-decor"></div>

  <div class="container" style="padding-top: 60px; padding-bottom: 80px;">
    
    <!-- Header -->
    <div style="max-width: 900px; margin-bottom: 48px;">
      <div class="section-label" style="margin-bottom: 20px; opacity: 0; animation: slideDown 0.6s 0.8s var(--ease-out) both;">
        SNIPER
      </div>
      <h1 class="display-text" style="margin-bottom: 16px; font-size: clamp(2.5rem, 5vw, 4.5rem);">
        Dashboard Console
      </h1>
      <p class="body-text" style="max-width: 600px;">
        Add targets, launch scouts, and watch matches come in.
      </p>
    </div>

    <!-- Stats Grid -->
    <div class="dashboard-grid reveal" data-delay="1">
      <div class="dashboard-stat-card">
        <span class="dashboard-stat-label">Online Scouts</span>
        <div class="dashboard-stat-value" id="count-scouts">0</div>
      </div>
      <div class="dashboard-stat-card">
        <span class="dashboard-stat-label">Active Targets</span>
        <div class="dashboard-stat-value" id="count-targets">0</div>
      </div>
      <div class="dashboard-stat-card">
        <span class="dashboard-stat-label">Total Matches</span>
        <div class="dashboard-stat-value" id="count-found">0</div>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 32px;" class="reveal" data-delay="2">
      
      <!-- Server Sweep Control Card -->
      <div class="about-manifesto" style="text-align: left; padding: 40px; display: flex; flex-direction: column; justify-content: space-between; height: 100%;">
        <div>
          <div class="section-label" style="margin-bottom: 16px;">Server Scan</div>
          <h2 style="font-size: 1.8rem; margin-bottom: 16px; font-weight: 400;">Find Servers</h2>
          <p style="font-size: 0.8rem; color: var(--fg-2); line-height: 1.6; margin-bottom: 24px;">
            Pulls all active Da Hood servers sorted by player count. Scouts work through them automatically — biggest first.
          </p>
        </div>
        
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-family: var(--font-mono); font-size: 0.72rem;">
            <span id="scan-status" style="color: var(--fg-2);">0 servers queued</span>
            <span id="scan-pct" style="color: var(--accent);">0% verified</span>
          </div>
          
          <div style="height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; margin-bottom: 24px;">
            <div id="scan-bar" style="height: 100%; background: var(--fg); width: 0%; transition: width 0.4s var(--ease-out);"></div>
          </div>
          
          <button class="btn btn-primary" id="scan-btn" onclick="triggerScan()" style="width: 100%; justify-content: center;">
            <span>Scan Public Servers</span>
          </button>
          <button class="btn" id="scout-btn" onclick="startScout()" style="width: 100%; justify-content: center; margin-top: 10px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.65rem; font-family: var(--font-mono); letter-spacing: 0.1em; padding: 13px 0; cursor: none;">
            <span>Launch Scout</span>
          </button>
        </div>
      </div>

      <!-- Live Matches Card -->
      <div class="about-manifesto" style="text-align: left; padding: 40px; height: 100%;">
        <div class="section-label" style="margin-bottom: 16px;">Live</div>
        <h2 style="font-size: 1.8rem; margin-bottom: 16px; font-weight: 400;">Found</h2>
        
        <div class="list-scroll" id="live-feed" style="max-height: 300px; margin-top: 16px;">
          <div style="padding: 40px 0; text-align: center; color: var(--fg-3); font-size: 0.8rem;">
            No targets found yet.
          </div>
        </div>
      </div>

    </div>

    <!-- Scout Activity Panel -->
    <div style="margin-top: 32px;" class="reveal" data-delay="3">
      <div class="about-manifesto" style="text-align: left; padding: 40px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
          <div>
            <div class="section-label" style="margin-bottom:8px;">Live Activity</div>
            <h2 style="font-size:1.4rem;font-weight:400;margin:0;">Scout Servers</h2>
          </div>
          <div id="scout-activity-badge" style="font-family:var(--font-mono);font-size:0.7rem;color:var(--fg-3);padding:4px 10px;border:1px solid var(--border);border-radius:4px;">0 active</div>
        </div>
        <div id="scout-activity-list" style="display:flex;flex-direction:column;gap:10px;">
          <div style="text-align:center;color:var(--fg-3);font-size:0.8rem;padding:24px 0;">No scouts online.</div>
        </div>
      </div>
    </div>

  </div>
</section>

<!-- Footer -->
<footer>
  <div class="container">
    <div class="footer-grid">
      <div class="footer-brand-col">
        <div class="footer-brand-name">SNIPER<span>.</span></div>
        <p class="footer-desc">Professional player location telemetry and match correlation dashboard.</p>
      </div>
      <div class="footer-links-col">
        <div class="footer-col-title">Operations</div>
        <div class="footer-links">
          <a href="/">Dashboard</a>
          <a href="products.html">Targets</a>
          <a href="cart.html">Accounts</a>
        </div>
      </div>
      <div class="footer-links-col">
        <div class="footer-col-title">Configuration</div>
        <div class="footer-links">
          <a href="checkout.html">Deploy Settings</a>
          <a href="about.html">Specs</a>
          <a href="journal.html">History</a>
        </div>
      </div>
      <div class="footer-links-col">
        <div class="footer-col-title">Quick Links</div>
        <div class="footer-links">
          <a href="checkout.html">Place ID Config</a>
          <a href="checkout.html">Webhook Integration</a>
          <a href="about.html">System Manifesto</a>
        </div>
      </div>
    </div>
    
    <div class="footer-bottom">
      <div class="footer-copy">© 2026 SNIPER Dashboard Inc. All rights reserved.</div>
      <div class="footer-legal">
        <a href="#">Security Protocol</a>
        <a href="#">API Documentation</a>
      </div>
    </div>
  </div>
</footer>

<!-- Logic Scripts -->



<script>
async function apiFetch(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function switchTab(name) {
  // Map tab names to the page sections visible on this single-page app
  const sections = document.querySelectorAll('section[id], #hero');
  // For now scroll to top and update nav active state
  window.scrollTo(0, 0);
  document.querySelectorAll('.nav-links a, .mobile-menu-link').forEach(a => a.classList.remove('active'));
  const activeLinks = document.querySelectorAll(`[onclick*="switchTab('${name}')"]`);
  activeLinks.forEach(a => a.classList.add('active'));
  // If there is a section mapping, scroll to it
  const sectionMap = { dashboard: 'hero', targets: 'targets-section', accounts: 'accounts-section', history: 'history-section', settings: 'settings-section', specs: 'specs-section' };
  const sId = sectionMap[name];
  if (sId) { const el = document.getElementById(sId); if (el) el.scrollIntoView({behavior:'smooth'}); }
}
const API = {
  getTargets:    ()     => apiFetch('/api/targets'),
  addTarget:     (uid)  => apiFetch('/api/targets/add',            {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:uid})}),
  removeTarget:  (uid)  => apiFetch('/api/targets/remove',         {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:uid})}),
  clearTargets:  ()     => apiFetch('/api/targets/clear',          {method:'POST'}),
  importFriends: (uid)  => apiFetch('/api/targets/import-friends', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:uid})}),
  getScouts:     ()     => apiFetch('/api/scouts'),
  triggerScan:   ()     => apiFetch('/api/scan',                   {method:'POST'}),
  getScanStatus: ()     => apiFetch('/api/scanstatus'),
  getHistory:    ()     => apiFetch('/api/history'),
  getVps:        ()     => apiFetch('/api/vps'),
  scoutStart:    (vps, accountId) => apiFetch('/api/scout/start',  {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vps:vps||null,accountId:accountId||null})}),
};
</script>
<script>
  let prevHistoryLength = 0;

  function formatAgo(ts) {
    const diff = Math.floor(Date.now() / 1000 - ts);
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return new Date(ts * 1000).toLocaleDateString();
  }

  function getAvatarMarkup(avatarUrl) {
    if (avatarUrl) {
      return `<img class="intel-avatar" src="${avatarUrl}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2232%22 height=%2232%22><rect width=%2232%22 height=%2232%22 fill=%22%2318181b%22/><circle cx=%2216%22 cy=%2216%22 r=%228%22 fill=%22%23475569%22/></svg>'">`;
    }
    return `<div class="intel-avatar" style="display:flex;align-items:center;justify-content:center;"><span style="font-size:0.6rem;color:var(--fg-3);">?</span></div>`;
  }

  async function triggerScan() {
    const btn = document.getElementById('scan-btn');
    const btnSpan = btn.querySelector('span');
    btn.disabled = true;
    if (btnSpan) btnSpan.textContent = 'Initializing Sweep...';
    try {
      await API.triggerScan();
      pollScanStatus();
    } catch (e) {
      if (btnSpan) btnSpan.textContent = 'Scan Public Servers';
      btn.disabled = false;
    }
  }

  async function startScout() {
    const btn = document.getElementById('scout-btn');
    const btnSpan = btn.querySelector('span');
    btn.disabled = true;
    if (btnSpan) btnSpan.textContent = 'Launching...';
    try {
      let vps = null;
      try { const vpsData = await API.getVps(); if (vpsData && vpsData.length > 0) vps = vpsData[0].vps_id; } catch {}
      const r = await API.scoutStart(vps, null);
      if (r.ok) {
        if (btnSpan) btnSpan.textContent = 'Scout Launched ✓';
        setTimeout(() => { if (btnSpan) btnSpan.textContent = 'Launch Scout'; btn.disabled = false; }, 3000);
      } else {
        const msg = r.error === 'all accounts already active' ? 'All scouts active' : 'Launch Scout';
        if (btnSpan) btnSpan.textContent = msg;
        setTimeout(() => { if (btnSpan) btnSpan.textContent = 'Launch Scout'; btn.disabled = false; }, 2500);
      }
    } catch (e) {
      if (btnSpan) btnSpan.textContent = 'Launch Scout';
      btn.disabled = false;
    }
  }

  async function pollScanStatus() {
    try {
      const d = await API.getScanStatus();
      const statusEl = document.getElementById('scan-status');
      const barEl = document.getElementById('scan-bar');
      const pctEl = document.getElementById('scan-pct');
      const btn = document.getElementById('scan-btn');
      const btnSpan = btn.querySelector('span');

      statusEl.textContent = `${d.queued} servers queued`;

      if (d.running) {
        const pct = d.total > 0 ? Math.round((d.progress / d.total) * 100) : 0;
        barEl.style.width = pct + '%';
        pctEl.textContent = `${d.progress} found`;
        if (btnSpan) btnSpan.textContent = `Scanning (${pct}%)`;
        btn.disabled = true;
        setTimeout(pollScanStatus, 1000);
      } else {
        barEl.style.width = d.total > 0 ? '100%' : '0%';
        pctEl.textContent = `${d.total} total`;
        if (btnSpan) btnSpan.textContent = 'Scan Public Servers';
        btn.disabled = false;
      }
    } catch (e) {}
  }

  async function loadDashboardData() {
    try {
      const [targets, scouts, history] = await Promise.all([
        API.getTargets(),
        API.getScouts(),
        API.getHistory()
      ]);

      const onlineCount = Object.values(scouts).filter(s => s.alive).length;
      const targetCount = Object.keys(targets).length;
      const matchCount = history.length;

      document.getElementById('count-scouts').textContent = onlineCount;
      document.getElementById('count-targets').textContent = targetCount;
      document.getElementById('count-found').textContent = matchCount;

      // Update nav scouts badge
      const badge = document.querySelector('.cart-badge');
      if (badge) {
        badge.textContent = onlineCount;
        badge.classList.toggle('show', onlineCount > 0);
      }

      // Render Scout Activity panel
      const activityEl = document.getElementById('scout-activity-list');
      const activityBadge = document.getElementById('scout-activity-badge');
      const scoutEntries = Object.entries(scouts).filter(([,s]) => s.alive);
      if (activityBadge) activityBadge.textContent = scoutEntries.length + ' active';
      if (activityEl) {
        if (scoutEntries.length === 0) {
          activityEl.innerHTML = '<div style="text-align:center;color:var(--fg-3);font-size:0.8rem;padding:24px 0;">No scouts online.</div>';
        } else {
          activityEl.innerHTML = scoutEntries.map(([id, s]) => {
            const jobId = s.current_server || '';
            const jobShort = jobId ? jobId.slice(0,8) + '...' : '—';
            const joinUrl = jobId ? `https://www.roblox.com/games/${s.place_id || '2788229376'}?gameInstanceId=${jobId}` : null;
            const players = s.player_count != null ? s.player_count : '?';
            const hops = s.hops != null ? s.hops : '?';
            const statusColor = s.status === 'scouting' ? '#4ade80' : s.status === 'assigned' ? '#facc15' : '#94a3b8';
            return `<div style="display:flex;align-items:center;gap:16px;padding:12px 16px;background:var(--bg-3);border-radius:6px;border:1px solid var(--border);">
              <div style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0;"></div>
              <div style="flex:1;min-width:0;">
                <div style="font-family:var(--font-mono);font-size:0.8rem;font-weight:500;color:var(--fg);">${s.username || id}</div>
                <div style="font-family:var(--font-mono);font-size:0.68rem;color:var(--fg-3);margin-top:2px;">
                  ${jobId
                    ? `Server: <span style="color:var(--fg-2)">${jobShort}</span>`
                    : '<span style="color:var(--fg-3)">No server</span>'}
                  &nbsp;&middot;&nbsp; Players: <span style="color:var(--fg-2)">${players}</span>
                  &nbsp;&middot;&nbsp; Hops: <span style="color:var(--fg-2)">${hops}</span>
                </div>
              </div>
              ${joinUrl ? `<a href="${joinUrl}" target="_blank" style="font-family:var(--font-mono);font-size:0.65rem;color:var(--accent);text-decoration:none;border:1px solid var(--border);padding:4px 10px;border-radius:4px;white-space:nowrap;">Join</a>` : ''}
            </div>`;
          }).join('');
        }
      }

      // Render Telemetry Feed
      const feedEl = document.getElementById('live-feed');
      if (history.length === 0) {
        feedEl.innerHTML = `<div style="padding: 40px 0; text-align: center; color: var(--fg-3); font-size: 0.8rem;">No targets located yet.</div>`;
      } else {
        feedEl.innerHTML = history.slice(0, 6).map(item => `
          <div style="display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--border);">
            ${getAvatarMarkup(item.avatar)}
            <div style="flex:1;min-width:0;">
              <div style="font-size:0.8rem;font-weight:500;color:var(--fg);font-family:var(--font-mono);">${item.username}</div>
              <div style="font-size:0.68rem;color:var(--fg-3);font-family:var(--font-mono);">${item.userId} &middot; ${formatAgo(item.foundAt)}</div>
            </div>
            <a href="${item.joinUrl}" class="btn btn-primary font-mono" style="padding:6px 14px;font-size:0.6rem;letter-spacing:0.1em;border-radius:4px;cursor:none;">
              Join
            </a>
          </div>
        `).join('');
      }

      // Show toast if a new match is detected
      if (prevHistoryLength > 0 && history.length > prevHistoryLength) {
        const latestMatch = history[0];
        showToast(`Target Located: ${latestMatch.username}`);
      }
      prevHistoryLength = history.length;

    } catch (e) {
      console.error(e);
    }
  }

  // Load and set intervals
  loadDashboardData();
  pollScanStatus();
  setInterval(loadDashboardData, 3000);
</script>
<script>
(function initBackground() {
  const canvas = document.createElement('canvas');
  canvas.id = 'bg-canvas';
  Object.assign(canvas.style, {
    position: 'fixed',
    top: '0',
    left: '0',
    width: '100vw',
    height: '100vh',
    zIndex: '-1',
    pointerEvents: 'none',
    display: 'block'
  });
  document.body.insertBefore(canvas, document.body.firstChild);
  const ctx = canvas.getContext('2d');

  let W = canvas.width = window.innerWidth;
  let H = canvas.height = window.innerHeight;

  window.addEventListener('resize', () => {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    placeBlobs();
  });

  // --- Ambient glow blobs ---
  // Positions defined as fractions of screen so they scale on resize
  const blobDefs = [
    { xf: 0.0,  yf: 0.0,  r: 0.38, baseA: 0.18 }, // top-left corner
    { xf: 1.0,  yf: 0.15, r: 0.32, baseA: 0.15 }, // top-right
    { xf: 0.5,  yf: 0.5,  r: 0.28, baseA: 0.10 }, // dead center (subtle)
    { xf: 0.0,  yf: 0.85, r: 0.30, baseA: 0.14 }, // bottom-left
    { xf: 1.0,  yf: 0.78, r: 0.34, baseA: 0.16 }, // bottom-right
    { xf: 0.72, yf: 0.42, r: 0.22, baseA: 0.11 }, // mid-right
    { xf: 0.22, yf: 0.62, r: 0.20, baseA: 0.10 }, // mid-left-lower
  ];

  let blobs = [];
  function placeBlobs() {
    blobs = blobDefs.map((d, i) => ({
      x: d.xf * W,
      y: d.yf * H,
      r: Math.min(W, H) * d.r,
      baseA: d.baseA,
      phase: i * (Math.PI * 2 / blobDefs.length), // stagger phases
      speed: 0.0008 + i * 0.0002
    }));
  }
  placeBlobs();

  // --- Faint grid ---
  const GRID = 50;

  let t = 0;

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // 1. Faint grid lines
    ctx.strokeStyle = 'rgba(0, 162, 255, 0.025)';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < W; x += GRID) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += GRID) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    // 2. Ambient glow blobs — pulse gently
    t += 0.01;
    blobs.forEach(b => {
      const pulse = Math.sin(t * b.speed * 100 + b.phase); // -1 to 1
      const alpha = b.baseA + pulse * (b.baseA * 0.35);     // ±35% of base

      const grad = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r);
      grad.addColorStop(0,   `rgba(0, 162, 255, ${alpha})`);
      grad.addColorStop(0.45, `rgba(0, 100, 220, ${alpha * 0.4})`);
      grad.addColorStop(1,   'rgba(0, 0, 0, 0)');

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
      ctx.fill();
    });

    requestAnimationFrame(draw);
  }

  draw();
})();

</script>
<script>
// ── Loader ───────────────────────────────────────────────
(function initLoader() {
  document.body.classList.add('loading');

  const loader    = document.getElementById('loader');
  const bar       = document.querySelector('.loader-bar');
  const numEl     = document.querySelector('.loader-num');
  if (!loader) return;

  let progress = 0;
  const interval = setInterval(() => {
    progress += Math.random() * 18 + 4;
    if (progress >= 100) {
      progress = 100;
      clearInterval(interval);
      bar && (bar.style.width = '100%');
      numEl && (numEl.textContent = '100%');
      setTimeout(hideLoader, 300);
    } else {
      bar && (bar.style.width = progress + '%');
      numEl && (numEl.textContent = Math.floor(progress) + '%');
    }
  }, 60);

  function hideLoader() {
    loader.classList.add('hidden');
    document.body.classList.remove('loading');
    setTimeout(() => {
      loader.style.display = 'none';
      triggerHeroEntrance();
    }, 650);
  }
})();

// ── Custom Cursor ────────────────────────────────────────
(function initCursor() {
  const cursor = document.getElementById('cursor');
  const dot    = document.getElementById('cursor-dot');
  const ring   = document.getElementById('cursor-ring');
  if (!cursor || !dot || !ring) return;

  let mx = window.innerWidth / 2, my = window.innerHeight / 2;
  let rx = mx, ry = my;
  let raf;

  document.addEventListener('mousemove', (e) => {
    mx = e.clientX;
    my = e.clientY;
    dot.style.left = mx + 'px';
    dot.style.top  = my + 'px';
  });

  function lerp(a, b, t) { return a + (b - a) * t; }

  function animCursor() {
    rx = lerp(rx, mx, 0.12);
    ry = lerp(ry, my, 0.12);
    ring.style.left = rx + 'px';
    ring.style.top  = ry + 'px';
    raf = requestAnimationFrame(animCursor);
  }
  animCursor();

  // Hover states
  document.addEventListener('mouseover', (e) => {
    const el = e.target.closest('a, button, .product-card, [data-cursor]');
    if (!el) return;
    if (el.matches('input, textarea')) {
      document.body.classList.add('cursor-text');
    } else {
      document.body.classList.add('cursor-hover');
    }
  });

  document.addEventListener('mouseout', (e) => {
    const el = e.target.closest('a, button, .product-card, [data-cursor]');
    if (!el) return;
    document.body.classList.remove('cursor-hover', 'cursor-text');
  });
})();

// ── Navigation ───────────────────────────────────────────
(function initNav() {
  const nav = document.getElementById('nav');
  if (!nav) return;

  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  }, { passive: true });

  // Active link — mark "Collection" trigger active on any products page
  const page = window.location.pathname.split('/').pop() || 'index.html';
  nav.querySelectorAll('.nav-links > li > a').forEach(a => {
    const href = a.getAttribute('href').split('/').pop().split('?')[0];
    if (href === page) a.classList.add('active');
  });
  if (page === 'products.html' || page === 'product.html') {
    const collectionLink = nav.querySelector('.nav-dropdown > a');
    if (collectionLink) collectionLink.classList.add('active');
  }

  // Hamburger / mobile menu
  const hamburger  = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobile-menu');
  if (!hamburger || !mobileMenu) return;

  function toggleMenu(force) {
    const open = force !== undefined ? force : !hamburger.classList.contains('open');
    hamburger.classList.toggle('open', open);
    mobileMenu.classList.toggle('open', open);
    document.body.style.overflow = open ? 'hidden' : '';
  }

  hamburger.addEventListener('click', () => toggleMenu());

  mobileMenu.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => toggleMenu(false));
  });

  // Close on resize back to desktop
  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) toggleMenu(false);
  });
})();

// ── Scroll Progress Bar ──────────────────────────────────
(function initScrollProgress() {
  const bar = document.getElementById('scroll-progress');
  if (!bar) return;

  window.addEventListener('scroll', () => {
    const scrollTop  = window.scrollY;
    const docHeight  = document.documentElement.scrollHeight - window.innerHeight;
    const progress   = docHeight > 0 ? scrollTop / docHeight : 0;
    bar.style.transform = `scaleX(${progress})`;
  }, { passive: true });
})();

// ── Reveal on Scroll ─────────────────────────────────────
function initReveal() {
  const els = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-scale');
  if (!els.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

  els.forEach(el => observer.observe(el));
}

// ── Hero Entrance ────────────────────────────────────────
function triggerHeroEntrance() {
  const lines = document.querySelectorAll('.hero-line-inner');
  lines.forEach(el => el.classList.add('in'));

  const badge = document.querySelector('.hero-badge');
  if (badge) {
    setTimeout(() => badge.style.animation = 'slideDown 0.6s var(--ease-out) both', 200);
  }

  const ctas = document.querySelectorAll('.hero-cta');
  ctas.forEach((el, i) => {
    setTimeout(() => {
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    }, 600 + i * 100);
  });

  setTimeout(initReveal, 400);
}

// ── Animated Counters ────────────────────────────────────
function initCounters() {
  const els = document.querySelectorAll('[data-count]');
  if (!els.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el     = entry.target;
      const target = parseFloat(el.dataset.count);
      const suffix = el.dataset.suffix || '';
      const prefix = el.dataset.prefix || '';
      const dur    = 1800;
      const start  = performance.now();

      function tick(now) {
        const elapsed = now - start;
        const t = Math.min(elapsed / dur, 1);
        const ease = 1 - Math.pow(1 - t, 4);
        const val   = target * ease;
        el.textContent = prefix + (Number.isInteger(target) ? Math.floor(val) : val.toFixed(1)) + suffix;
        if (t < 1) requestAnimationFrame(tick);
        else el.textContent = prefix + target + suffix;
      }

      requestAnimationFrame(tick);
      observer.unobserve(el);
    });
  }, { threshold: 0.5 });

  els.forEach(el => observer.observe(el));
}

// ── Magnetic Buttons ─────────────────────────────────────
function initMagnetic() {
  document.querySelectorAll('.magnetic').forEach(el => {
    el.addEventListener('mousemove', (e) => {
      const rect  = el.getBoundingClientRect();
      const cx    = rect.left + rect.width  / 2;
      const cy    = rect.top  + rect.height / 2;
      const dx    = (e.clientX - cx) * 0.25;
      const dy    = (e.clientY - cy) * 0.25;
      el.style.transform = `translate(${dx}px, ${dy}px)`;
    });

    el.addEventListener('mouseleave', () => {
      el.style.transform = '';
    });
  });
}

// ── Parallax ─────────────────────────────────────────────
function initParallax() {
  const wraps = document.querySelectorAll('.parallax-wrap');
  if (!wraps.length) return;

  window.addEventListener('scroll', () => {
    wraps.forEach(wrap => {
      const rect  = wrap.getBoundingClientRect();
      const img   = wrap.querySelector('.parallax-img');
      if (!img) return;
      const speed = parseFloat(wrap.dataset.speed || 0.2);
      const cy    = rect.top + rect.height / 2 - window.innerHeight / 2;
      img.style.transform = `translateY(${cy * speed}px)`;
    });
  }, { passive: true });
}

// ── Accordion ────────────────────────────────────────────
function initAccordion() {
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => {
      const item = header.closest('.accordion-item');
      const body = item.querySelector('.accordion-body');
      const inner = item.querySelector('.accordion-body-inner');
      const isOpen = item.classList.contains('open');

      document.querySelectorAll('.accordion-item.open').forEach(openItem => {
        openItem.classList.remove('open');
        openItem.querySelector('.accordion-body').style.maxHeight = '0';
      });

      if (!isOpen) {
        item.classList.add('open');
        body.style.maxHeight = inner.offsetHeight + 'px';
      }
    });
  });
}

// ── Tabs ─────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.closest('[data-tabs]') || btn.parentElement.parentElement;
      const target = btn.dataset.tab;

      group.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.dataset.tab === target);
      });
    });
  });
}

// ── Smooth page transitions ──────────────────────────────
function initPageTransitions() {
  document.querySelectorAll('a[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('http') || href.startsWith('mailto')) return;

    link.addEventListener('click', (e) => {
      e.preventDefault();
      document.body.style.opacity = '0';
      document.body.style.transition = 'opacity 0.3s';
      setTimeout(() => window.location.href = href, 300);
    });
  });
}

// ── Update Scouts Active Badge ───────────────────────────
async function updateCartBadge() {
  const badge = document.querySelector('.cart-badge');
  if (!badge) return;
  try {
    if (typeof API !== 'undefined') {
      const scouts = await API.getScouts();
      const onlineCount = Object.values(scouts).filter(s => s.alive).length;
      badge.textContent = onlineCount;
      badge.classList.toggle('show', onlineCount > 0);
    }
  } catch (e) {
    badge.classList.remove('show');
  }
}

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  updateCartBadge();
  initCounters();
  initMagnetic();
  initParallax();
  initAccordion();
  initTabs();
  initPageTransitions();
  document.body.style.opacity = '1';
  document.body.style.transition = 'opacity 0.4s';
});

// ── Search Overlay ───────────────────────────────────────
function initSearchOverlay() {
  const overlay = document.getElementById('search-overlay');
  const input   = document.getElementById('search-overlay-input');
  const results = document.getElementById('search-overlay-results');
  const openBtn = document.getElementById('nav-search-btn');
  const closeBtn= document.getElementById('search-overlay-close');
  if (!overlay || !input) return;

  function openOverlay() {
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    setTimeout(() => input.focus(), 100);
  }

  function closeOverlay() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    input.value = '';
    results.innerHTML = '<div class="search-overlay-hint">Start typing to search targets…</div>';
  }

  openBtn  && openBtn.addEventListener('click', openOverlay);
  closeBtn && closeBtn.addEventListener('click', closeOverlay);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && overlay.classList.contains('open')) closeOverlay();
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); openOverlay(); }
  });

  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeOverlay();
  });

  input.addEventListener('input', async () => {
    const q = input.value.toLowerCase().trim();
    if (!q) {
      results.innerHTML = '<div class="search-overlay-hint">Start typing to search targets…</div>';
      return;
    }
    
    try {
      if (typeof API === 'undefined') return;
      const targets = await API.getTargets();
      const matches = Object.entries(targets).filter(([uid, t]) => 
        uid.includes(q) || (t.username && t.username.toLowerCase().includes(q))
      ).slice(0, 6);

      if (!matches.length) {
        results.innerHTML = '<div class="search-overlay-hint">No results for "' + input.value + '"</div>';
        return;
      }

      results.innerHTML = '';
      matches.forEach(([uid, t]) => {
        const a = document.createElement('a');
        a.href = 'product.html?id=' + uid;
        a.className = 'search-result-item';
        
        const isFound = t.status === 'found';
        const badgeMarkup = `<span class="badge ${isFound ? 'badge-located' : 'badge-searching'}" style="font-size:0.55rem; padding:2px 6px; border-radius:3px;">${isFound ? 'LOCATED' : 'LOCATING'}</span>`;
        
        a.innerHTML = `<div class="search-result-img" style="border-radius:50%; overflow:hidden; border:1px solid var(--border); display:flex; align-items:center; justify-content:center; width:32px; height:32px; background:var(--bg-3);">` 
          + (t.avatar ? `<img src="${t.avatar}" style="width:100%; height:100%; object-fit:cover;">` : '?') + '</div>'
          + '<div><div class="search-result-name" style="font-family:var(--font-mono); font-size:0.8rem; font-weight:500;">' + t.username + '</div>'
          + '<div style="font-family:var(--font-mono); font-size:0.65rem; color:var(--fg-3); margin-top:2px; display:flex; align-items:center; gap:8px;">ID: ' + uid + ' &middot; ' + badgeMarkup + '</div></div>';
        results.appendChild(a);
      });
    } catch (e) {
      results.innerHTML = '<div class="search-overlay-hint">Search failed.</div>';
    }
  });
}

// ── Card Interactive Hover Glow Helper ───────────────────
function initCardGlow() {
  document.addEventListener('mousemove', e => {
    const cards = document.querySelectorAll('.dashboard-stat-card, .scout-card, .about-manifesto, .product-card');
    cards.forEach(card => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', `${x}px`);
      card.style.setProperty('--mouse-y', `${y}px`);
    });
  });
}

// Patch into DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  initSearchOverlay();
  initCardGlow();
});
</script>
</body>
</html>"""

@app.route("/")
def dashboard():
    if not require_auth():
        return redirect("/login")
    # Always serve embedded DASHBOARD — self-contained, no external JS files needed
    return render_template_string(DASHBOARD)

# Inline API script injected into every served HTML page
_INLINE_API = """<script>
async function apiFetch(p,o){const r=await fetch(p,o);if(!r.ok)throw new Error(r.status);return r.json();}
const API={
  getTargets:()=>apiFetch('/api/targets'),
  addTarget:(u)=>apiFetch('/api/targets/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u})}),
  removeTarget:(u)=>apiFetch('/api/targets/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u})}),
  clearTargets:()=>apiFetch('/api/targets/clear',{method:'POST'}),
  importFriends:(u)=>apiFetch('/api/targets/import-friends',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u})}),
  getScouts:()=>apiFetch('/api/scouts'),
  triggerScan:()=>apiFetch('/api/scan',{method:'POST'}),
  getScanStatus:()=>apiFetch('/api/scanstatus'),
  getHistory:()=>apiFetch('/api/history'),
  getSettings:()=>apiFetch('/api/settings'),
  saveSettings:(d)=>apiFetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),
  getVps:()=>apiFetch('/api/vps'),
  queueLaunch:(vps,accountId,target)=>apiFetch('/api/commands/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vps,accountId,target})}),
  killAccount:(vps,accountId)=>apiFetch('/api/commands/push',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vps,command:{type:'kill',accountId}})}),
  scoutStart:(vps,accountId)=>apiFetch('/api/scout/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vps:vps||null,accountId:accountId||null})}),
};
</script>"""

def _serve_html(filename):
    """Read an HTML file from STATIC_DIR, inject the inline API, return it."""
    filepath = os.path.join(STATIC_DIR, filename)
    if not os.path.isfile(filepath):
        abort(404)
    with open(filepath, 'r', encoding='utf-8') as f:
        html = f.read()
    # Remove external api.js tag if present
    html = html.replace('<script src="js/api.js"></script>', '')
    # Inject inline API before </head>
    html = html.replace('</head>', _INLINE_API + '\n</head>', 1)
    return html

@app.route("/<path:filename>")
def static_files(filename):
    reserved = ("login", "logout", "api")
    if filename.split("/")[0] in reserved:
        abort(404)
    # Serve HTML pages with injected API
    if filename.endswith(".html"):
        if not require_auth():
            return redirect("/login")
        return _serve_html(filename)
    # Serve static assets (css, js) from STATIC_DIR if present
    filepath = os.path.join(STATIC_DIR, filename)
    if os.path.isfile(filepath):
        return send_from_directory(STATIC_DIR, filename)
    abort(404)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"sniper  ->  http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)