from core.models import GapSignal
from core.race_state import RaceState

_PIT_LOSS_SECS = 22.0
_OVERCUT_MIN_GAP_BEHIND = 25.0


def _parse_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class GapMonitor:
    def analyze(self, state: RaceState, intervals_data: list[dict]) -> GapSignal:
        gap_ahead = 0.0
        gap_behind = 0.0

        for entry in reversed(intervals_data):
            if entry.get("driver_number") == state.driver:
                ahead = _parse_float(entry.get("gap_to_leader"))
                behind = _parse_float(entry.get("interval"))
                if ahead is not None:
                    gap_ahead = ahead
                if behind is not None:
                    gap_behind = behind
                break

        undercut_viable = 0.0 < gap_ahead < _PIT_LOSS_SECS
        overcut_viable = gap_behind > _OVERCUT_MIN_GAP_BEHIND and gap_ahead >= _PIT_LOSS_SECS

        return GapSignal(
            driver=state.driver,
            undercut_viable=undercut_viable,
            overcut_viable=overcut_viable,
            gap_ahead=gap_ahead,
            gap_behind=gap_behind,
        )
