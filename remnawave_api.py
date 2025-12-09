"""Remnawave API client using official SDK"""

from remnawave import RemnawaveSDK
from config import REMNAWAVE_API_URL, REMNAWAVE_API_TOKEN


class RemnawaveAPI:
    def __init__(self):
        self.client = RemnawaveSDK(
            base_url=REMNAWAVE_API_URL,
            token=REMNAWAVE_API_TOKEN
        )

    async def get_user_by_id(self, user_id: str):
        """Get user by ID (number from logs)"""
        try:
            result = await self.client.users.get_user_by_id(user_id)
            return result
        except Exception as e:
            print(f"[ERROR] Failed to get user by ID {user_id}: {e}")
            return None

    async def get_user_by_username(self, username: str):
        """Get user info by username or ID"""
        try:
            # Если это число - ищем по ID
            if username.isdigit():
                user = await self.get_user_by_id(username)
                if user:
                    return user
            
            # Иначе по username
            result = await self.client.users.get_user_by_username(username)
            return result
        except Exception as e:
            print(f"[ERROR] Failed to get user {username}: {e}")
            return None

    async def get_user_hwid_limit(self, username: str) -> int | None:
        """Get user's HWID device limit"""
        user = await self.get_user_by_username(username)
        if not user:
            return None
        
        try:
            # SDK возвращает объект с полем hwid_device_limit
            limit = getattr(user, 'hwid_device_limit', None)
            if limit is not None and limit > 0:
                return int(limit)
            return None  # Нет лимита или 0
        except Exception as e:
            print(f"[ERROR] Failed to get HWID limit for {username}: {e}")
            return None


    async def get_user_uuid(self, username: str) -> str | None:
        """Get user UUID"""
        user = await self.get_user_by_username(username)
        if user:
            uuid = getattr(user, 'uuid', None)
            return str(uuid) if uuid else None
        return None

    async def disable_user(self, uuid: str) -> bool:
        """Disable user subscription"""
        try:
            await self.client.users.disable_user(uuid)
            print(f"[INFO] User {uuid} disabled")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to disable user {uuid}: {e}")
            return False

    async def enable_user(self, uuid: str) -> bool:
        """Enable user subscription"""
        try:
            await self.client.users.enable_user(uuid)
            print(f"[INFO] User {uuid} enabled")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to enable user {uuid}: {e}")
            return False
