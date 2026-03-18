import asyncio
import os
import time

import httpx


class OpenF1Error(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"OpenF1 API error {status_code}: {message}")


class OpenF1Client:
    def __init__(
        self,
        base_url: str | None = None,
        request_delay: float = 0.0,
        max_requests_per_sec: float | None = None,
        max_429_retries: int = 2,
    ):
        self.base_url = (base_url or os.getenv("OPENF1_BASE_URL", "https://api.openf1.org/v1")).rstrip("/")
        self.request_delay = request_delay
        env_max_rps = float(os.getenv("OPENF1_MAX_RPS", "2.5"))
        self.max_requests_per_sec = max_requests_per_sec if max_requests_per_sec is not None else env_max_rps
        self.max_429_retries = max_429_retries
        self._client: httpx.AsyncClient | None = None
        self._rate_lock = asyncio.Lock()
        self._next_request_time = 0.0

    async def __aenter__(self) -> "OpenF1Client":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _wait_for_rate_slot(self) -> None:
        if self.max_requests_per_sec <= 0:
            return

        min_interval = 1.0 / self.max_requests_per_sec
        async with self._rate_lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next_request_time - now)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = time.monotonic()
            self._next_request_time = now + min_interval

    async def _get(self, path: str, params: dict) -> list[dict]:
        if self._client is None:
            raise RuntimeError("OpenF1Client must be used as an async context manager")

        for attempt in range(self.max_429_retries + 1):
            await self._wait_for_rate_slot()
            if self.request_delay > 0:
                await asyncio.sleep(self.request_delay)

            response = await self._client.get(path, params=params)
            if response.status_code == 200:
                return response.json()

            if response.status_code == 429 and attempt < self.max_429_retries:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        backoff = float(retry_after)
                    except ValueError:
                        backoff = 0.5 * (2**attempt)
                else:
                    backoff = 0.5 * (2**attempt)
                await asyncio.sleep(backoff)
                continue

            raise OpenF1Error(response.status_code, response.text[:200])

        raise OpenF1Error(429, "Rate limit exceeded after retries")

    async def get_positions(self, session_key: str, driver: int) -> list[dict]:
        return await self._get("/position", {"session_key": session_key, "driver_number": driver})

    async def get_intervals(self, session_key: str) -> list[dict]:
        return await self._get("/intervals", {"session_key": session_key})

    async def get_stints(self, session_key: str, driver: int) -> list[dict]:
        return await self._get("/stints", {"session_key": session_key, "driver_number": driver})

    async def get_race_control(self, session_key: str) -> list[dict]:
        return await self._get("/race_control", {"session_key": session_key})
