#!/usr/bin/env python3
"""
Connection Limiter Server v2
- Receives logs from nodes
- Tracks unique IPs per user
- Disables subscription + drops IP on violation
"""

import asyncio
import os
import time
import logging
import sqlite3
import hashlib
import secrets
import json
import re
from datetime import datetime
from pathlib import Path
from collections import deque
from aiohttp import web, ClientSession, ClientTimeout

# ============ CONFIG ============
ENV_FILE = Path(__file__).parent / '.env'
LOG_STATE_FILE = Path(__file__).parent / '.log_state.json'

def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

def save_env(data):
    lines = [f"{k}={v}" for k, v in data.items() if v]
    ENV_FILE.write_text('\n'.join(lines))
    load_env()

def get_env_dict():
    if not ENV_FILE.exists():
        return {}
    result = {}
    for line in ENV_FILE.read_text().splitlines():
        if line.strip() and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            result[k.strip()] = v.strip()
    return result

load_env()

def cfg(key, default=''):
    return os.getenv(key, default)

def cfg_int(key, default=0):
    try:
        return int(os.getenv(key, default))
    except:
        return default

def get_nodes():
    nodes_str = cfg('NODES', '')
    result = {}
    for item in nodes_str.split(','):
        if ':' in item:
            name, ip = item.split(':', 1)
            result[name.strip()] = ip.strip()
    return result

# Log state
def load_log_state():
    if LOG_STATE_FILE.exists():
        try:
            return json.loads(LOG_STATE_FILE.read_text())
        except:
            pass
    return {}

def save_log_state(state):
    LOG_STATE_FILE.write_text(json.dumps(state))

log_state = load_log_state()

# ============ LOGGING ============
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('server')

admin_logs = deque(maxlen=500)
events = deque(maxlen=200)

def log(msg, level='INFO'):
    ts = datetime.now().strftime('%H:%M:%S')
    admin_logs.appendleft({'time': ts, 'level': level, 'msg': msg})
    getattr(logger, level.lower(), logger.info)(msg)

def add_event(msg, details='', level='info'):
    ts = datetime.now().strftime('%H:%M:%S')
    events.appendleft({'time': ts, 'msg': msg, 'details': details, 'level': level})


# ============ DATABASE ============
class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.conn.execute('''CREATE TABLE connections (
            user TEXT, ip TEXT, node TEXT, ts INTEGER,
            PRIMARY KEY(user, ip)
        )''')
        self.conn.execute('CREATE INDEX idx_user ON connections(user)')
        self.conn.execute('CREATE INDEX idx_ts ON connections(ts)')
    
    def add(self, user, ip, node=''):
        now = int(time.time())
        self.conn.execute('INSERT OR REPLACE INTO connections VALUES(?,?,?,?)',
                         (user, ip, node, now))
        self.conn.commit()
    
    def get_user_ips(self, user):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300)
        return [r[0] for r in self.conn.execute(
            'SELECT DISTINCT ip FROM connections WHERE user=? AND ts>?', (user, cutoff))]
    
    def get_concurrent_ips(self, user, window_seconds=60):
        """Get IPs that were active within the same time window (concurrent connections)"""
        now = int(time.time())
        cutoff = now - window_seconds
        
        # Get IPs with their last seen timestamp
        rows = self.conn.execute(
            'SELECT ip, MAX(ts) as last_seen FROM connections WHERE user=? AND ts>? GROUP BY ip',
            (user, now - cfg_int('IP_WINDOW_SECONDS', 300))
        ).fetchall()
        
        # Filter to only IPs active in the concurrent window
        concurrent = [ip for ip, ts in rows if ts >= cutoff]
        all_ips = [ip for ip, ts in rows]
        
        return concurrent, all_ips
    
    def get_active_users(self):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300)
        return [r[0] for r in self.conn.execute(
            'SELECT DISTINCT user FROM connections WHERE ts>?', (cutoff,))]
    
    def get_violators(self):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300)
        return self.conn.execute('''
            SELECT user, COUNT(DISTINCT ip) as cnt, GROUP_CONCAT(DISTINCT ip) as ips
            FROM connections WHERE ts>? GROUP BY user HAVING cnt > 1 ORDER BY cnt DESC
        ''', (cutoff,)).fetchall()
    
    def get_all_connections(self, limit=100):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300)
        return self.conn.execute('''
            SELECT user, ip, node, ts FROM connections WHERE ts>? ORDER BY ts DESC LIMIT ?
        ''', (cutoff, limit)).fetchall()
    
    def cleanup(self):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300) - 60
        self.conn.execute('DELETE FROM connections WHERE ts<?', (cutoff,))
        self.conn.commit()
    
    def stats(self):
        cutoff = int(time.time()) - cfg_int('IP_WINDOW_SECONDS', 300)
        total = self.conn.execute('SELECT COUNT(*) FROM connections WHERE ts>?', (cutoff,)).fetchone()[0]
        users = self.conn.execute('SELECT COUNT(DISTINCT user) FROM connections WHERE ts>?', (cutoff,)).fetchone()[0]
        return {'connections': total, 'users': users}
    
    def clear(self):
        self.conn.execute('DELETE FROM connections')
        self.conn.commit()

db = DB()
limit_cache = {}
drop_cooldown = {}
http = None

# Persistent disabled users storage
DISABLED_FILE = Path(__file__).parent / '.disabled_users.json'

def load_disabled_users():
    if DISABLED_FILE.exists():
        try:
            return json.loads(DISABLED_FILE.read_text())
        except:
            pass
    return {}

def save_disabled_users():
    DISABLED_FILE.write_text(json.dumps(disabled_users))

disabled_users = load_disabled_users()

async def get_http():
    global http
    if http is None or http.closed:
        http = ClientSession(timeout=ClientTimeout(total=10))
    return http


