"""Tests for agents/orchestrator.py.

All external calls (OpenF1 client, synthesizer subagents) are mocked so
the tests run fully offline without network access or an Anthropic key.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator import Orchestrator
from core.models import Action, GapSignal, SafetyCarSignal, StrategyCall, TireSignal
from core.race_state import RaceState


# ---------------------------------------------------------------------------
# Helpers — build minimal valid signal objects
# ---------------------------------------------------------------------------

def _make_tire_signal(driver: int = 1) -> TireSignal:
    return TireSignal(
        driver=driver,
        recommend_pit=False,
        suggested_compound="MEDIUM",
        pit_window_laps=(0, 0),
        deg_rate=0.05,
    )


def _make_gap_signal(driver: int = 1) -> GapSignal:
    return GapSignal(
        driver=driver,
        undercut_viable=False,
        overcut_viable=False,
        gap_ahead=30.0,
        gap_behind=5.0,
    )


def _make_sc_signal() -> SafetyCarSignal:
    return SafetyCarSignal(
        sc_active=False,
        vsc_active=False,
        pit_opportunity=False,
        reasoning="No safety car — normal racing conditions",
    )


def _make_strategy_call(driver: int = 1, lap: int = 10) -> StrategyCall:
    return StrategyCall(
        driver=driver,
        action=Action.MONITOR,
        confidence=0.50,
        reasoning="No decisive signal — monitoring",
        lap=lap,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """A mock OpenF1Client that returns minimal list responses."""
    client = AsyncMock()
    client.get_positions = AsyncMock(return_value=[{"lap_number": 10}])
    client.get_intervals = AsyncMock(return_value=[{"driver_number": 1, "gap_to_leader": 5.0, "interval": 2.0}])
    client.get_stints = AsyncMock(return_value=[{"compound": "MEDIUM", "lap_number": 8}])
    client.get_race_control = AsyncMock(return_value=[])
    return client


@pytest.fixture
def orchestrator():
    return Orchestrator()


# ---------------------------------------------------------------------------
# subscribe()
# ---------------------------------------------------------------------------

class TestSubscribe:
    def test_subscriber_stored(self, orchestrator):
        cb = MagicMock()
        orchestrator.subscribe(cb)
        assert cb in orchestrator._subscribers

    def test_multiple_subscribers_stored(self, orchestrator):
        cb1, cb2 = MagicMock(), MagicMock()
        orchestrator.subscribe(cb1)
        orchestrator.subscribe(cb2)
        assert len(orchestrator._subscribers) == 2


# ---------------------------------------------------------------------------
# _notify_subscribers()
# ---------------------------------------------------------------------------

class TestNotifySubscribers:
    @pytest.mark.asyncio
    async def test_sync_callback_called(self, orchestrator):
        received = []
        call = _make_strategy_call()
        orchestrator.subscribe(lambda c: received.append(c))
        await orchestrator._notify_subscribers(call)
        assert received == [call]

    @pytest.mark.asyncio
    async def test_async_callback_awaited(self, orchestrator):
        received = []

        async def async_cb(c):
            received.append(c)

        call = _make_strategy_call()
        orchestrator.subscribe(async_cb)
        await orchestrator._notify_subscribers(call)
        assert received == [call]

    @pytest.mark.asyncio
    async def test_failing_subscriber_does_not_raise(self, orchestrator):
        """A subscriber that raises must not propagate to the caller."""
        def bad_cb(c):
            raise RuntimeError("subscriber exploded")

        good_received = []
        orchestrator.subscribe(bad_cb)
        orchestrator.subscribe(lambda c: good_received.append(c))

        call = _make_strategy_call()
        # Should not raise
        await orchestrator._notify_subscribers(call)
        # The good subscriber still ran
        assert good_received == [call]

    @pytest.mark.asyncio
    async def test_all_subscribers_called(self, orchestrator):
        received = []
        for _ in range(3):
            orchestrator.subscribe(lambda c: received.append(c))
        await orchestrator._notify_subscribers(_make_strategy_call())
        assert len(received) == 3


# ---------------------------------------------------------------------------
# _poll_cycle()
# ---------------------------------------------------------------------------

class TestPollCycle:
    @pytest.mark.asyncio
    async def test_poll_cycle_calls_client_methods(self, orchestrator, mock_client):
        """All four client methods should be called once per cycle."""
        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=_make_strategy_call())),
        ):
            state = RaceState.default("9158", 1)
            await orchestrator._poll_cycle("9158", 1, state, mock_client)

        mock_client.get_positions.assert_called_once_with("9158", 1)
        mock_client.get_intervals.assert_called_once_with("9158")
        mock_client.get_stints.assert_called_once_with("9158", 1)
        mock_client.get_race_control.assert_called_once_with("9158")

    @pytest.mark.asyncio
    async def test_poll_cycle_updates_state(self, orchestrator, mock_client):
        """State should be mutated after a poll cycle."""
        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=_make_strategy_call())),
        ):
            state = RaceState.default("9158", 1)
            assert state.lap == 0
            await orchestrator._poll_cycle("9158", 1, state, mock_client)

        assert state.lap == 10  # from mock get_positions response
        assert state.compound == "MEDIUM"  # from mock get_stints response

    @pytest.mark.asyncio
    async def test_poll_cycle_notifies_subscribers(self, orchestrator, mock_client):
        received: list[StrategyCall] = []
        orchestrator.subscribe(lambda c: received.append(c))
        expected_call = _make_strategy_call()

        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=expected_call)),
        ):
            state = RaceState.default("9158", 1)
            await orchestrator._poll_cycle("9158", 1, state, mock_client)

        assert received == [expected_call]

    @pytest.mark.asyncio
    async def test_poll_cycle_calls_subagents(self, orchestrator, mock_client):
        """TireStrategist, GapMonitor, and SafetyCarDetector should each be called once."""
        tire_mock = MagicMock(return_value=_make_tire_signal())
        gap_mock = MagicMock(return_value=_make_gap_signal())
        sc_mock = MagicMock(return_value=_make_sc_signal())

        with (
            patch.object(orchestrator._tire_strategist, "analyze", tire_mock),
            patch.object(orchestrator._gap_monitor, "analyze", gap_mock),
            patch.object(orchestrator._sc_detector, "analyze", sc_mock),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=_make_strategy_call())),
        ):
            state = RaceState.default("9158", 1)
            await orchestrator._poll_cycle("9158", 1, state, mock_client)

        tire_mock.assert_called_once()
        gap_mock.assert_called_once()
        sc_mock.assert_called_once()


# ---------------------------------------------------------------------------
# run() — integration of the loop
# ---------------------------------------------------------------------------

class TestRun:
    @pytest.mark.asyncio
    async def test_run_emits_strategy_call_within_one_cycle(self, orchestrator, mock_client):
        """run() should emit at least one StrategyCall before being cancelled."""
        received: list[StrategyCall] = []
        orchestrator.subscribe(lambda c: received.append(c))

        expected_call = _make_strategy_call()

        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=expected_call)),
        ):
            task = asyncio.create_task(
                orchestrator.run("9158", 1, poll_interval=0.0, client=mock_client)
            )
            # Give the event loop a chance to run at least one cycle
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(received) >= 1
        assert received[0] == expected_call

    @pytest.mark.asyncio
    async def test_run_continues_after_transient_api_error(self, orchestrator):
        """A failing poll cycle should be logged and the loop should continue."""
        received: list[StrategyCall] = []
        orchestrator.subscribe(lambda c: received.append(c))

        call_count = 0
        expected_call = _make_strategy_call()

        error_client = AsyncMock()

        async def flaky_positions(session_key, driver):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient network error")
            return [{"lap_number": 10}]

        error_client.get_positions = flaky_positions
        error_client.get_intervals = AsyncMock(return_value=[])
        error_client.get_stints = AsyncMock(return_value=[])
        error_client.get_race_control = AsyncMock(return_value=[])

        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=expected_call)),
        ):
            task = asyncio.create_task(
                orchestrator.run("9158", 1, poll_interval=0.01, client=error_client)
            )
            # Wait long enough for at least 2 cycles (first fails, second succeeds)
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # At least one successful call should have come through after the transient error
        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_subscriber_receives_each_cycle_call(self, orchestrator, mock_client):
        """Subscriber should be called once per successful poll cycle."""
        received: list[StrategyCall] = []
        orchestrator.subscribe(lambda c: received.append(c))

        expected_call = _make_strategy_call()

        with (
            patch.object(orchestrator._tire_strategist, "analyze", return_value=_make_tire_signal()),
            patch.object(orchestrator._gap_monitor, "analyze", return_value=_make_gap_signal()),
            patch.object(orchestrator._sc_detector, "analyze", return_value=_make_sc_signal()),
            patch.object(orchestrator._synthesizer, "synthesize", new=AsyncMock(return_value=expected_call)),
        ):
            task = asyncio.create_task(
                orchestrator.run("9158", 1, poll_interval=0.01, client=mock_client)
            )
            await asyncio.sleep(0.08)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Multiple cycles should have fired
        assert len(received) >= 2
