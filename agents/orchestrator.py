import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any

from agents.gap_monitor import GapMonitor
from agents.safety_car_detector import SafetyCarDetector
from agents.synthesizer import Synthesizer
from agents.tire_strategist import TireStrategist
from core.models import StrategyCall
from core.openf1_client import OpenF1Client
from core.race_state import RaceState

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SECS", "2"))

# Type alias for subscriber callbacks — may be sync or async
SubscriberCallback = Callable[[StrategyCall], Any]


class Orchestrator:
    """Coordinates the polling loop and dispatches to all subagents."""

    def __init__(self) -> None:
        self._tire_strategist = TireStrategist()
        self._gap_monitor = GapMonitor()
        self._sc_detector = SafetyCarDetector()
        self._synthesizer = Synthesizer()
        self._subscribers: list[SubscriberCallback] = []
        self._poll_interval = _DEFAULT_POLL_INTERVAL
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, callback: SubscriberCallback) -> None:
        """Register a callback to be invoked with each new StrategyCall.

        The callback may be a plain function or a coroutine function.
        """
        self._subscribers.append(callback)

    async def run(
        self,
        session_key: str,
        driver: int,
        *,
        poll_interval: float | None = None,
        client: OpenF1Client | None = None,
    ) -> None:
        """Start the polling loop.  Runs indefinitely until cancelled.

        Args:
            session_key: OpenF1 session key to poll.
            driver: Target driver number.
            poll_interval: Override the default POLL_INTERVAL_SECS.
            client: Inject a pre-built OpenF1Client (useful for testing).
        """
        interval = poll_interval if poll_interval is not None else self._poll_interval
        state = RaceState.default(session_key, driver)
        self._running = True

        if client is not None:
            await self._loop(session_key, driver, state, interval, client)
        else:
            async with OpenF1Client() as managed_client:
                await self._loop(session_key, driver, state, interval, managed_client)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _loop(
        self,
        session_key: str,
        driver: int,
        state: RaceState,
        interval: float,
        client: OpenF1Client,
    ) -> None:
        """Inner polling loop — separated so the client context is managed outside."""
        while self._running:
            try:
                await self._poll_cycle(session_key, driver, state, client)
            except asyncio.CancelledError:
                logger.info("Orchestrator polling loop cancelled")
                self._running = False
                raise
            except Exception as exc:
                logger.error("Polling cycle error (will retry): %s", exc, exc_info=True)

            await asyncio.sleep(interval)

    async def _poll_cycle(
        self,
        session_key: str,
        driver: int,
        state: RaceState,
        client: OpenF1Client,
    ) -> None:
        """Execute one full polling cycle: fetch → update state → analyze → synthesize → emit."""
        # 1. Fetch all data concurrently
        positions, intervals, stints, race_control = await asyncio.gather(
            client.get_positions(session_key, driver),
            client.get_intervals(session_key),
            client.get_stints(session_key, driver),
            client.get_race_control(session_key),
        )

        # 2. Update shared race state
        state.update_from_poll(
            positions=positions,
            intervals=intervals,
            stints=stints,
            race_control=race_control,
        )

        logger.debug(
            "State updated — lap=%d compound=%s stint_lap=%d sc=%s vsc=%s",
            state.lap,
            state.compound,
            state.stint_lap,
            state.sc_active,
            state.vsc_active,
        )

        # 3. Dispatch to subagents concurrently
        tire_signal, gap_signal, sc_signal = await asyncio.gather(
            asyncio.to_thread(self._tire_strategist.analyze, state, stints),
            asyncio.to_thread(self._gap_monitor.analyze, state, intervals),
            asyncio.to_thread(self._sc_detector.analyze, state, race_control),
        )

        # 4. Synthesize into a final strategy call
        call = await self._synthesizer.synthesize(tire_signal, gap_signal, sc_signal, state)

        logger.info(
            "Strategy call — driver=%d lap=%d action=%s confidence=%.2f | %s",
            call.driver,
            call.lap,
            call.action,
            call.confidence,
            call.reasoning,
        )

        # 5. Notify all subscribers
        await self._notify_subscribers(call)

    async def _notify_subscribers(self, call: StrategyCall) -> None:
        """Invoke each registered subscriber, supporting both sync and async callbacks."""
        for callback in self._subscribers:
            try:
                result = callback(call)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("Subscriber callback error: %s", exc, exc_info=True)