# ============ API FUNCTIONS ============
async def get_user_limit(user_id):
    now = time.time()
    if user_id in limit_cache:
        limit, ts = limit_cache[user_id]
        if now - ts < 120:
            return limit
    
    api_url = cfg('REMNAWAVE_API_URL')
    api_token = cfg('REMNAWAVE_API_TOKEN')
    if not api_url or not api_token:
        return 0
    
    try:
        s = await get_http()
        url = f"{api_url.rstrip('/')}/api/users/by-id/{user_id}"
        async with s.get(url, headers={"Authorization": f"Bearer {api_token}"}) as r:
            if r.status == 200:
                data = await r.json()
                user_data = data.get('response', data)
                limit = user_data.get('hwidDeviceLimit') or 0
                limit_cache[user_id] = (limit, now)
                return limit
    except Exception as e:
        log(f"API error: {e}", 'ERROR')
    return 0

async def get_user_uuid(user_id):
    """Get user UUID from user ID"""
    api_url = cfg('REMNAWAVE_API_URL')
    api_token = cfg('REMNAWAVE_API_TOKEN')
    if not api_url or not api_token:
        return None
    
    try:
        s = await get_http()
        url = f"{api_url.rstrip('/')}/api/users/by-id/{user_id}"
        async with s.get(url, headers={"Authorization": f"Bearer {api_token}"}) as r:
            if r.status == 200:
                data = await r.json()
                user_data = data.get('response', data)
                return user_data.get('uuid')
    except Exception as e:
        log(f"Get UUID error: {e}", 'ERROR')
    return None

async def disable_user_subscription(user_id, minutes=10):
    api_url = cfg('REMNAWAVE_API_URL')
    api_token = cfg('REMNAWAVE_API_TOKEN')
    if not api_url or not api_token:
        return False
    
    # Get user UUID first
    uuid = await get_user_uuid(user_id)
    if not uuid:
        log(f"Cannot get UUID for user {user_id}", 'ERROR')
        return False
    
    try:
        s = await get_http()
        url = f"{api_url.rstrip('/')}/api/users/{uuid}/actions/disable"
        async with s.post(url, headers={"Authorization": f"Bearer {api_token}"}) as r:
            if r.status == 200:
                disabled_users[user_id] = time.time() + (minutes * 60)
                save_disabled_users()
                log(f"Disabled user {user_id} (UUID: {uuid[:8]}...) for {minutes} min")
                return True
            else:
                log(f"Disable failed: {r.status}", 'ERROR')
    except Exception as e:
        log(f"Disable error: {e}", 'ERROR')
    return False

async def enable_user_subscription(user_id):
    api_url = cfg('REMNAWAVE_API_URL')
    api_token = cfg('REMNAWAVE_API_TOKEN')
    if not api_url or not api_token:
        return False
    
    uuid = await get_user_uuid(user_id)
    if not uuid:
        return False
    
    try:
        s = await get_http()
        url = f"{api_url.rstrip('/')}/api/users/{uuid}/actions/enable"
        async with s.post(url, headers={"Authorization": f"Bearer {api_token}"}) as r:
            if r.status == 200:
                disabled_users.pop(user_id, None)
                save_disabled_users()
                log(f"Re-enabled user {user_id}")
                return True
    except:
        pass
    return False

async def send_telegram(text):
    token = cfg('TELEGRAM_BOT_TOKEN')
    chat1 = cfg('TELEGRAM_CHAT_ID')
    chat2 = cfg('TELEGRAM_CHAT_ID_2')
    if not token:
        return False
    try:
        s = await get_http()
        # Send to first chat
        if chat1:
            await s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat1, "text": text, "parse_mode": "HTML"})
        # Send to second chat if configured
        if chat2:
            await s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat2, "text": text, "parse_mode": "HTML"})
        return True
    except:
        return False

async def get_bot_username():
    token = cfg('TELEGRAM_BOT_TOKEN')
    if not token:
        return None
    try:
        s = await get_http()
        async with s.get(f"https://api.telegram.org/bot{token}/getMe") as r:
            if r.status == 200:
                data = await r.json()
                return data.get('result', {}).get('username')
    except:
        pass
    return None

async def drop_ip_on_all_nodes(ip):
    nodes = get_nodes()
    secret = cfg('NODE_API_SECRET', 'secret')
    duration = cfg_int('DROP_DURATION_SECONDS', 600)
    
    async def drop_one(name, node_ip):
        try:
            s = await get_http()
            async with s.post(f"http://{node_ip}:5001/block",
                            json={"ip": ip, "duration": duration, "secret": secret},
                            timeout=ClientTimeout(total=3)) as r:
                if r.status == 200:
                    log(f"Dropped {ip} on {name}")
                    return True
        except:
            pass
        return False
    
    if nodes:
        results = await asyncio.gather(*[drop_one(n, nip) for n, nip in nodes.items()])
        return sum(results)
    return 0

async def check_node_health(node_ip):
    try:
        s = await get_http()
        async with s.get(f"http://{node_ip}:5001/health", timeout=ClientTimeout(total=2)) as r:
            return r.status == 200
    except:
        return False


# ============ VIOLATION HANDLING ============
async def handle_violation(user_id, ips, limit, reason="IP_COUNT"):
    now = time.time()
    cooldown = cfg_int('DROP_COOLDOWN_SECONDS', 60)
    
    if user_id in drop_cooldown and now - drop_cooldown[user_id] < cooldown:
        return False
    
    drop_cooldown[user_id] = now
    disable_minutes = cfg_int('DISABLE_MINUTES', 10)
    drop_all = cfg('DROP_ALL_IPS', 'true').lower() == 'true'
    ips_to_drop = ips if drop_all else (ips[limit:] if len(ips) > limit else ips[-1:])
    
    log(f"VIOLATION: User {user_id} - {reason}", 'WARNING')
    add_event(f"🚨 User {user_id}: {reason}",
              f"Dropping: {', '.join(ips_to_drop)}", 'violation')
    
    await disable_user_subscription(user_id, disable_minutes)
    for ip in ips_to_drop:
        await drop_ip_on_all_nodes(ip)
    
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    await send_telegram(
        f"🔻 <b>Disabled for {disable_minutes} minutes</b>\n"
        f"<i>{ts}</i>\n\n"
        f"User: <code>{user_id}</code>\n"
        f"IPs: {len(ips)}, Limit: {limit}\n"
        f"Dropped: {', '.join(ips_to_drop)}"
    )
    return True

