"""Main connection checker logic - optimized with parallel requests"""

import asyncio
import time
import logging
import aiohttp
from database import (
    init_db, get_all_active_users, get_unique_ips_with_ports,
    cleanup_old_connections, get_db_stats, get_users_with_multiple_ips
)
from telegram_bot import notifier
from events_log import log_drop
from config import (
    CHECK_INTERVAL_SECONDS, DROP_DURATION_SECONDS,
    NODE_API_SECRET, NODE_API_PORT, NODES,
    REMNAWAVE_API_URL, REMNAWAVE_API_TOKEN
)

logger = logging.getLogger(__name__)

# Cache for user limits (username -> (limit, timestamp))
_limit_cache = {}
CACHE_TTL = 300  # 5 minutes


class ConnectionChecker:
    def __init__(self):
        self.running = False
        self.session = None

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_user_limit(self, username: str) -> int | None:
        """Get user HWID limit with caching"""
        now = time.time()
        
        # Check cache
        if username in _limit_cache:
            limit, ts = _limit_cache[username]
            if now - ts < CACHE_TTL:
                return limit
        
        # Fetch from API
        try:
            session = await self.get_session()
            url = f"{REMNAWAVE_API_URL}/api/users/by-id/{username}"
            headers = {"Authorization": f"Bearer {REMNAWAVE_API_TOKEN}"}
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user = data.get('response', data)
                    limit = user.get('hwidDeviceLimit') or 0
                    _limit_cache[username] = (limit, now)
                    return limit if limit > 0 else None
        except Exception as e:
            logger.debug(f"API error for {username}: {e}")
        
        return None

    async def check_user(self, username: str, ip_data: list):
        """Check single user - ip_data is list of (ip, port) tuples"""
        unique_ips = list(set(ip for ip, port in ip_data))
        ip_count = len(unique_ips)
        
        if ip_count <= 1:
            return
        
        # Get limit
        device_limit = await self.get_user_limit(username)
        
        logger.info(f"User {username}: {ip_count} IPs, limit: {device_limit}")
        
        if device_limit is None or device_limit == 0:
            return
        
        if ip_count <= device_limit:
            return
        
        # Excess! Drop extra connections
        excess_count = ip_count - device_limit
        logger.warning(f"EXCESS! User {username}: {ip_count} IPs, limit: {device_limit}, dropping {excess_count}")
        
        # Group by IP
        ip_connections = {}
        for ip, port in ip_data:
            if ip not in ip_connections:
                ip_connections[ip] = []
            ip_connections[ip].append((ip, port))
        
        # Sort: drop IPs with fewer connections first (likely newer)
        sorted_ips = sorted(ip_connections.keys(), key=lambda x: len(ip_connections[x]))
        ips_to_drop = sorted_ips[:excess_count]
        
        connections_to_drop = []
        for ip in ips_to_drop:
            connections_to_drop.extend(ip_connections[ip])
        
        logger.warning(f"DROP User {username}: IPs {ips_to_drop}")
        
        log_drop(username, ip_count, device_limit, ips_to_drop)
        await notifier.notify_drop(username, ip_count, device_limit, ips_to_drop)
        await self.drop_ips_on_all_nodes(connections_to_drop)

    async def drop_ips_on_all_nodes(self, ip_port_list: list):
        """Send drop commands to all nodes in parallel"""
        if not NODES or not ip_port_list:
            return
        
        session = await self.get_session()
        tasks = []
        
        for node_name, node_ip in NODES.items():
            for ip, port in ip_port_list:
                tasks.append(self._drop_single(session, node_name, node_ip, ip, port))
        
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _drop_single(self, session, node_name, node_ip, ip, port):
        try:
            url = f"http://{node_ip}:{NODE_API_PORT}/block_ip"
            payload = {"ip": ip, "port": port, "duration": DROP_DURATION_SECONDS, "secret": NODE_API_SECRET}
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                block_key = f"{ip}:{port}" if port else ip
                if resp.status == 200:
                    logger.info(f"DROP {block_key} on {node_name}")
                else:
                    logger.warning(f"Failed drop {block_key} on {node_name}: {resp.status}")
        except:
            pass

    async def run_check_cycle(self):
        """Run one check cycle - only check users with multiple IPs"""
        start = time.time()
        logger.info(f"=== Check cycle at {time.strftime('%H:%M:%S')} ===")

        # Get only users with >1 unique IP (much faster)
        users_data = get_users_with_multiple_ips()
        
        if not users_data:
            logger.info("No users with multiple IPs")
        else:
            logger.info(f"Checking {len(users_data)} users with multiple IPs")
            
            # Check users in parallel batches
            batch_size = 20
            for i in range(0, len(users_data), batch_size):
                batch = users_data[i:i+batch_size]
                tasks = [self.check_user(username, ip_data) for username, ip_data in batch]
                await asyncio.gather(*tasks, return_exceptions=True)

        cleanup_old_connections(max_age_seconds=120)
        
        elapsed = time.time() - start
        stats = get_db_stats()
        logger.info(f"Cycle done in {elapsed:.1f}s, DB: {stats['total_connections']} connections")

    async def start(self):
        """Start the checker loop"""
        self.running = True
        init_db()
        logger.info("Connection checker started")
        logger.info(f"Check interval: {CHECK_INTERVAL_SECONDS}s")

        while self.running:
            try:
                await self.run_check_cycle()
            except Exception as e:
                logger.error(f"Check cycle error: {e}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def stop(self):
        self.running = False
        if self.session:
            await self.session.close()
        logger.info("Connection checker stopped")


async def run_checker():
    checker = ConnectionChecker()
    await checker.start()


if __name__ == '__main__':
    asyncio.run(run_checker())
