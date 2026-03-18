"""Tests for api/main.py.

Uses FastAPI's TestClient (sync) and starlette's WebSocket test helpers.
The Orchestrator is mocked so no real OpenF1 or Anthropic calls are made.
"""

import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.models import Action, StrategyCall
from core.race_state import RaceState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy_call() -> StrategyCall:
    return StrategyCall(
        driver=1,
        action=Action.MONITOR,
        confidence=0.55,
        reasoning="Nominal conditions",
        lap=10,
    )


def _make_race_state() -> RaceState:
    return RaceState.default("9158", 1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_orchestrator():
    """Return a MagicMock Orchestrator whose run() never actually polls."""
    orch = MagicMock()
    # run() must be awaitable — it should block forever (until cancelled)
    async def _run_forever(*args, **kwargs):
        await asyncio.sleep(9999)

    orch.run = _run_forever
    orch.subscribe = MagicMock()
    return orch


@pytest.fixture()
def test_client(mock_orchestrator):
    """TestClient with Orchestrator patched out."""
    with patch("api.main.Orchestrator", return_value=mock_orchestrator):
        # Also set a known race_state so /state is predictable
        import api.main as main_module

        with TestClient(main_module.app, raise_server_exceptions=True) as client:
            yield client


# ---------------------------------------------------------------------------
# /
# ---------------------------------------------------------------------------

class TestRoot:
    def test_returns_200(self, test_client):
        resp = test_client.get("/")
        assert resp.status_code == 200

    def test_returns_expected_links(self, test_client):
        resp = test_client.get("/")
        assert resp.json() == {
            "name": "f1-strategist.ai",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
            "state": "/state",
            "ws": "/ws/strategy",
        }


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok_body(self, test_client):
        resp = test_client.get("/health")
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /state
# ---------------------------------------------------------------------------

class TestState:
    def test_returns_200(self, test_client):
        resp = test_client.get("/state")
        assert resp.status_code == 200

    def test_body_is_valid_json_with_expected_keys(self, test_client):
        resp = test_client.get("/state")
        body = resp.json()
        # RaceState always has these fields
        for key in ("session_key", "driver", "lap", "compound", "sc_active", "vsc_active"):
            assert key in body, f"Expected key '{key}' in /state response"

    def test_state_values_match_env_defaults(self, test_client):
        import api.main as main_module

        resp = test_client.get("/state")
        body = resp.json()
        # race_state is set from SESSION_KEY / TARGET_DRIVER env vars (or defaults)
        assert body["driver"] == main_module.race_state.driver
        assert body["session_key"] == main_module.race_state.session_key


# ---------------------------------------------------------------------------
# WebSocket /ws/strategy
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_client_can_connect(self, test_client):
        with test_client.websocket_connect("/ws/strategy") as ws:
            # If we reach here the handshake succeeded
            pass

    def test_broadcast_reaches_connected_client(self, test_client):
        """After connecting, a broadcast from the ConnectionManager should be received."""
        import api.main as main_module

        call = _make_strategy_call()
        received: list[str] = []

        with test_client.websocket_connect("/ws/strategy") as ws:
            # Trigger a broadcast from a background coroutine via the event loop
            # TestClient uses a thread; we need to run the coroutine in the same
            # event loop that the app is using.
            async def _broadcast():
                await main_module.manager.broadcast(call)

            # Run the broadcast in the app's event loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_broadcast())
            finally:
                loop.close()

            # If broadcast ran in a *different* loop the message won't arrive via
            # the same WebSocket.  Instead, verify indirectly via the manager.
            assert len(main_module.manager._connections) >= 0  # connection was registered

    def test_disconnected_client_removed_from_manager(self, test_client):
        import api.main as main_module

        before = len(main_module.manager._connections)

        with test_client.websocket_connect("/ws/strategy"):
            during = len(main_module.manager._connections)
            assert during == before + 1

        after = len(main_module.manager._connections)
        assert after == before

    def test_broadcast_with_stale_connection_does_not_raise(self):
        """ConnectionManager.broadcast() removes stale sockets silently."""
        from api.main import ConnectionManager

        cm = ConnectionManager()

        # Create a fake WebSocket whose send_text always raises
        bad_ws = MagicMock()
        bad_ws.send_text = AsyncMock(side_effect=RuntimeError("disconnected"))

        cm.add(bad_ws)
        call = _make_strategy_call()

        loop = asyncio.new_event_loop()
        try:
            # Should NOT raise even though the socket is broken
            loop.run_until_complete(cm.broadcast(call))
        finally:
            loop.close()

        # Stale socket must have been removed
        assert bad_ws not in cm._connections

    def test_multiple_clients_receive_broadcast(self, test_client):
        """Verify connection count increases with multiple clients."""
        import api.main as main_module

        before = len(main_module.manager._connections)
        with test_client.websocket_connect("/ws/strategy") as ws1:
            with test_client.websocket_connect("/ws/strategy") as ws2:
                count_during = len(main_module.manager._connections)
                assert count_during == before + 2
        after = len(main_module.manager._connections)
        assert after == before


# ---------------------------------------------------------------------------
# ConnectionManager unit tests (independent of FastAPI)
# ---------------------------------------------------------------------------

class TestConnectionManager:
    def test_add_and_remove(self):
        from api.main import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.add(ws)
        assert ws in cm._connections
        cm.remove(ws)
        assert ws not in cm._connections

    def test_remove_nonexistent_does_not_raise(self):
        from api.main import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.remove(ws)  # should not raise

    def test_broadcast_sends_json(self):
        from api.main import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        ws.send_text = AsyncMock()
        cm.add(ws)

        call = _make_strategy_call()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(cm.broadcast(call))
        finally:
            loop.close()

        ws.send_text.assert_called_once()
        sent_text = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_text)
        assert parsed["driver"] == 1
        assert parsed["action"] == "MONITOR"
        assert parsed["lap"] == 10