def analyze_sharing(user_id, limit):
    """
    Sharing detection based on SIMULTANEOUS connections from different nodes.
    
    SHARING = user connected to 2+ VPN nodes AT THE SAME TIME
    One person physically cannot be in two places at once.
    
    Handover (IP change on same node) is NOT flagged.
    """
    now = int(time.time())
    window = cfg_int('CONCURRENT_WINDOW', 30)
    
    # Get connections from last N seconds
    rows = db.conn.execute('''
        SELECT DISTINCT ip, node FROM connections 
        WHERE user=? AND ts>?
    ''', (user_id, now - window)).fetchall()
    
    if not rows:
        return False, [], "no data"
    
    ips = [r[0] for r in rows]
    nodes = set(r[1] for r in rows if r[1])
    
    # ONLY ban if connected to MULTIPLE NODES simultaneously
    # This is the ONLY reliable way to detect sharing
    if len(nodes) >= 2:
        return True, ips, f"{len(ips)} IPs on {len(nodes)} nodes: {', '.join(nodes)}"
    
    return False, [], "ok"

async def check_user(user_id):
    limit = await get_user_limit(user_id)
    if limit <= 0:
        return False
    
    # Simple IP count - ban if more IPs than limit
    all_ips = db.get_user_ips(user_id)
    if len(all_ips) > limit:
        reason = f"{len(all_ips)} IPs > limit {limit}"
        return await handle_violation(user_id, all_ips, limit, reason)
    return False

async def scan_all_users():
    violations = 0
    for user in db.get_active_users():
        if await check_user(user):
            violations += 1
    return violations

# ============ LOG PROCESSING ============
def parse_log_line(line):
    ip_match = re.search(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+):\d+', line)
    email_match = re.search(r'email:\s*(\S+)', line)
    if ip_match and email_match:
        return email_match.group(1).replace('user_', ''), ip_match.group(1)
    return None, None

def process_log_lines(lines, node_name):
    global log_state
    if not lines:
        return 0
    
    last_line = log_state.get(node_name, '')
    start_idx = 0
    if last_line:
        for i, line in enumerate(lines):
            if line.strip() == last_line.strip():
                start_idx = i + 1
                break
    
    processed = 0
    users_to_check = set()
    for line in lines[start_idx:]:
        line = line.strip()
        if not line:
            continue
        user, ip = parse_log_line(line)
        if user and ip:
            db.add(user, ip, node_name)
            users_to_check.add(user)
            processed += 1
    
    if lines:
        log_state[node_name] = lines[-1].strip()
        save_log_state(log_state)
    
    for user in users_to_check:
        asyncio.create_task(check_user(user))
    return processed


# ============ HTTP HANDLERS ============
async def handle_log_upload(request):
    try:
        data = await request.json()
        node = data.get('node', 'unknown')
        lines = data.get('lines', [])
        secret = data.get('secret', '')
        
        if secret != cfg('NODE_API_SECRET', 'secret'):
            return web.json_response({"error": "unauthorized"}, status=403)
        
        processed = process_log_lines(lines, node)
        if processed > 0:
            log(f"Received {len(lines)} lines from {node}, processed {processed}")
        return web.json_response({"ok": True, "processed": processed})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_log_single(request):
    try:
        data = await request.json()
        user = data.get('user', '').replace('user_', '')
        ip = data.get('ip', '')
        node = data.get('node', '')
        if user and ip:
            db.add(user, ip, node)
            asyncio.create_task(check_user(user))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_health(request):
    return web.json_response({"status": "ok", **db.stats()})

# ============ ADMIN PANEL ============
ADMIN_PW_FILE = Path(__file__).parent / '.admin_password'
sessions = {}

def get_pw_hash():
    if ADMIN_PW_FILE.exists():
        return ADMIN_PW_FILE.read_text().strip()
    h = hashlib.sha256(b'admin').hexdigest()
    ADMIN_PW_FILE.write_text(h)
    return h

def set_pw(pw):
    ADMIN_PW_FILE.write_text(hashlib.sha256(pw.encode()).hexdigest())

async def check_auth(req):
    sid = req.cookies.get('session')
    return sid and sid in sessions

