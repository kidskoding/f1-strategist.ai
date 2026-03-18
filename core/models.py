from enum import Enum

from pydantic import BaseModel, Field


class Action(str, Enum):
    BOX_NOW = "BOX NOW"
    STAY_OUT = "STAY OUT"
    MONITOR = "MONITOR"


class TireSignal(BaseModel):
    driver: int
    recommend_pit: bool
    suggested_compound: str  # "SOFT" | "MEDIUM" | "HARD"
    pit_window_laps: tuple[int, int]
    deg_rate: float  # seconds per lap lost


class GapSignal(BaseModel):
    driver: int
    undercut_viable: bool
    overcut_viable: bool
    gap_ahead: float  # seconds
    gap_behind: float  # seconds


class SafetyCarSignal(BaseModel):
    sc_active: bool
    vsc_active: bool
    pit_opportunity: bool
    reasoning: str


class StrategyCall(BaseModel):
    driver: int
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    lap: int
