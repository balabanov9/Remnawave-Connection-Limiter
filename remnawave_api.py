"""Remnawave API client using official SDK"""

import asyncio
from remnawave import RemnawaveSDK
from remnawave.models import UserResponseDto
from config import REMNAWAVE_API_URL, REMNAWAVE_API_TOKEN


class RemnawaveAPI:
    def __init__(self):
        self.client = RemnawaveSDK(
            base_url=REMNAWAVE_API_URL,
            token=REMNAWAVE_API_TOKEN
        )

    async def get_user_by_username(self, username: str) -> UserResponseDto | None:
        """Get user info by username"""
        try:
            user = await self.client.users.get_user_by_username(username)
            return user
        except Exception as e:
            print(f"[ERROR] Failed to get user {username}: {e}")
            return None

    async def get_user_by_uuid(self, uuid: str) -> UserResponseDto | None:
        """Get user info by UUID"""
        try:
            user = await self.client.users.get_user_by_uuid(uuid)
            return user
        except Exception as e:
            print(f"[ERROR] Failed to get user by UUID {uuid}: {e}")
            return None

    async def get_user_device_limit(self, username: str) -> int:
        """Get user's device limit (hwidDeviceLimit)"""
        user = await self.get_user_by_username(username)
        if user:
            limit = None
            
            try:
                # Получаем все данные юзера
                data = user.model_dump()
                
                # DEBUG: показать все поля (раскомментируй для отладки)
                # print(f"[DEBUG] User {username} fields: {list(data.keys())}")
                
                # Ищем поле с лимитом устройств
                for key in ['hwidDeviceLimit', 'hwid_device_limit', 'deviceLimit', 'device_limit']:
                    if key in data and data[key] is not None:
                        limit = data[key]
                        break
            except Exception as e:
                print(f"[DEBUG] Error getting user data: {e}")
            
            # Если лимит найден и > 0, возвращаем его
            if limit is not None and limit > 0:
                return int(limit)
            
            # Если None или 0 — без лимита (пропускаем проверку)
            return 999
        return 1  # По умолчанию 1 устройство если юзер не найден

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

    async def get_user_status(self, username: str) -> str:
        """Get current user status"""
        user = await self.get_user_by_username(username)
        if user and user.status:
            return user.status.value if hasattr(user.status, 'value') else str(user.status)
        return 'unknown'

    async def get_user_uuid(self, username: str) -> str | None:
        """Get user UUID by username"""
        user = await self.get_user_by_username(username)
        if user:
            return str(user.uuid)
        return None
