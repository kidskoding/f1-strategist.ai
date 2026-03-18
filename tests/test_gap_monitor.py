import json
from pathlib import Path

import pytest

from agents.gap_monitor import GapMonitor
from core.models import GapSignal
from core.race_state import RaceState

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def monitor():
    return GapMonitor()


def make_state(driver: int = 1) -> RaceState:
    return RaceState.default(session_key="test", driver=driver)


def intervals(driver: int, gap_to_leader: object, interval: object) -> list[dict]:
    return [{"driver_number": driver, "gap_to_leader": gap_to_leader, "interval": interval}]


class TestReturnType:
    def test_returns_gap_signal(self, monitor):
        result = monitor.analyze(make_state(), [])
        assert isinstance(result, GapSignal)

    def test_driver_matches_state(self, monitor):
        result = monitor.analyze(make_state(driver=44), [])
        assert result.driver == 44


class TestUndercutViable:
    def test_undercut_true_when_gap_below_22(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "18.5", "3.0"))
        assert result.undercut_viable is True
        assert result.gap_ahead == pytest.approx(18.5)

    def test_undercut_false_when_gap_at_22(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "22.0", "3.0"))
        assert result.undercut_viable is False

    def test_undercut_false_when_gap_above_22(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "30.0", "3.0"))
        assert result.undercut_viable is False

    def test_undercut_false_when_gap_is_zero(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "0.0", "3.0"))
        assert result.undercut_viable is False


class TestOvercutViable:
    def test_overcut_true_when_gap_behind_large_and_ahead_safe(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "25.0", "26.0"))
        assert result.overcut_viable is True

    def test_overcut_false_when_gap_behind_small(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "25.0", "10.0"))
        assert result.overcut_viable is False

    def test_overcut_false_when_undercut_viable(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "18.0", "30.0"))
        assert result.overcut_viable is False


class TestEdgeCases:
    def test_missing_driver_returns_zeros(self, monitor):
        result = monitor.analyze(make_state(driver=1), intervals(44, "5.0", "2.0"))
        assert result.gap_ahead == 0.0
        assert result.gap_behind == 0.0
        assert result.undercut_viable is False

    def test_empty_intervals_returns_zeros(self, monitor):
        result = monitor.analyze(make_state(), [])
        assert result.gap_ahead == 0.0
        assert result.gap_behind == 0.0

    def test_non_numeric_gap_handled(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, "LAP", "LAP"))
        assert result.gap_ahead == 0.0
        assert result.gap_behind == 0.0

    def test_none_gap_handled(self, monitor):
        result = monitor.analyze(make_state(), intervals(1, None, None))
        assert result.gap_ahead == 0.0


class TestWithFixture:
    def test_fixture_loads_and_returns_signal(self, monitor):
        data = json.loads((FIXTURES / "intervals.json").read_text())
        state = make_state(driver=1)
        result = monitor.analyze(state, data)
        assert isinstance(result, GapSignal)
        assert result.driver == 1
