import pytest

from agents.tire_strategist import TireStrategist
from core.models import TireSignal
from core.race_state import RaceState


@pytest.fixture
def strategist():
    return TireStrategist()


def make_state(compound: str, stint_lap: int, lap: int = 20, driver: int = 1) -> RaceState:
    state = RaceState.default(session_key="test", driver=driver)
    state.compound = compound
    state.stint_lap = stint_lap
    state.lap = lap
    return state


class TestReturnType:
    def test_returns_tire_signal(self, strategist):
        result = strategist.analyze(make_state("SOFT", 10), [])
        assert isinstance(result, TireSignal)

    def test_driver_matches_state(self, strategist):
        result = strategist.analyze(make_state("MEDIUM", 5, driver=44), [])
        assert result.driver == 44


class TestRecommendPit:
    @pytest.mark.parametrize("compound,over_limit", [
        ("SOFT", 26),
        ("MEDIUM", 36),
        ("HARD", 46),
    ])
    def test_recommend_pit_over_limit(self, strategist, compound, over_limit):
        result = strategist.analyze(make_state(compound, over_limit), [])
        assert result.recommend_pit is True

    @pytest.mark.parametrize("compound,fresh", [
        ("SOFT", 10),
        ("MEDIUM", 20),
        ("HARD", 30),
    ])
    def test_no_pit_fresh_tires(self, strategist, compound, fresh):
        result = strategist.analyze(make_state(compound, fresh), [])
        assert result.recommend_pit is False

    def test_no_pit_at_exact_limit(self, strategist):
        result = strategist.analyze(make_state("SOFT", 25), [])
        assert result.recommend_pit is False


class TestSuggestedCompound:
    def test_soft_suggests_medium(self, strategist):
        assert strategist.analyze(make_state("SOFT", 1), []).suggested_compound == "MEDIUM"

    def test_medium_suggests_hard(self, strategist):
        assert strategist.analyze(make_state("MEDIUM", 1), []).suggested_compound == "HARD"

    def test_hard_suggests_medium(self, strategist):
        assert strategist.analyze(make_state("HARD", 1), []).suggested_compound == "MEDIUM"


class TestPitWindowLaps:
    def test_window_set_when_recommending(self, strategist):
        result = strategist.analyze(make_state("SOFT", 26, lap=30), [])
        assert result.pit_window_laps == (30, 35)

    def test_window_zero_when_not_recommending(self, strategist):
        result = strategist.analyze(make_state("SOFT", 10, lap=15), [])
        assert result.pit_window_laps == (0, 0)


class TestDegRate:
    @pytest.mark.parametrize("compound,rate", [
        ("SOFT", 0.08),
        ("MEDIUM", 0.05),
        ("HARD", 0.03),
    ])
    def test_deg_rate(self, strategist, compound, rate):
        result = strategist.analyze(make_state(compound, 1), [])
        assert result.deg_rate == pytest.approx(rate)
