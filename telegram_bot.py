"""Telegram bot for notifications"""

import aiohttp


class TelegramNotifier:
    def __init__(self):
        self._token = None
        self._chat_id = None

    def _load_config(self):
        """Load config on demand"""
        try:
            from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            self._token = TELEGRAM_BOT_TOKEN
            self._chat_id = TELEGRAM_CHAT_ID
        except Exception as e:
            print(f"[TELEGRAM] Failed to load config: {e}")
            self._token = None
            self._chat_id = None

    @property
    def enabled(self):
        self._load_config()
        return bool(self._token and self._chat_id)

    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send message to Telegram chat"""
        self._load_config()
        
        if not self._token or not self._chat_id:
            print("[TELEGRAM] Bot disabled - no token or chat_id")
            return False
        
        try:
            api_url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": parse_mode
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        print(f"[TELEGRAM] Message sent OK")
                        return True
                    else:
                        data = await response.json()
                        error = data.get('description', f'HTTP {response.status}')
                        print(f"[TELEGRAM] Error: {error}")
                        return False
        except Exception as e:
            print(f"[TELEGRAM] Failed to send: {e}")
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
