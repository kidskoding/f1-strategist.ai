import json
from pathlib import Path

import pytest

from agents.safety_car_detector import SafetyCarDetector
from core.models import SafetyCarSignal
from core.race_state import RaceState

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def detector():
    return SafetyCarDetector()


def make_state(stint_lap: int = 10) -> RaceState:
    state = RaceState.default(session_key="test", driver=1)
    state.stint_lap = stint_lap
    return state


class TestReturnType:
    def test_returns_safety_car_signal(self, detector):
        result = detector.analyze(make_state(), [])
        assert isinstance(result, SafetyCarSignal)

    def test_reasoning_always_non_empty(self, detector):
        for data in [[], [{"flag": "SAFETY CAR"}], [{"flag": "GREEN"}]]:
            result = detector.analyze(make_state(), data)
            assert result.reasoning != ""


class TestSCDetection:
    def test_sc_active_on_safety_car_flag(self, detector):
        result = detector.analyze(make_state(), [{"flag": "SAFETY CAR"}])
        assert result.sc_active is True
        assert result.vsc_active is False

    def test_vsc_active_on_virtual_safety_car_flag(self, detector):
        result = detector.analyze(make_state(), [{"flag": "VIRTUAL SAFETY CAR"}])
        assert result.vsc_active is True
        assert result.sc_active is False

    def test_flags_clear_on_green(self, detector):
        data = [{"flag": "SAFETY CAR"}, {"flag": "GREEN"}]
        result = detector.analyze(make_state(), data)
        assert result.sc_active is False
        assert result.vsc_active is False

    def test_flags_clear_on_clear(self, detector):
        data = [{"flag": "VIRTUAL SAFETY CAR"}, {"flag": "CLEAR"}]
        result = detector.analyze(make_state(), data)
        assert result.vsc_active is False

    def test_no_sc_when_empty(self, detector):
        result = detector.analyze(make_state(), [])
        assert result.sc_active is False
        assert result.vsc_active is False


class TestPitOpportunity:
    def test_pit_opportunity_true_when_sc_and_stint_over_5(self, detector):
        result = detector.analyze(make_state(stint_lap=10), [{"flag": "SAFETY CAR"}])
        assert result.pit_opportunity is True

    def test_pit_opportunity_false_when_sc_but_just_pitted(self, detector):
        result = detector.analyze(make_state(stint_lap=3), [{"flag": "SAFETY CAR"}])
        assert result.pit_opportunity is False

    def test_pit_opportunity_true_when_vsc_and_stint_over_5(self, detector):
        result = detector.analyze(make_state(stint_lap=8), [{"flag": "VIRTUAL SAFETY CAR"}])
        assert result.pit_opportunity is True

    def test_pit_opportunity_false_when_no_sc(self, detector):
        result = detector.analyze(make_state(stint_lap=20), [])
        assert result.pit_opportunity is False

    def test_pit_opportunity_false_at_exact_limit(self, detector):
        result = detector.analyze(make_state(stint_lap=5), [{"flag": "SAFETY CAR"}])
        assert result.pit_opportunity is False


class TestWithFixture:
    def test_fixture_loads_and_returns_signal(self, detector):
        data = json.loads((FIXTURES / "race_control.json").read_text())
        result = detector.analyze(make_state(stint_lap=15), data)
        assert isinstance(result, SafetyCarSignal)
        assert result.reasoning != ""