CSS = '''
:root{--bg:linear-gradient(135deg,#0f0f1a 0%,#1a1a2e 50%,#16213e 100%);--bg2:#1a1a2e;--card:rgba(30,30,50,0.8);--accent:#8b5cf6;--accent2:#a78bfa;--success:#34d399;--warn:#fbbf24;--danger:#f87171;--text:#f8fafc;--muted:#94a3b8;--border:rgba(139,92,246,0.2)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);background-attachment:fixed;color:var(--text);min-height:100vh}
.container{max-width:1280px;margin:0 auto;padding:32px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:32px;padding:20px 24px;background:var(--card);border-radius:20px;backdrop-filter:blur(10px);border:1px solid var(--border);box-shadow:0 8px 32px rgba(0,0,0,0.3)}
.logo{font-size:28px;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;display:flex;align-items:center;gap:12px}
.nav{display:flex;gap:6px;background:var(--card);padding:8px;border-radius:16px;backdrop-filter:blur(10px);border:1px solid var(--border);flex-wrap:wrap}
.nav a{padding:12px 20px;color:var(--muted);text-decoration:none;border-radius:12px;font-size:14px;font-weight:500;transition:all 0.3s}
.nav a:hover{background:rgba(139,92,246,0.1);color:var(--text);transform:translateY(-2px)}
.nav a.active{background:linear-gradient(135deg,var(--accent),#7c3aed);color:#fff;box-shadow:0 4px 15px rgba(139,92,246,0.4)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:20px;margin-bottom:32px}
.stat{background:var(--card);border-radius:20px;padding:24px;border:1px solid var(--border);backdrop-filter:blur(10px);transition:transform 0.3s,box-shadow 0.3s}
.stat:hover{transform:translateY(-4px);box-shadow:0 12px 40px rgba(139,92,246,0.2)}
.stat-value{font-size:36px;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-label{font-size:13px;color:var(--muted);margin-top:8px;text-transform:uppercase;letter-spacing:0.5px}
.card{background:var(--card);border-radius:20px;padding:28px;margin-bottom:24px;border:1px solid var(--border);backdrop-filter:blur(10px)}
.card h2{font-size:18px;margin-bottom:20px;color:var(--text);display:flex;align-items:center;gap:10px}
.badge{display:inline-flex;align-items:center;padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;gap:6px}
.badge-ok{background:rgba(52,211,153,0.15);color:var(--success);border:1px solid rgba(52,211,153,0.3)}
.badge-err{background:rgba(248,113,113,0.15);color:var(--danger);border:1px solid rgba(248,113,113,0.3)}
.badge-warn{background:rgba(251,191,36,0.15);color:var(--warn);border:1px solid rgba(251,191,36,0.3)}
table{width:100%;border-collapse:separate;border-spacing:0}
th,td{padding:16px;text-align:left;font-size:14px}
th{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:12px;letter-spacing:0.5px;border-bottom:1px solid var(--border)}
td{border-bottom:1px solid rgba(139,92,246,0.1)}
tr{transition:background 0.2s}
tr:hover{background:rgba(139,92,246,0.05)}
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 24px;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none;transition:all 0.3s}
.btn-primary{background:linear-gradient(135deg,var(--accent),#7c3aed);color:#fff;box-shadow:0 4px 15px rgba(139,92,246,0.3)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(139,92,246,0.4)}
.btn-danger{background:linear-gradient(135deg,var(--danger),#dc2626);color:#fff}
.btn-success{background:linear-gradient(135deg,var(--success),#10b981);color:#fff}
.btn-sm{padding:8px 16px;font-size:12px;border-radius:8px}
.btn-ghost{background:rgba(139,92,246,0.1);color:var(--accent);border:1px solid var(--border)}
.btn-ghost:hover{background:rgba(139,92,246,0.2)}
input,select{width:100%;padding:14px 18px;background:rgba(15,15,26,0.6);border:1px solid var(--border);border-radius:12px;color:var(--text);font-size:14px;margin-bottom:16px;transition:all 0.3s}
input:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(139,92,246,0.2)}
label{display:block;margin-bottom:8px;font-size:13px;color:var(--muted);font-weight:500}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.form-hint{font-size:11px;color:var(--muted);margin-top:-12px;margin-bottom:16px;opacity:0.8}
.logs{background:rgba(15,15,26,0.6);border-radius:12px;padding:20px;max-height:400px;overflow-y:auto;font-family:'JetBrains Mono',monospace;font-size:12px;border:1px solid var(--border)}
.log-entry{padding:8px 0;border-bottom:1px solid rgba(139,92,246,0.1);display:flex;gap:16px;align-items:center}
.log-time{color:var(--muted);min-width:70px;font-size:11px}
.log-INFO{color:var(--accent);font-weight:600}
.log-WARNING{color:var(--warn);font-weight:600}
.log-ERROR{color:var(--danger);font-weight:600}
.event{padding:16px;border-radius:12px;margin-bottom:10px;background:rgba(15,15,26,0.4);border:1px solid var(--border);transition:all 0.2s}
.event:hover{background:rgba(139,92,246,0.05)}
.event.violation{background:rgba(248,113,113,0.1);border-left:4px solid var(--danger)}
.login-box{max-width:420px;margin:80px auto;background:var(--card);padding:48px;border-radius:24px;border:1px solid var(--border);backdrop-filter:blur(10px);box-shadow:0 20px 60px rgba(0,0,0,0.4)}
.login-box h1{text-align:center;margin-bottom:40px;font-size:32px;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.alert{padding:16px 20px;border-radius:12px;margin-bottom:24px;font-size:14px;display:flex;align-items:center;gap:10px}
.alert-ok{background:rgba(52,211,153,0.15);color:var(--success);border:1px solid rgba(52,211,153,0.3)}
.alert-err{background:rgba(248,113,113,0.15);color:var(--danger);border:1px solid rgba(248,113,113,0.3)}
.ip-list{font-size:11px;color:var(--muted);max-width:220px;word-break:break-all}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:10px;box-shadow:0 0 8px currentColor}
.dot-on{background:var(--success);color:var(--success)}
.dot-off{background:var(--danger);color:var(--danger)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.pulse{animation:pulse 2s infinite}
'''


def base_html(content, tab='dashboard'):
    nav = [('/', 'dashboard', '📊 Dashboard'), ('/violators', 'violators', '🚨 Violators'),
           ('/connections', 'connections', '🔗 Connections'), ('/nodes', 'nodes', '🖥️ Nodes'),
           ('/logs', 'logs', '📋 Logs'), ('/settings', 'settings', '⚙️ Settings')]
    nav_html = ''.join(f'<a href="{u}" class="{"active" if t==tab else ""}">{n}</a>' for u,t,n in nav)
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connection Limiter</title><style>{CSS}</style></head><body><div class="container">
<div class="header"><div class="logo">🔒 Connection Limiter</div><a href="/logout" class="btn btn-ghost">Logout</a></div>
<nav class="nav">{nav_html}</nav>{content}</div></body></html>'''

def login_html(err=''):
    e = f'<div class="alert alert-err">{err}</div>' if err else ''
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Login</title><style>{CSS}</style></head><body>
<div class="login-box"><h1>🔒 Connection Limiter</h1>{e}<form method="POST">
<label>Password</label><input type="password" name="password" placeholder="Enter password" autofocus>
<button class="btn btn-primary" style="width:100%">Login</button></form>
<p style="text-align:center;margin-top:20px;color:var(--muted);font-size:12px">Default: admin</p></div></body></html>'''

