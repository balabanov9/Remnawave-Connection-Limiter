"""Log server - receives connections and checks violations in real-time"""

import asyncio
import logging
import time
import aiohttp
from aiohttp import web
from database import init_db, log_connection, get_unique_ips_for_user, cleanup_old_connections
from config import (
    LOG_SERVER_HOST, LOG_SERVER_PORT, DROP_DURATION_SECONDS,
    NODE_API_SECRET, NODE_API_PORT, NODES,
    REMNAWAVE_API_URL, REMNAWAVE_API_TOKEN, IP_WINDOW_SECONDS
)
from telegram_bot import notifier
from events_log import log_drop

logger = logging.getLogger(__name__)

# Cache for user limits
_limit_cache = {}
CACHE_TTL = 300

# Track recently dropped to avoid spam
_recently_dropped = {}  # user -> timestamp


async def get_user_limit(session: aiohttp.ClientSession, username: str) -> int | None:
    """Get user HWID limit with caching"""
    now = time.time()
    
    if username in _limit_cache:
        limit, ts = _limit_cache[username]
        if now - ts < CACHE_TTL:
            return limit
    
    try:
        url = f"{REMNAWAVE_API_URL}/api/users/by-id/{username}"
        headers = {"Authorization": f"Bearer {REMNAWAVE_API_TOKEN}"}
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status == 200:
                data = await resp.json()
                user = data.get('response', data)
                limit = user.get('hwidDeviceLimit') or 0
                _limit_cache[username] = (limit, now)
                return limit if limit > 0 else None
    except:
        pass
    
    return None


async def drop_ip_on_nodes(session: aiohttp.ClientSession, ip: str):
    """Send DROP command to all nodes"""
    if not NODES:
        return
    
    tasks = []
    for node_name, node_ip in NODES.items():
        tasks.append(_drop_on_node(session, node_name, node_ip, ip))
    
    await asyncio.gather(*tasks, return_exceptions=True)


async def _drop_on_node(session, node_name, node_ip, ip):
    try:
        url = f"http://{node_ip}:{NODE_API_PORT}/block_ip"
        payload = {"ip": ip, "duration": DROP_DURATION_SECONDS, "secret": NODE_API_SECRET}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2)) as resp:
            if resp.status == 200:
                logger.info(f"DROP {ip} on {node_name}")
    except:
        pass


async def check_and_drop(session: aiohttp.ClientSession, username: str, ip: str, node_name: str):
    """Check user and drop if violation - called on every new connection"""
    now = time.time()
    
    # Skip if recently dropped this user (avoid spam)
    if username in _recently_dropped:
        if now - _recently_dropped[username] < 30:
            return
    
    # Get all IPs for this user
    user_ips = get_unique_ips_for_user(username)
    ip_count = len(user_ips)
    
    if ip_count <= 1:
        return
    
    # Get limit
    limit = await get_user_limit(session, username)
    
    if limit is None or limit == 0:
        return
    
    if ip_count <= limit:
        return
    
    # VIOLATION! Drop the newest IP (current one)
    _recently_dropped[username] = now
    
    logger.warning(f"VIOLATION! User {username}: {ip_count} IPs, limit: {limit}, dropping {ip}")
    
    log_drop(username, ip_count, limit, [ip])
    
    # Drop and notify in parallel
    await asyncio.gather(
        drop_ip_on_nodes(session, ip),
        notifier.notify_drop(username, ip_count, limit, [ip]),
        return_exceptions=True
    )


class LogServer:
    def __init__(self):
        self.app = web.Application()
        self.app.router.add_post('/log', self.handle_log)
        self.app.router.add_post('/log_batch', self.handle_log_batch)
        self.app.router.add_get('/health', self.handle_health)
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def handle_health(self, request):
        return web.json_response({"status": "ok"})
    
    async def handle_log(self, request):
        """Handle single connection - check immediately"""
        try:
            data = await request.json()
            username = data.get('user_email', '').replace('user_', '')
            ip = data.get('ip_address')
            node_name = data.get('node_name', 'unknown')
            
            if username and ip:
                log_connection(username, ip, None, node_name)
                
                session = await self.get_session()
                asyncio.create_task(check_and_drop(session, username, ip, node_name))
            
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error handling log: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def handle_log_batch(self, request):
        """Handle batch of connections - check each one"""
        try:
            data = await request.json()
            connections = data.get('connections', [])
            
            session = await self.get_session()
            
            for conn in connections:
                username = conn.get('user_email', '').replace('user_', '')
                ip = conn.get('ip_address')
                node_name = conn.get('node_name', 'unknown')
                
                if username and ip:
                    log_connection(username, ip, None, node_name)
                    asyncio.create_task(check_and_drop(session, username, ip, node_name))
            
            return web.json_response({"status": "ok", "count": len(connections)})
        except Exception as e:
            logger.error(f"Error handling batch: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def cleanup_task(self):
        """Periodic cleanup of old connections"""
        while True:
            try:
                cleanup_old_connections(max_age_seconds=IP_WINDOW_SECONDS + 60)
            except:
                pass
            await asyncio.sleep(30)
    
    async def start(self):
        init_db()
        asyncio.create_task(self.cleanup_task())
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, LOG_SERVER_HOST, LOG_SERVER_PORT)
        await site.start()
        
        logger.info(f"Log server started on {LOG_SERVER_HOST}:{LOG_SERVER_PORT}")


# For backwards compatibility with Flask import
app = None


async def run_server():
    server = LogServer()
    await server.start()
    while True:
        await asyncio.sleep(3600)
