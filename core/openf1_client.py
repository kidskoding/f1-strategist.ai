import asyncio
import os

import httpx


class OpenF1Error(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"OpenF1 API error {status_code}: {message}")


class OpenF1Client:
    def __init__(self, base_url: str | None = None, request_delay: float = 0.1):
        self.base_url = (base_url or os.getenv("OPENF1_BASE_URL", "https://api.openf1.org/v1")).rstrip("/")
        self.request_delay = request_delay
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OpenF1Client":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict) -> list[dict]:
        if self._client is None:
            raise RuntimeError("OpenF1Client must be used as an async context manager")
        await asyncio.sleep(self.request_delay)
        response = await self._client.get(path, params=params)
        if response.status_code != 200:
            raise OpenF1Error(response.status_code, response.text[:200])
        return response.json()

    async def get_positions(self, session_key: str, driver: int) -> list[dict]:
        return await self._get("/position", {"session_key": session_key, "driver_number": driver})

    async def get_intervals(self, session_key: str) -> list[dict]:
        return await self._get("/intervals", {"session_key": session_key})

    async def get_stints(self, session_key: str, driver: int) -> list[dict]:
        return await self._get("/stints", {"session_key": session_key, "driver_number": driver})

    async def get_race_control(self, session_key: str) -> list[dict]:
        return await self._get("/race_control", {"session_key": session_key})
