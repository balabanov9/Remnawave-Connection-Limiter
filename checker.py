"""Main connection checker logic (async version)"""

import asyncio
import time
import aiohttp
from database import (
    init_db, get_all_active_users, get_unique_ips,
    add_blocked_user, get_users_to_unblock, remove_blocked_user,
    is_user_blocked, cleanup_old_connections, get_db_stats
)
from remnawave_api import RemnawaveAPI
from telegram_bot import notifier
from config import (
    CHECK_INTERVAL_SECONDS, BLOCK_DURATION_SECONDS,
    NODE_API_SECRET, NODE_API_PORT, KICK_IPS_ON_VIOLATION, NODES,
    VIOLATION_CONFIRM_COUNT
)


class ConnectionChecker:
    def __init__(self):
        self.api = RemnawaveAPI()
        self.running = False
        # Счётчик нарушений для каждого юзера {username: count}
        # Нужно несколько подряд нарушений чтобы забанить
        self.violation_counts = {}

    async def kick_ips_from_all_nodes(self, ips: list):
        """Send block commands to ALL nodes to kick IPs"""
        if not KICK_IPS_ON_VIOLATION:
            return
        
        if not NODES:
            print("[WARN] NODES config is empty, cannot kick IPs")
            return
        
        async with aiohttp.ClientSession() as session:
            for node_name, node_ip in NODES.items():
                for ip in ips:
                    try:
                        url = f"http://{node_ip}:{NODE_API_PORT}/block_ip"
                        async with session.post(
                            url,
                            json={
                                "ip": ip,
                                "duration": BLOCK_DURATION_SECONDS,
                                "secret": NODE_API_SECRET
                            },
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            if resp.status == 200:
                                print(f"[KICK] Blocked {ip} on {node_name}")
                            else:
                                print(f"[WARN] Failed to block {ip} on {node_name}: {resp.status}")
                    except Exception as e:
                        print(f"[WARN] Could not reach node {node_name}: {e}")

    async def check_user(self, username: str):
        """Check single user for connection limit violation"""
        if is_user_blocked(username):
            # Сбрасываем счётчик для заблокированных
            self.violation_counts.pop(username, None)
            return

        unique_ips = get_unique_ips(username)
        ip_count = len(unique_ips)

        if ip_count == 0:
            # Нет активности — сбрасываем счётчик
            self.violation_counts.pop(username, None)
            return

        device_limit = await self.api.get_user_device_limit(username)

        if ip_count > device_limit:
            # Увеличиваем счётчик нарушений
            self.violation_counts[username] = self.violation_counts.get(username, 0) + 1
            current_count = self.violation_counts[username]
            
            print(f"[CHECK] User {username}: {ip_count} IPs, limit: {device_limit}, violations: {current_count}/{VIOLATION_CONFIRM_COUNT}")
            
            # Проверяем достаточно ли нарушений подряд
            if current_count < VIOLATION_CONFIRM_COUNT:
                print(f"[WARN] User {username} exceeds limit, waiting for confirmation ({current_count}/{VIOLATION_CONFIRM_COUNT})")
                return
            
            # Подтверждённое нарушение!
            print(f"[VIOLATION] User {username} confirmed: {ip_count} IPs, limit: {device_limit}")
            print(f"[VIOLATION] IPs: {unique_ips}")

            # Сбрасываем счётчик
            self.violation_counts.pop(username, None)

            # Отправляем warning в телеграм
            await notifier.notify_warning(username, ip_count, device_limit, unique_ips)

            # Кикаем IP на ВСЕХ нодах
            await self.kick_ips_from_all_nodes(unique_ips)

            user_uuid = await self.api.get_user_uuid(username)
            if not user_uuid:
                print(f"[ERROR] Could not get UUID for user {username}")
                return

            current_status = await self.api.get_user_status(username)

            if await self.api.disable_user(user_uuid):
                blocked_until = int(time.time()) + BLOCK_DURATION_SECONDS
                add_blocked_user(username, blocked_until, current_status)
                print(f"[BLOCKED] User {username} for {BLOCK_DURATION_SECONDS}s")
                
                await notifier.notify_disabled(username)
        else:
            # Нет нарушения — сбрасываем счётчик
            self.violation_counts.pop(username, None)

    async def unblock_expired(self):
        """Unblock users whose block time has expired"""
        users_to_unblock = get_users_to_unblock()

        for username, original_status in users_to_unblock:
            print(f"[UNBLOCK] Unblocking user {username}")

            user_uuid = await self.api.get_user_uuid(username)
            if not user_uuid:
                print(f"[ERROR] Could not get UUID for {username}")
                remove_blocked_user(username)
                continue

            if await self.api.enable_user(user_uuid):
                remove_blocked_user(username)
                print(f"[UNBLOCKED] User {username} is now active")
                await notifier.notify_enabled(username)

    async def run_check_cycle(self):
        """Run one check cycle"""
        print(f"[CYCLE] Check at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        await self.unblock_expired()

        active_users = get_all_active_users()
        print(f"[CYCLE] Checking {len(active_users)} active users")

        for username in active_users:
            try:
                await self.check_user(username)
            except Exception as e:
                print(f"[ERROR] Error checking {username}: {e}")

        # Очистка старых записей
        cleanup_old_connections(max_age_seconds=120)
        
        stats = get_db_stats()
        print(f"[STATS] DB: {stats['total_connections']} connections, {stats['blocked_users']} blocked, pending violations: {len(self.violation_counts)}")

    async def start(self):
        """Start the checker loop"""
        self.running = True
        init_db()
        print("[START] Connection checker started")
        print(f"[CONFIG] Check interval: {CHECK_INTERVAL_SECONDS}s, Confirm count: {VIOLATION_CONFIRM_COUNT}")

        while self.running:
            try:
                await self.run_check_cycle()
            except Exception as e:
                print(f"[ERROR] Check cycle error: {e}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def stop(self):
        self.running = False
        print("[STOP] Connection checker stopped")


async def run_checker():
    checker = ConnectionChecker()
    await checker.start()


if __name__ == '__main__':
    asyncio.run(run_checker())