async def page_dashboard(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    stats = db.stats()
    nodes = get_nodes()
    violators = db.get_violators()
    
    api_ok = False
    if cfg('REMNAWAVE_API_URL'):
        try:
            s = await get_http()
            async with s.get(f"{cfg('REMNAWAVE_API_URL')}/api/system/stats",
                           headers={"Authorization": f"Bearer {cfg('REMNAWAVE_API_TOKEN')}"}) as r:
                api_ok = r.status == 200
        except:
            pass
    
    tg_ok = bool(cfg('TELEGRAM_BOT_TOKEN') and cfg('TELEGRAM_CHAT_ID'))
    
    online = 0
    nodes_html = ''
    for name, ip in nodes.items():
        ok = await check_node_health(ip)
        if ok: online += 1
        dot = 'dot-on' if ok else 'dot-off'
        st = 'badge-ok' if ok else 'badge-err'
        nodes_html += f'<tr><td><span class="dot {dot}"></span>{name}</td><td>{ip}</td><td><span class="badge {st}">{"Online" if ok else "Offline"}</span></td></tr>'
    if not nodes_html:
        nodes_html = '<tr><td colspan="3" style="color:var(--muted)">No nodes</td></tr>'
    
    events_html = ''.join(f'<div class="event {e.get("level","")}">{e["time"]} - {e["msg"]} <span style="color:var(--muted)">{e["details"]}</span></div>' for e in list(events)[:8])
    if not events_html:
        events_html = '<p style="color:var(--muted)">No events</p>'
    
    content = f'''
<div class="stats">
<div class="stat"><div class="stat-value">{stats['connections']}</div><div class="stat-label">Connections</div></div>
<div class="stat"><div class="stat-value">{stats['users']}</div><div class="stat-label">Active Users</div></div>
<div class="stat"><div class="stat-value">{len(violators)}</div><div class="stat-label">Multi-IP Users</div></div>
<div class="stat"><div class="stat-value">{online}/{len(nodes)}</div><div class="stat-label">Nodes Online</div></div>
<div class="stat"><div class="stat-value">{cfg_int('IP_WINDOW_SECONDS',300)}s</div><div class="stat-label">IP Window</div></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
<div class="card"><h2>Status</h2>
<table><tr><td>API</td><td><span class="badge {"badge-ok" if api_ok else "badge-err"}">{"OK" if api_ok else "Error"}</span></td></tr>
<tr><td>Telegram</td><td><span class="badge {"badge-ok" if tg_ok else "badge-warn"}">{"OK" if tg_ok else "Not set"}</span></td></tr>
<tr><td>Disabled Users</td><td>{len(disabled_users)}</td></tr></table></div>
<div class="card"><h2>Nodes</h2><table><tr><th>Name</th><th>IP</th><th>Status</th></tr>{nodes_html}</table></div>
</div>
<div class="card"><h2>Recent Events</h2>{events_html}</div>
<div class="card"><h2>Actions</h2><div style="display:flex;gap:12px;flex-wrap:wrap">
<form method="POST" action="/action/scan"><button class="btn btn-primary">🔍 Scan Now</button></form>
<form method="POST" action="/action/test_tg"><button class="btn btn-ghost">📱 Test Telegram</button></form>
<form method="POST" action="/action/clear_db"><button class="btn btn-danger">🗑️ Clear DB</button></form>
</div></div>'''
    return web.Response(text=base_html(content, 'dashboard'), content_type='text/html')


async def page_violators(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    msg = req.query.get('msg', '')
    alert = f'<div class="alert alert-ok">{msg}</div>' if msg else ''
    
    rows = ''
    for user, cnt, ips in db.get_violators():
        limit = await get_user_limit(user)
        violation = limit > 0 and cnt > limit
        ips_list = ips.split(',') if ips else []
        st = '<span class="badge badge-err">VIOLATION</span>' if violation else ('<span class="badge badge-ok">OK</span>' if limit > 0 else '<span class="badge badge-warn">No limit</span>')
        bg = 'style="background:rgba(239,68,68,.05)"' if violation else ''
        rows += f'''<tr {bg}><td><strong>{user}</strong></td><td>{cnt}</td><td>{limit if limit > 0 else "∞"}</td><td>{st}</td>
        <td class="ip-list">{", ".join(ips_list[:3])}{"..." if len(ips_list) > 3 else ""}</td>
        <td><form method="POST" action="/action/drop_user" style="display:inline"><input type="hidden" name="user" value="{user}">
        <button class="btn btn-sm btn-danger">Drop</button></form></td></tr>'''
    if not rows:
        rows = '<tr><td colspan="6" style="color:var(--muted)">No users with multiple IPs</td></tr>'
    
    # Disabled users table
    disabled_rows = ''
    now = time.time()
    for uid, exp_time in disabled_users.items():
        remaining = int(exp_time - now)
        if remaining > 0:
            mins = remaining // 60
            secs = remaining % 60
            disabled_rows += f'''<tr><td><strong>{uid}</strong></td><td>{mins}m {secs}s</td>
            <td><form method="POST" action="/action/unban_user" style="display:inline"><input type="hidden" name="user" value="{uid}">
            <button class="btn btn-sm btn-success">Unban</button></form></td></tr>'''
    if not disabled_rows:
        disabled_rows = '<tr><td colspan="3" style="color:var(--muted)">No disabled users</td></tr>'
    
    content = f'''{alert}<div class="card"><h2>🚫 Disabled Users</h2>
<p style="color:var(--muted);font-size:13px;margin-bottom:16px">Users temporarily disabled due to violations. Will auto-enable after timeout.</p>
<table><tr><th>User ID</th><th>Time Left</th><th>Action</th></tr>{disabled_rows}</table></div>

<div class="card"><h2>🚨 Users with Multiple IPs</h2>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
<p style="color:var(--muted);font-size:13px">Red = exceeds limit. Use manual Drop button to take action.</p>
<div style="display:flex;gap:8px"><a href="/export/violators.html" class="btn btn-sm btn-primary">📊 Export Report</a><a href="/export/violators.csv" class="btn btn-sm btn-ghost">📥 CSV</a></div>
</div>
<table><tr><th>User</th><th>IPs</th><th>Limit</th><th>Status</th><th>Addresses</th><th>Action</th></tr>{rows}</table></div>
<div class="card"><h2>🔍 Manual Check</h2><form method="POST" action="/action/check_user">
<div class="form-row"><div><label>User ID</label><input name="user_id" placeholder="934057566"></div>
<div style="display:flex;align-items:flex-end"><button class="btn btn-primary">Check</button></div></div></form></div>'''
    return web.Response(text=base_html(content, 'violators'), content_type='text/html')

async def page_connections(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    rows = ''
    for user, ip, node, ts in db.get_all_connections(100):
        t = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
        rows += f'<tr><td>{user}</td><td>{ip}</td><td>{node or "-"}</td><td>{t}</td></tr>'
    if not rows:
        rows = '<tr><td colspan="4" style="color:var(--muted)">No connections</td></tr>'
    
    content = f'''<div class="card"><h2>Recent Connections</h2>
<table><tr><th>User</th><th>IP</th><th>Node</th><th>Time</th></tr>{rows}</table></div>'''
    return web.Response(text=base_html(content, 'connections'), content_type='text/html')

async def page_nodes(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    msg = req.query.get('msg', '')
    alert = f'<div class="alert alert-ok">{msg}</div>' if msg else ''
    
    rows = ''
    for name, ip in get_nodes().items():
        ok = await check_node_health(ip)
        dot = 'dot-on' if ok else 'dot-off'
        st = 'badge-ok' if ok else 'badge-err'
        rows += f'''<tr><td><span class="dot {dot}"></span>{name}</td><td>{ip}</td>
        <td><span class="badge {st}">{"Online" if ok else "Offline"}</span></td>
        <td><form method="POST" action="/action/node_del" style="display:inline">
        <input type="hidden" name="name" value="{name}"><button class="btn btn-sm btn-danger">Delete</button></form></td></tr>'''
    if not rows:
        rows = '<tr><td colspan="4" style="color:var(--muted)">No nodes</td></tr>'
    
    content = f'''{alert}<div class="card"><h2>Add Node</h2><form method="POST" action="/action/node_add">
<div class="form-row"><div><label>Name</label><input name="name" placeholder="yandex1" required></div>
<div><label>IP</label><input name="ip" placeholder="51.250.70.247" required></div></div>
<button class="btn btn-primary">Add Node</button></form></div>
<div class="card"><h2>Nodes</h2><table><tr><th>Name</th><th>IP</th><th>Status</th><th>Action</th></tr>{rows}</table></div>'''
    return web.Response(text=base_html(content, 'nodes'), content_type='text/html')


async def page_logs(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    logs_html = ''.join(f'<div class="log-entry"><span class="log-time">{e["time"]}</span><span class="log-{e["level"]}">{e["level"]}</span><span>{e["msg"]}</span></div>' for e in list(admin_logs)[:100])
    if not logs_html:
        logs_html = '<p style="color:var(--muted)">No logs</p>'
    
    events_html = ''.join(f'<div class="event {e.get("level","")}">{e["time"]} - {e["msg"]} <span style="color:var(--muted)">{e["details"]}</span></div>' for e in list(events)[:50])
    if not events_html:
        events_html = '<p style="color:var(--muted)">No events</p>'
    
    content = f'''<div class="card"><h2>Events</h2><div style="max-height:300px;overflow-y:auto">{events_html}</div>
<form method="POST" action="/action/clear_events" style="margin-top:16px"><button class="btn btn-sm btn-ghost">Clear Events</button></form></div>
<div class="card"><h2>System Logs</h2><div class="logs">{logs_html}</div>
<form method="POST" action="/action/clear_logs" style="margin-top:16px"><button class="btn btn-sm btn-ghost">Clear Logs</button></form></div>'''
    return web.Response(text=base_html(content, 'logs'), content_type='text/html')

async def page_settings(req):
    if not await check_auth(req):
        return web.Response(text=login_html(), content_type='text/html')
    
    msg = req.query.get('msg', '')
    alert = f'<div class="alert alert-ok">{msg}</div>' if msg else ''
    
    # Get bot username
    bot_username = await get_bot_username()
    bot_info = f'<span class="badge badge-ok">@{bot_username}</span>' if bot_username else '<span class="badge badge-warn">Not configured</span>'
    
    content = f'''{alert}<form method="POST" action="/action/save_settings">
<div class="card"><h2>🔗 Remnawave API</h2>
<label>API URL</label><input name="REMNAWAVE_API_URL" value="{cfg('REMNAWAVE_API_URL')}" placeholder="https://panel.example.com">
<div class="form-hint">Full URL with https://</div>
<label>API Token</label><input name="REMNAWAVE_API_TOKEN" value="{cfg('REMNAWAVE_API_TOKEN')}" type="password" placeholder="JWT token"></div>

<div class="card"><h2>📱 Telegram</h2>
<div style="margin-bottom:16px">Bot: {bot_info}</div>
<label>Bot Token</label><input name="TELEGRAM_BOT_TOKEN" value="{cfg('TELEGRAM_BOT_TOKEN')}" placeholder="123456789:ABC...">
<div class="form-row">
<div><label>Chat ID 1</label><input name="TELEGRAM_CHAT_ID" value="{cfg('TELEGRAM_CHAT_ID')}" placeholder="123456789"></div>
<div><label>Chat ID 2 (optional)</label><input name="TELEGRAM_CHAT_ID_2" value="{cfg('TELEGRAM_CHAT_ID_2')}" placeholder="123456789"></div>
</div></div>

<div class="card"><h2>⚙️ Detection</h2>
<div class="form-row">
<div><label>IP Window (sec)</label><input name="IP_WINDOW_SECONDS" value="{cfg_int('IP_WINDOW_SECONDS',300)}" type="number"><div class="form-hint">Track IPs for this duration</div></div>
<div><label>Disable Duration (min)</label><input name="DISABLE_MINUTES" value="{cfg_int('DISABLE_MINUTES',10)}" type="number"><div class="form-hint">Disable subscription for</div></div>
</div>
<div class="form-row">
<div><label>Drop Duration (sec)</label><input name="DROP_DURATION_SECONDS" value="{cfg_int('DROP_DURATION_SECONDS',600)}" type="number"><div class="form-hint">Block IP on nodes for</div></div>
<div><label>Drop Cooldown (sec)</label><input name="DROP_COOLDOWN_SECONDS" value="{cfg_int('DROP_COOLDOWN_SECONDS',60)}" type="number"><div class="form-hint">Min time between drops</div></div>
</div>
<div class="form-row">
<div><label>Scan Interval (sec)</label><input name="SCAN_INTERVAL_SECONDS" value="{cfg_int('SCAN_INTERVAL_SECONDS',30)}" type="number"><div class="form-hint">Auto-scan frequency</div></div>
<div><label>Node Secret</label><input name="NODE_API_SECRET" value="{cfg('NODE_API_SECRET')}" type="password"></div>
</div>
<div class="form-row">
<div><label>Drop All IPs</label><select name="DROP_ALL_IPS"><option value="true" {"selected" if cfg('DROP_ALL_IPS','true').lower()=='true' else ""}>Yes - drop ALL IPs</option><option value="false" {"selected" if cfg('DROP_ALL_IPS','true').lower()=='false' else ""}>No - only excess IPs</option></select><div class="form-hint">Drop all IPs or only those exceeding limit</div></div>
<div></div>
</div></div>

<div class="card"><h2>🔐 Password</h2>
<label>New Password</label><input name="new_password" type="password" placeholder="Leave empty to keep current"></div>

<button class="btn btn-primary" style="width:100%">💾 Save Settings</button></form>'''
    return web.Response(text=base_html(content, 'settings'), content_type='text/html')


# ============ AUTH & ACTIONS ============
async def handle_login(req):
    if req.method == 'POST':
        data = await req.post()
        if hashlib.sha256(data.get('password', '').encode()).hexdigest() == get_pw_hash():
            sid = secrets.token_hex(16)
            sessions[sid] = time.time()
            resp = web.HTTPFound('/')
            resp.set_cookie('session', sid, max_age=86400)
            return resp
        return web.Response(text=login_html('Invalid password'), content_type='text/html')
    return web.Response(text=login_html(), content_type='text/html')

async def handle_logout(req):
    sid = req.cookies.get('session')
    sessions.pop(sid, None)
    resp = web.HTTPFound('/')
    resp.del_cookie('session')
    return resp

async def action_save_settings(req):
    data = await req.post()
    env = get_env_dict()
    env.update({
        'REMNAWAVE_API_URL': data.get('REMNAWAVE_API_URL', ''),
        'REMNAWAVE_API_TOKEN': data.get('REMNAWAVE_API_TOKEN', ''),
        'TELEGRAM_BOT_TOKEN': data.get('TELEGRAM_BOT_TOKEN', ''),
        'TELEGRAM_CHAT_ID': data.get('TELEGRAM_CHAT_ID', ''),
        'TELEGRAM_CHAT_ID_2': data.get('TELEGRAM_CHAT_ID_2', ''),
        'NODE_API_SECRET': data.get('NODE_API_SECRET', ''),
        'IP_WINDOW_SECONDS': data.get('IP_WINDOW_SECONDS', '300'),
        'DROP_DURATION_SECONDS': data.get('DROP_DURATION_SECONDS', '600'),
        'DROP_COOLDOWN_SECONDS': data.get('DROP_COOLDOWN_SECONDS', '60'),
        'SCAN_INTERVAL_SECONDS': data.get('SCAN_INTERVAL_SECONDS', '30'),
        'DISABLE_MINUTES': data.get('DISABLE_MINUTES', '10'),
        'DROP_ALL_IPS': data.get('DROP_ALL_IPS', 'true'),
        'SMART_DETECTION': data.get('SMART_DETECTION', 'true'),
        'CONCURRENT_WINDOW': data.get('CONCURRENT_WINDOW', '60'),

    })
    save_env(env)
    if data.get('new_password'):
        set_pw(data['new_password'])
    log("Settings saved")
    return web.HTTPFound('/settings?msg=Settings saved')

async def action_node_add(req):
    data = await req.post()
    name, ip = data.get('name', '').strip(), data.get('ip', '').strip()
    if name and ip:
        nodes = get_nodes()
        nodes[name] = ip
        env = get_env_dict()
        env['NODES'] = ','.join(f"{k}:{v}" for k, v in nodes.items())
        save_env(env)
        log(f"Node added: {name}")
        add_event(f"Node added: {name}", ip)
    return web.HTTPFound('/nodes?msg=Node added')

async def action_node_del(req):
    data = await req.post()
    name = data.get('name', '')
    nodes = get_nodes()
    if name in nodes:
        del nodes[name]
        env = get_env_dict()
        env['NODES'] = ','.join(f"{k}:{v}" for k, v in nodes.items())
        save_env(env)
        log(f"Node deleted: {name}")
    return web.HTTPFound('/nodes?msg=Node deleted')

async def action_scan(req):
    v = await scan_all_users()
    log(f"Manual scan: {v} violations")
    add_event(f"Manual scan", f"{v} violations")
    return web.HTTPFound(f'/?msg=Scan: {v} violations')

async def action_test_tg(req):
    await send_telegram("✅ Test from Connection Limiter")
    add_event("Telegram test sent")
    return web.HTTPFound('/?msg=Telegram test sent')

async def action_clear_db(req):
    db.clear()
    log("Database cleared")
    add_event("Database cleared")
    return web.HTTPFound('/?msg=Database cleared')

async def action_clear_events(req):
    events.clear()
    return web.HTTPFound('/logs')

async def action_clear_logs(req):
    admin_logs.clear()
    return web.HTTPFound('/logs')

async def action_drop_user(req):
    data = await req.post()
    user = data.get('user', '')
    if user:
        ips = db.get_user_ips(user)
        if ips:
            mins = cfg_int('DISABLE_MINUTES', 10)
            await disable_user_subscription(user, mins)
            for ip in ips:
                await drop_ip_on_all_nodes(ip)
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            await send_telegram(f"🔨 <b>Manual Drop</b>\n<i>{ts}</i>\n\nUser: <code>{user}</code>\nDropped: {len(ips)} IPs")
            log(f"Manual drop: {user}", 'WARNING')
            add_event(f"Manual drop: {user}", f"{len(ips)} IPs", 'violation')
    return web.HTTPFound('/violators?msg=User dropped')

async def action_check_user(req):
    data = await req.post()
    user_id = data.get('user_id', '').strip()
    if user_id:
        limit = await get_user_limit(user_id)
        ips = db.get_user_ips(user_id)
        msg = f"User {user_id}: {len(ips)} IPs, limit {limit if limit > 0 else 'unlimited'}"
        if limit > 0 and len(ips) > limit:
            await handle_violation(user_id, ips, limit)
            msg += " - ENFORCED"
        return web.HTTPFound(f'/violators?msg={msg}')
    return web.HTTPFound('/violators')

async def action_unban_user(req):
    data = await req.post()
    user_id = data.get('user', '').strip()
    if user_id:
        await enable_user_subscription(user_id)
        log(f"Manual unban: {user_id}")
        add_event(f"Manual unban: {user_id}", "", "info")
        return web.HTTPFound(f'/violators?msg=User {user_id} unbanned')
    return web.HTTPFound('/violators')

async def export_violators_csv(req):
    if not await check_auth(req):
        return web.HTTPFound('/')
    
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['user_id', 'ip_count', 'limit', 'status', 'ips'])
    
    for user, cnt, ips in db.get_violators():
        limit = await get_user_limit(user)
        if limit > 0 and cnt > limit:
            status = 'VIOLATION'
        elif limit > 0:
            status = 'OK'
        else:
            status = 'NO_LIMIT'
        writer.writerow([user, cnt, limit if limit > 0 else 'unlimited', status, ips])
    
    csv_content = output.getvalue()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    return web.Response(
        text=csv_content,
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="violators_{ts}.csv"'}

async def export_violators_html(req):
    if not await check_auth(req):
        return web.HTTPFound('/')
    
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    rows = ''
    total = 0
    violations = 0
    for user, cnt, ips in db.get_violators():
        limit = await get_user_limit(user)
        total += 1
        is_violation = limit > 0 and cnt > limit
        if is_violation:
            violations += 1
            status = '<span style="color:#ef4444;font-weight:bold">⚠️ VIOLATION</span>'
            row_style = 'background:#fef2f2;'
        elif limit > 0:
            status = '<span style="color:#22c55e">✓ OK</span>'
            row_style = ''
        else:
            status = '<span style="color:#f59e0b">No limit</span>'
            row_style = ''
        
        ips_list = ips.split(',') if ips else []
        ips_formatted = '<br>'.join(ips_list)
        
        rows += f'<tr style="{row_style}"><td>{user}</td><td>{cnt}</td><td>{limit if limit > 0 else "∞"}</td><td>{status}</td><td style="font-size:12px">{ips_formatted}</td></tr>'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Violators Report - {ts}</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; padding: 40px; background: #f8fafc; }}
h1 {{ color: #1e293b; margin-bottom: 8px; }}
.meta {{ color: #64748b; margin-bottom: 24px; }}
.stats {{ display: flex; gap: 24px; margin-bottom: 24px; }}
.stat {{ background: white; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #8b5cf6; }}
.stat-label {{ font-size: 12px; color: #64748b; text-transform: uppercase; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th {{ background: #8b5cf6; color: white; padding: 14px; text-align: left; font-weight: 600; }}
td {{ padding: 12px 14px; border-bottom: 1px solid #e2e8f0; }}
tr:hover {{ background: #f8fafc; }}
</style>
</head>
<body>
<h1>🔒 Connection Limiter Report</h1>
<p class="meta">Generated: {ts}</p>
<div class="stats">
<div class="stat"><div class="stat-value">{total}</div><div class="stat-label">Total Users</div></div>
<div class="stat"><div class="stat-value" style="color:#ef4444">{violations}</div><div class="stat-label">Violations</div></div>
</div>
<table>
<tr><th>User ID</th><th>IPs</th><th>Limit</th><th>Status</th><th>IP Addresses</th></tr>
{rows}
</table>
</body>
</html>'''
    
    return web.Response(
        text=html,
        content_type='text/html',
        headers={'Content-Disposition': f'attachment; filename="violators_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html"'}
    )


# ============ BACKGROUND TASKS ============
async def scanner_task():
    while True:
        await asyncio.sleep(cfg_int('SCAN_INTERVAL_SECONDS', 30))
        try:
            v = await scan_all_users()
            if v > 0:
                log(f"Auto-scan: {v} violations", 'WARNING')
        except Exception as e:
            log(f"Scanner error: {e}", 'ERROR')

async def cleanup_task():
    while True:
        await asyncio.sleep(60)
        try:
            db.cleanup()
            now = time.time()
            for uid, exp in list(disabled_users.items()):
                if now >= exp:
                    await enable_user_subscription(uid)
            expired = [s for s, t in sessions.items() if now - t > 86400]
            for s in expired:
                sessions.pop(s, None)
        except Exception as e:
            log(f"Cleanup error: {e}", 'ERROR')

# ============ MAIN ============
async def main():
    log("=" * 50)
    log("Connection Limiter v2 Starting")
    log("=" * 50)
    log(f"API: {cfg('REMNAWAVE_API_URL')}")
    log(f"Nodes: {list(get_nodes().keys())}")
    log(f"IP Window: {cfg_int('IP_WINDOW_SECONDS', 300)}s")
    log(f"Disable: {cfg_int('DISABLE_MINUTES', 10)} min")
    
    app = web.Application()
    
    # API
    app.router.add_post('/log', handle_log_single)
    app.router.add_post('/log_upload', handle_log_upload)
    app.router.add_get('/health', handle_health)
    
    # Pages
    app.router.add_get('/', page_dashboard)
    app.router.add_post('/', handle_login)
    app.router.add_get('/violators', page_violators)
    app.router.add_get('/connections', page_connections)
    app.router.add_get('/nodes', page_nodes)
    app.router.add_get('/logs', page_logs)
    app.router.add_get('/settings', page_settings)
    app.router.add_get('/logout', handle_logout)
    
    # Actions
    app.router.add_post('/action/save_settings', action_save_settings)
    app.router.add_post('/action/node_add', action_node_add)
    app.router.add_post('/action/node_del', action_node_del)
    app.router.add_post('/action/scan', action_scan)
    app.router.add_post('/action/test_tg', action_test_tg)
    app.router.add_post('/action/clear_db', action_clear_db)
    app.router.add_post('/action/clear_events', action_clear_events)
    app.router.add_post('/action/clear_logs', action_clear_logs)
    app.router.add_post('/action/drop_user', action_drop_user)
    app.router.add_post('/action/check_user', action_check_user)
    app.router.add_post('/action/unban_user', action_unban_user)
    app.router.add_get('/export/violators.csv', export_violators_csv)
    app.router.add_get('/export/violators.html', export_violators_html)
    
    asyncio.create_task(scanner_task())
    asyncio.create_task(cleanup_task())
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 5000).start()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
    
    log("Log receiver: http://0.0.0.0:5000")
    log("Admin panel:  http://0.0.0.0:8080")
    log("Ready!")
    add_event("Server started", f"{len(get_nodes())} nodes")
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
