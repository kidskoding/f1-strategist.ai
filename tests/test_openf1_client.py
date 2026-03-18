import json

import httpx
import pytest

from core.openf1_client import OpenF1Client, OpenF1Error


def make_response(status_code: int, body: list | str) -> httpx.Response:
    content = json.dumps(body).encode() if isinstance(body, list) else body.encode()
    return httpx.Response(status_code, content=content)


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response):
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


class SequenceTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        idx = self.calls
        self.calls += 1
        return self._responses[min(idx, len(self._responses) - 1)]


async def make_client(response: httpx.Response) -> OpenF1Client:
    client = OpenF1Client(
        base_url="https://api.openf1.org/v1",
        request_delay=0,
        max_requests_per_sec=1000,
    )
    client._client = httpx.AsyncClient(transport=MockTransport(response), base_url="https://api.openf1.org/v1")
    return client


class TestGetPositions:
    async def test_returns_list(self):
        payload = [{"driver_number": 1, "lap_number": 24}]
        client = await make_client(make_response(200, payload))
        result = await client.get_positions("9158", 1)
        assert result == payload

    async def test_raises_on_429(self):
        client = await make_client(make_response(429, "rate limited"))
        with pytest.raises(OpenF1Error) as exc_info:
            await client.get_positions("9158", 1)
        assert exc_info.value.status_code == 429

    async def test_raises_on_500(self):
        client = await make_client(make_response(500, "server error"))
        with pytest.raises(OpenF1Error) as exc_info:
            await client.get_positions("9158", 1)
        assert exc_info.value.status_code == 500

    async def test_retries_on_429_then_succeeds(self):
        payload = [{"driver_number": 1, "lap_number": 24}]
        seq_transport = SequenceTransport([make_response(429, "rate limited"), make_response(200, payload)])
        client = OpenF1Client(
            base_url="https://api.openf1.org/v1",
            request_delay=0,
            max_requests_per_sec=1000,
        )
        client._client = httpx.AsyncClient(transport=seq_transport, base_url="https://api.openf1.org/v1")

        result = await client.get_positions("9158", 1)

        assert result == payload
        assert seq_transport.calls == 2

    async def test_raises_after_exhausting_429_retries(self):
        seq_transport = SequenceTransport([make_response(429, "rate limited")] * 5)
        client = OpenF1Client(
            base_url="https://api.openf1.org/v1",
            request_delay=0,
            max_requests_per_sec=1000,
            max_429_retries=1,
        )
        client._client = httpx.AsyncClient(transport=seq_transport, base_url="https://api.openf1.org/v1")

        with pytest.raises(OpenF1Error) as exc_info:
            await client.get_positions("9158", 1)

        assert exc_info.value.status_code == 429
        assert seq_transport.calls == 2


class TestGetIntervals:
    async def test_returns_list(self):
        payload = [{"driver_number": 1, "gap_to_leader": "0.0", "interval": "5.2"}]
        client = await make_client(make_response(200, payload))
        result = await client.get_intervals("9158")
        assert result == payload


class TestGetStints:
    async def test_returns_list(self):
        payload = [{"driver_number": 1, "compound": "MEDIUM", "lap_number": 8}]
        client = await make_client(make_response(200, payload))
        result = await client.get_stints("9158", 1)
        assert result == payload


class TestGetRaceControl:
    async def test_returns_list(self):
        payload = [{"flag": "SAFETY CAR", "message": "SAFETY CAR DEPLOYED"}]
        client = await make_client(make_response(200, payload))
        result = await client.get_race_control("9158")
        assert result == payload

    async def test_returns_empty_list(self):
        client = await make_client(make_response(200, []))
        result = await client.get_race_control("9158")
        assert result == []


class TestContextManager:
    async def test_raises_without_context_manager(self):
        client = OpenF1Client(request_delay=0, max_requests_per_sec=1000)
        with pytest.raises(RuntimeError, match="async context manager"):
            await client.get_positions("9158", 1)

    async def test_works_as_context_manager(self):
        payload = [{"driver_number": 1, "lap_number": 1}]

        class AutoTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return make_response(200, payload)

        async with OpenF1Client(
            base_url="https://api.openf1.org/v1",
            request_delay=0,
            max_requests_per_sec=1000,
        ) as client:
            client._client = httpx.AsyncClient(
                transport=AutoTransport(), base_url="https://api.openf1.org/v1"
            )
            result = await client.get_positions("9158", 1)
        assert result == payload
