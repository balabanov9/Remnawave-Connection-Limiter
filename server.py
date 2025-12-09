#!/usr/bin/env python3
"""
Connection Limiter Server
- Receives connections from nodes in real-time
- Checks HWID limits via Remnawave API
- Sends DROP commands to nodes
- Telegram notifications
"""

import asyncio
import os
import time
import logging
import sqlite3
import hashlib
import secrets
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout

# ============ CONFIG ============

def load_env():
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

API_URL = os.getenv('REMNAWAVE_API_URL', '')
API_TOKEN = os.getenv('REMNAWAVE_API_TOKEN', '')
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.getenv('TELEGRAM_CHAT_ID', '')
NODE_SECRET = os.getenv('NODE_API_SECRET', 'secret')
DROP_DURATION = int(os.getenv('DROP_DURATION_SECONDS', '60'))
IP_WINDOW = int(os.getenv('IP_WINDOW_SECONDS', '60'))

def get_nodes():
    nodes_str = os.getenv('NODES', '')
    if not nodes_str:
        return {}
    result = {}
    for item in nodes_str.split(','):
        if ':' in item:
            name, ip = item.split(':', 1)
            result[name.strip()] = ip.strip()
    return result

# ============ LOGGING ============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger('server')

# ============ DATABASE (in-memory for speed) ============

class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.conn.execute('''
            CREATE TABLE connections (
                user TEXT, ip TEXT, ts INTEGER,
                PRIMARY KEY (user, ip)
            )
        ''')
        self.conn.execute('CREATE INDEX idx_ts ON connections(ts)')
    
    def add(self, user: str, ip: str):
        now = int(time.time())
        self.conn.execute(
            'INSERT OR REPLACE INTO connections VALUES (?, ?, ?)',
            (user, ip, now)
        )
        self.conn.commit()
    
    def get_ips(self, user: str) -> list:
        cutoff = int(time.time()) - IP_WINDOW
        cur = self.conn.execute(
            'SELECT DISTINCT ip FROM connections WHERE user = ? AND ts > ?',
            (user, cutoff)
        )
        return [r[0] for r in cur.fetchall()]
    
    def cleanup(self):
        cutoff = int(time.time()) - IP_WINDOW - 60
        self.conn.execute('DELETE FROM connections WHERE ts < ?', (cutoff,))
        self.conn.commit()
    
    def stats(self):
        cur = self.conn.execute('SELECT COUNT(*) FROM connections')
        total = cur.fetchone()[0]
        cutoff = int(time.time()) - IP_WINDOW
        cur = self.conn.execute('SELECT COUNT(DISTINCT user) FROM connections WHERE ts > ?', (cutoff,))
        users = cur.fetchone()[0]
        return {'connections': total, 'users': users}

db = DB()

# ============ CACHE ============

limit_cache = {}  # user -> (limit, timestamp)
CACHE_TTL = 300

recently_dropped = {}  # user -> timestamp
DROP_COOLDOWN = 30

# ============ API CLIENT ============

http: ClientSession = None

async def get_http():
    global http
    if http is None or http.closed:
        http = ClientSession(timeout=ClientTimeout(total=5))
    return http

async def get_limit(user: str) -> int:
    """Get HWID limit from Remnawave API with caching"""
    now = time.time()
    
    if user in limit_cache:
        limit, ts = limit_cache[user]
        if now - ts < CACHE_TTL:
            return limit
    
    if not API_URL or not API_TOKEN:
        return 0
    
    try:
        session = await get_http()
        async with session.get(
            f"{API_URL}/api/users/by-id/{user}",
            headers={"Authorization": f"Bearer {API_TOKEN}"}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                user_data = data.get('response', data)
                limit = user_data.get('hwidDeviceLimit') or 0
                limit_cache[user] = (limit, now)
                return limit
    except Exception as e:
        log.debug(f"API error: {e}")
    
    return 0

async def send_telegram(text: str):
    """Send Telegram notification"""
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        session = await get_http()
        await session.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"}
        )
    except:
        pass

