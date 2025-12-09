"""Telegram bot for notifications"""

import asyncio
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramNotifier:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            print("[TELEGRAM] Bot disabled - no token or chat_id configured")

    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send message to Telegram chat"""
        if not self.enabled:
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
        except Exception as e:
            print(f"[TELEGRAM] Failed to send message: {e}")
            return False

    async def notify_warning(self, username: str, ip_count: int, device_limit: int, ips: list):
        """Send warning about user exceeding IP limit"""
        ips_formatted = ", ".join([f"'{ip}'" for ip in ips])
        
        message = (
            f"⚠️ <b>Warning:</b> User <code>{username}</code> has {ip_count} "
            f"active ips. {{{ips_formatted}}}"
        )
        
        await self.send_message(message)

    async def notify_disabled(self, username: str):
        """Send notification that user was disabled"""
        message = f"🔴 <b>Disabled user:</b> <code>{username}</code>"
        await self.send_message(message)

    async def notify_enabled(self, username: str):
        """Send notification that user was enabled"""
        message = f"🟢 <b>Enabled user:</b> <code>{username}</code>"
        await self.send_message(message)

    async def notify_drop(self, username: str, ip_count: int, device_limit: int, dropped_ips: list):
        """Send notification about dropped connections"""
        ips_formatted = ", ".join([f"'{ip}'" for ip in dropped_ips])
        
        message = (
            f"🔻 <b>Drop:</b> User <code>{username}</code>\n"
            f"IPs: {ip_count}, Limit: {device_limit}\n"
            f"Dropped: {{{ips_formatted}}}"
        )
        
        await self.send_message(message)


# Global instance
notifier = TelegramNotifier()
