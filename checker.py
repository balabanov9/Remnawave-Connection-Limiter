"""Main connection checker logic - simple IP drop version"""

import asyncio
import time
import logging
import aiohttp
from database import (
    init_db, get_all_active_users, get_unique_ips_with_ports,
    cleanup_old_connections, get_db_stats
)
from remnawave_api import RemnawaveAPI
from telegram_bot import notifier
from events_log import log_drop, log_error, log_info
from config import (
    CHECK_INTERVAL_SECONDS, DROP_DURATION_SECONDS,
    NODE_API_SECRET, NODE_API_PORT, NODES
)

logger = logging.getLogger(__name__)


class ConnectionChecker:
    def __init__(self):
        self.api = RemnawaveAPI()
        self.running = False

    async def drop_ips_on_all_nodes(self, ip_port_list: list):
        """Send drop commands to ALL nodes
        ip_port_list: list of tuples (ip, port)
        """
        if not NODES:
            logger.warning("NODES config is empty, cannot drop IPs")
            return
        
        async with aiohttp.ClientSession() as session:
            for node_name, node_ip in NODES.items():
                for ip, port in ip_port_list:
                    try:
                        url = f"http://{node_ip}:{NODE_API_PORT}/block_ip"
                        payload = {
                            "ip": ip,
                            "port": port,
                            "duration": DROP_DURATION_SECONDS,
                            "secret": NODE_API_SECRET
                        }
                        
                        async with session.post(
                            url,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            block_key = f"{ip}:{port}" if port else ip
                            if resp.status == 200:
                                logger.info(f"DROP {block_key} on {node_name}")
                            else:
                                logger.warning(f"Failed to drop {block_key} on {node_name}: {resp.status}")
                    except Exception as e:
                        logger.warning(f"Could not reach node {node_name}: {e}")

    async def check_user(self, username: str):
        """Check user and drop excess connections if IP > HWID limit"""
        # Получаем все IP:port для юзера
        ip_port_list = get_unique_ips_with_ports(username)
        
        if not ip_port_list:
            return
        
        # Считаем уникальные IP (без портов)
        unique_ips = list(set(ip for ip, port in ip_port_list))
        ip_count = len(unique_ips)
        
        # Получаем лимит устройств
        device_limit = await self.api.get_user_hwid_limit(username)
        
        # Логируем для отладки если больше 1 IP
        if ip_count > 1:
            logger.info(f"User {username}: {ip_count} IPs, limit: {device_limit}")
        
        if device_limit is None or device_limit == 0:
            # Нет лимита - пропускаем
            if ip_count > 1:
                logger.info(f"User {username}: no limit set, skipping")
            return
        
        if ip_count <= device_limit:
            # Всё ок, в пределах лимита
            return
        
        # Превышение! Дропаем лишние соединения
        excess_count = ip_count - device_limit
        logger.warning(f"EXCESS! User {username}: {ip_count} IPs, limit: {device_limit}, dropping {excess_count}")
        
        # Сортируем IP по количеству соединений (дропаем те что меньше соединений - скорее всего новые)
        ip_connections = {}
        for ip, port in ip_port_list:
            if ip not in ip_connections:
                ip_connections[ip] = []
            ip_connections[ip].append((ip, port))
        
        # Сортируем: сначала IP с меньшим количеством соединений
        sorted_ips = sorted(ip_connections.keys(), key=lambda x: len(ip_connections[x]))
        
        # Берём лишние IP для дропа
        ips_to_drop = sorted_ips[:excess_count]
        
        # Собираем все IP:port для дропа
        connections_to_drop = []
        for ip in ips_to_drop:
            connections_to_drop.extend(ip_connections[ip])
        
        logger.warning(f"DROP User {username}: dropping IPs {ips_to_drop}")
        
        # Логируем событие для админки
        log_drop(username, ip_count, device_limit, ips_to_drop)
        
        # Отправляем в телеграм
        await notifier.notify_drop(username, ip_count, device_limit, ips_to_drop)
        
        # Дропаем на всех нодах
        await self.drop_ips_on_all_nodes(connections_to_drop)

    async def run_check_cycle(self):
        """Run one check cycle"""
        logger.info(f"=== Check cycle at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

        active_users = get_all_active_users()
        logger.info(f"Checking {len(active_users)} active users")

        for username in active_users:
            try:
                await self.check_user(username)
            except Exception as e:
                logger.error(f"Error checking {username}: {e}")

        # Очистка старых записей (держим 3 минуты для надёжности)
        cleanup_old_connections(max_age_seconds=180)
        
        stats = get_db_stats()
        logger.info(f"DB stats: {stats['total_connections']} connections")

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

    def stop(self):
        self.running = False
        logger.info("Connection checker stopped")


async def run_checker():
    checker = ConnectionChecker()
    await checker.start()


if __name__ == '__main__':
    asyncio.run(run_checker())
