"""Remnawave API client - direct HTTP"""

import aiohttp
from config import REMNAWAVE_API_URL, REMNAWAVE_API_TOKEN


class RemnawaveAPI:
    def __init__(self):
        self.base_url = REMNAWAVE_API_URL
        self.headers = {"Authorization": f"Bearer {REMNAWAVE_API_TOKEN}"}

    async def _request(self, method: str, endpoint: str, json_data: dict = None):
        """Make HTTP request to API"""
        try:
            url = f"{self.base_url}/api{endpoint}"
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get('response', data)
                        return None
                else:
                    async with session.post(url, headers=self.headers, json=json_data or {}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return resp.status == 200
        except Exception as e:
            print(f"[ERROR] API {method} {endpoint}: {e}")
            return None

    async def get_user_by_id(self, user_id: str):
        """Get user by ID (number from logs)"""
        return await self._request("GET", f"/users/by-id/{user_id}")

    async def get_user_by_username(self, username: str):
        """Get user info by username or ID"""
        # Если это число - ищем по ID
        if username.isdigit():
            user = await self.get_user_by_id(username)
            if user:
                return user
        
        # Иначе по username
        return await self._request("GET", f"/users/by-username/{username}")

    async def get_user_hwid_limit(self, username: str) -> int | None:
        """Get user's HWID device limit"""
        user = await self.get_user_by_username(username)
        if not user:
            return None
        
        # Ищем поле с лимитом
        limit = user.get('hwidDeviceLimit') or user.get('hwid_device_limit')
        if limit is not None and limit > 0:
            return int(limit)
        return None


    async def get_user_uuid(self, username: str) -> str | None:
        """Get user UUID"""
        user = await self.get_user_by_username(username)
        if user:
            return str(user.get('uuid', ''))
        return None

    async def disable_user(self, uuid: str) -> bool:
        """Disable user subscription"""
        result = await self._request("POST", f"/users/{uuid}/actions/disable")
        if result:
            print(f"[INFO] User {uuid} disabled")
        return bool(result)

    async def enable_user(self, uuid: str) -> bool:
        """Enable user subscription"""
        result = await self._request("POST", f"/users/{uuid}/actions/enable")
        if result:
            print(f"[INFO] User {uuid} enabled")
        return bool(result)
