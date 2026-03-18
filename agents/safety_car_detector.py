from core.models import SafetyCarSignal
from core.race_state import RaceState

_SC_FLAG = "SAFETY CAR"
_VSC_FLAG = "VIRTUAL SAFETY CAR"
_CLEAR_FLAGS = {"GREEN", "CLEAR"}
_MIN_STINT_LAP_FOR_PIT = 5


class SafetyCarDetector:
    def analyze(self, state: RaceState, race_control_data: list[dict]) -> SafetyCarSignal:
        sc_active = False
        vsc_active = False

        for msg in race_control_data:
            flag = msg.get("flag", "")
            if flag == _SC_FLAG:
                sc_active = True
                vsc_active = False
            elif flag == _VSC_FLAG:
                vsc_active = True
                sc_active = False
            elif flag in _CLEAR_FLAGS:
                sc_active = False
                vsc_active = False

        opportunity = (sc_active or vsc_active) and state.stint_lap > _MIN_STINT_LAP_FOR_PIT

        if sc_active:
            reasoning = (
                "Safety car deployed — free pit stop opportunity"
                if opportunity
                else "Safety car deployed but just pitted, stay out"
            )
        elif vsc_active:
            reasoning = (
                "Virtual safety car active — reduced pit loss, consider stopping"
                if opportunity
                else "VSC active but just pitted, stay out"
            )
        else:
            reasoning = "No safety car — normal racing conditions"

        return SafetyCarSignal(
            sc_active=sc_active,
            vsc_active=vsc_active,
            pit_opportunity=opportunity,
            reasoning=reasoning,
        )