async def drop_on_node(node_ip: str, ip: str):
    """Send DROP command to node"""
    try:
        session = await get_http()
        await session.post(
            f"http://{node_ip}:5001/block",
            json={"ip": ip, "duration": DROP_DURATION, "secret": NODE_SECRET}
        )
    except:
        pass

async def drop_ip(ip: str):
    """Drop IP on all nodes"""
    nodes = get_nodes()
    if nodes:
        await asyncio.gather(*[drop_on_node(node_ip, ip) for node_ip in nodes.values()])

# ============ CORE LOGIC ============

async def check_user(user: str, ip: str):
    """Check user and drop if violation"""
    now = time.time()
    
    # Cooldown check
    if user in recently_dropped and now - recently_dropped[user] < DROP_COOLDOWN:
        return
    
    # Get all IPs for user
    ips = db.get_ips(user)
    if len(ips) <= 1:
        return
    
    # Get limit
    limit = await get_limit(user)
    if limit <= 0:
        return
    
    if len(ips) <= limit:
        return
    
    # VIOLATION!
    recently_dropped[user] = now
    log.warning(f"VIOLATION: {user} has {len(ips)} IPs, limit {limit}, dropping {ip}")
    
    # Drop and notify
    await asyncio.gather(
        drop_ip(ip),
        send_telegram(f"🔻 <b>Drop:</b> User {user}\nIPs: {len(ips)}, Limit: {limit}\nDropped: {ip}")
    )

# ============ HTTP SERVER ============

async def handle_connection(request):
    """Handle incoming connection from node"""
    try:
        data = await request.json()
        user = data.get('user', '').replace('user_', '')
        ip = data.get('ip', '')
        
        if user and ip:
            db.add(user, ip)
            asyncio.create_task(check_user(user, ip))
        
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_health(request):
    return web.json_response({"status": "ok", **db.stats()})

async def handle_stats(request):
    return web.json_response(db.stats())

# ============ ADMIN PANEL ============

ADMIN_PASSWORD_FILE = Path(__file__).parent / '.admin_password'

def get_password_hash():
    if ADMIN_PASSWORD_FILE.exists():
        return ADMIN_PASSWORD_FILE.read_text().strip()
    h = hashlib.sha256(b'admin').hexdigest()
    ADMIN_PASSWORD_FILE.write_text(h)
    return h

sessions = {}

ADMIN_HTML = '''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connection Limiter</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:20px}
.container{max-width:900px;margin:0 auto}
h1{color:#38bdf8;margin-bottom:20px}
.card{background:#1e293b;border-radius:12px;padding:20px;margin-bottom:20px}
.card h2{color:#38bdf8;margin-bottom:15px;font-size:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:15px;margin-bottom:20px}
.stat{background:#0f172a;padding:15px;border-radius:8px;text-align:center}
.stat-value{font-size:28px;font-weight:bold;color:#38bdf8}
.stat-label{font-size:12px;color:#64748b;margin-top:5px}
.status{display:inline-block;padding:4px 10px;border-radius:4px;font-size:12px}
.status-ok{background:#22c55e;color:#000}
.status-err{background:#ef4444}
table{width:100%;border-collapse:collapse}
th,td{padding:10px;text-align:left;border-bottom:1px solid #334155}
th{color:#64748b;font-weight:normal}
.btn{background:#38bdf8;color:#000;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:bold}
.btn:hover{background:#0ea5e9}
.btn-danger{background:#ef4444;color:#fff}
input{width:100%;padding:10px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#fff;margin-bottom:10px}
.events{max-height:300px;overflow-y:auto}
.event{padding:8px;border-bottom:1px solid #334155;font-size:13px}
.login-box{max-width:400px;margin:100px auto}
</style>
</head><body>
<div class="container">
%CONTENT%
</div>
<script>
setTimeout(()=>location.reload(), 10000);
</script>
</body></html>'''

