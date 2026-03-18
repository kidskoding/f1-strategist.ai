from core.models import TireSignal
from core.race_state import RaceState

_DEG_RATES: dict[str, float] = {
    "SOFT": 0.08,
    "MEDIUM": 0.05,
    "HARD": 0.03,
}

_COMPOUND_LIFE: dict[str, int] = {
    "SOFT": 25,
    "MEDIUM": 35,
    "HARD": 45,
}

_NEXT_COMPOUND: dict[str, str] = {
    "SOFT": "MEDIUM",
    "MEDIUM": "HARD",
    "HARD": "MEDIUM",
}


class TireStrategist:
    def analyze(self, state: RaceState, stints_data: list[dict]) -> TireSignal:
        compound = state.compound.upper()
        deg_rate = _DEG_RATES.get(compound, _DEG_RATES["MEDIUM"])
        expected_life = _COMPOUND_LIFE.get(compound, _COMPOUND_LIFE["MEDIUM"])
        suggested_compound = _NEXT_COMPOUND.get(compound, "MEDIUM")
        recommend_pit = state.stint_lap > expected_life
        pit_window_laps = (state.lap, state.lap + 5) if recommend_pit else (0, 0)
        return TireSignal(
            driver=state.driver,
            recommend_pit=recommend_pit,
            suggested_compound=suggested_compound,
            pit_window_laps=pit_window_laps,
            deg_rate=deg_rate,
        )