LOGIN_HTML = '''
<div class="login-box card">
<h1 style="text-align:center">🔒 Connection Limiter</h1>
<form method="POST" style="margin-top:20px">
<input type="password" name="password" placeholder="Password" autofocus>
<button class="btn" style="width:100%">Login</button>
</form>
<p style="text-align:center;margin-top:15px;color:#64748b;font-size:12px">Default: admin</p>
</div>'''

def render_dashboard(stats, nodes, api_ok, tg_ok):
    nodes_html = ''
    for name, ip in nodes.items():
        nodes_html += f'<tr><td>{name}</td><td>{ip}</td><td><span class="status status-ok">Online</span></td></tr>'
    
    if not nodes:
        nodes_html = '<tr><td colspan="3" style="color:#64748b">No nodes configured</td></tr>'
    
    return f'''
<h1>🔒 Connection Limiter</h1>
<div class="stats">
<div class="stat"><div class="stat-value">{stats["connections"]}</div><div class="stat-label">Connections</div></div>
<div class="stat"><div class="stat-value">{stats["users"]}</div><div class="stat-label">Active Users</div></div>
<div class="stat"><div class="stat-value">{len(nodes)}</div><div class="stat-label">Nodes</div></div>
<div class="stat"><div class="stat-value">{IP_WINDOW}s</div><div class="stat-label">IP Window</div></div>
</div>
<div class="card">
<h2>Status</h2>
<p>Remnawave API: <span class="status {"status-ok" if api_ok else "status-err"}">{"OK" if api_ok else "Error"}</span></p>
<p style="margin-top:10px">Telegram: <span class="status {"status-ok" if tg_ok else "status-err"}">{"OK" if tg_ok else "Not configured"}</span></p>
</div>
<div class="card">
<h2>Nodes</h2>
<table><tr><th>Name</th><th>IP</th><th>Status</th></tr>{nodes_html}</table>
</div>
'''

async def handle_admin(request):
    session_id = request.cookies.get('session')
    
    if request.method == 'POST':
        data = await request.post()
        password = data.get('password', '')
        if hashlib.sha256(password.encode()).hexdigest() == get_password_hash():
            session_id = secrets.token_hex(16)
            sessions[session_id] = time.time()
            resp = web.HTTPFound('/')
            resp.set_cookie('session', session_id)
            return resp
        return web.Response(text=ADMIN_HTML.replace('%CONTENT%', LOGIN_HTML), content_type='text/html')
    
    if not session_id or session_id not in sessions:
        return web.Response(text=ADMIN_HTML.replace('%CONTENT%', LOGIN_HTML), content_type='text/html')
    
    # Check API
    api_ok = False
    if API_URL and API_TOKEN:
        try:
            session = await get_http()
            async with session.get(f"{API_URL}/api/system/stats", headers={"Authorization": f"Bearer {API_TOKEN}"}) as r:
                api_ok = r.status == 200
        except:
            pass
    
    tg_ok = bool(TG_TOKEN and TG_CHAT)
    
    content = render_dashboard(db.stats(), get_nodes(), api_ok, tg_ok)
    return web.Response(text=ADMIN_HTML.replace('%CONTENT%', content), content_type='text/html')

# ============ MAIN ============

async def cleanup_task():
    while True:
        db.cleanup()
        await asyncio.sleep(60)

async def main():
    log.info("Starting Connection Limiter Server")
    log.info(f"API: {API_URL}")
    log.info(f"Nodes: {list(get_nodes().keys())}")
    
    app = web.Application()
    app.router.add_post('/log', handle_connection)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/stats', handle_stats)
    app.router.add_get('/', handle_admin)
    app.router.add_post('/', handle_admin)
    
    asyncio.create_task(cleanup_task())
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Log server on 5000
    await web.TCPSite(runner, '0.0.0.0', 5000).start()
    log.info("Log server: http://0.0.0.0:5000")
    
    # Admin on 8080
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
    log.info("Admin panel: http://0.0.0.0:8080")
    
    log.info("Ready!")
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
