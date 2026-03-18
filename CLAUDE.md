# CLAUDE.md

> f1-strategist.ai — Real-time F1 race strategy optimization using a multi-agent swarm.
> Built for open source
> Stack: FastAPI · OpenF1 API · Claude claude-sonnet-4-6 · Python · uv

---

## Development workflow

After completing each task in `TASKS.md`:

1. Verify the expected outcomes listed in the task
2. **Commit before moving to the next task** — one commit per task, using `feat(scaffold): task N.M — <name>`
3. Then continue with `/scaffold`

---

## Local setup

```bash
uv sync                         # install deps, creates .venv automatically
cp .env.example .env            # fill in ANTHROPIC_API_KEY
uv run uvicorn api.main:app --reload  # start the server
```

### Verify the environment

```bash
uv run python -c "import fastapi, httpx, anthropic, pydantic, dotenv, uvicorn; print('all deps ok')"
```

### Run tests

```bash
uv run pytest tests/
```

### Replay a past race (offline)

```bash
uv run python scripts/replay.py --session 9158 --speed 10x
```

---

## Project overview

F1 strategy teams make pit stop decisions under extreme time pressure with incomplete data.
Smaller constructors (Haas, Sauber, etc.) can't afford massive strategy departments.
This system simulates a "pit wall brain" — a swarm of specialized AI agents that monitor
live race telemetry and push actionable strategy calls in real time.

**The hook**: "F1 teams spend millions on strategy engineers. I built an AI pit wall in a weekend."

---

## Agent architecture

```
OpenF1 stream
     │
     ▼
┌─────────────────┐
│  Orchestrator   │  Routes incoming events to the right subagents
└────────┬────────┘
         │
    ┌────┴──────────────────┐
    │           │           │
    ▼           ▼           ▼
┌────────┐ ┌─────────┐ ┌──────────────┐
│  Tire  │ │  Gap    │ │  Safety Car  │
│Analyst │ │Monitor  │ │   Detector   │
└────┬───┘ └────┬────┘ └──────┬───────┘
     │          │             │
     └──────────┴─────────────┘
                │
                ▼
        ┌───────────────┐
        │  Synthesizer  │  Resolves conflicts, weighs signals
        └───────┬───────┘
                │
                ▼
        ┌───────────────┐
        │ Strategy Call │  "Box now — undercut window open"
        └───────────────┘
```

---

## Agents — responsibilities

### 1. Orchestrator
- Polls OpenF1 `/position`, `/car_data`, `/intervals`, `/race_control` endpoints every ~2s
- Parses incoming events and fans out to relevant subagents
- Maintains shared race state (lap number, compound per driver, gap to leader)
- Does NOT make strategy calls itself — purely routes and coordinates

### 2. Tire strategist
- Tracks stint length and estimated degradation per compound
- Compares current lap delta against historical compound curves
- Outputs: recommended pit window (lap range), suggested compound switch
- Key signal: if lap delta is increasing > 0.3s/lap for 3 consecutive laps → flag for pit

### 3. Gap monitor
- Watches intervals between target driver and cars ahead/behind
- Calculates undercut viability: if gap to car ahead < pit loss time (~22s) → undercut window
- Calculates overcut viability: if car behind pits and gap > pit loss → stay out
- Outputs: "undercut open", "overcut viable", "gap neutral"

### 4. Safety car detector
- Monitors `/race_control` messages for VSC / SC / red flag events
- On SC: immediately signals orchestrator — free pit stop opportunity
- Calculates net gain of pitting under SC vs current strategy
- Outputs: "SC pit now", "SC — stay out (already on fresh rubber)"

### 5. Synthesizer
- Receives signals from all three subagents each polling cycle
- Resolves conflicts (e.g. gap monitor says stay out, tire analyst says pit now)
- Priority order: SC opportunity > undercut window > tire deg > gap neutral
- Calls Claude claude-sonnet-4-6 with all signals to generate final natural language recommendation
- Outputs: final strategy call string + confidence level + reasoning

---

## Data source — OpenF1 API

Base URL: `https://api.openf1.org/v1`

Key endpoints used:
- `GET /position?session_key={key}&driver_number={n}` — live positions
- `GET /car_data?session_key={key}&driver_number={n}` — speed, throttle, brake, gear
- `GET /intervals?session_key={key}` — gaps between drivers
- `GET /stints?session_key={key}` — current compound, lap entered on
- `GET /race_control?session_key={key}` — SC, VSC, flags, penalties
- `GET /sessions?year=2025&session_name=Race` — get latest session key

No auth required. Free. Rate limit: be polite (~1 req/s per endpoint).

Useful for testing: replay 2024 race sessions by filtering with `date` params.

---

## Project structure

```
f1-strategist.ai/
├── CLAUDE.md                  ← you are here
├── README.md
├── pyproject.toml             ← managed by uv
├── .env.example
│
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py        ← polls OpenF1, fans out to subagents
│   ├── tire_strategist.py
│   ├── gap_monitor.py
│   ├── safety_car_detector.py
│   └── synthesizer.py         ← calls Claude, produces final call
│
├── core/
│   ├── openf1_client.py       ← async HTTP client for OpenF1
│   ├── race_state.py          ← shared state object (dataclass)
│   └── models.py              ← pydantic models for agent signals
│
├── api/
│   └── main.py                ← FastAPI app, WebSocket endpoint for dashboard
│
└── tests/
    ├── test_tire_strategist.py
    ├── test_gap_monitor.py
    └── fixtures/              ← saved OpenF1 responses for offline testing
```

---

## Key data models

```python
# core/models.py

from pydantic import BaseModel
from enum import Enum

class TireSignal(BaseModel):
    driver: int
    recommend_pit: bool
    suggested_compound: str        # "SOFT" | "MEDIUM" | "HARD"
    pit_window_laps: tuple[int, int]
    deg_rate: float                # seconds per lap lost

class GapSignal(BaseModel):
    driver: int
    undercut_viable: bool
    overcut_viable: bool
    gap_ahead: float               # seconds
    gap_behind: float

class SafetyCarSignal(BaseModel):
    sc_active: bool
    vsc_active: bool
    pit_opportunity: bool
    reasoning: str

class StrategyCall(BaseModel):
    driver: int
    action: str                    # "BOX NOW" | "STAY OUT" | "MONITOR"
    confidence: float              # 0.0 - 1.0
    reasoning: str
    lap: int
```

---

## Synthesizer prompt (Claude)

```python
SYNTHESIZER_SYSTEM = """
You are a Formula 1 strategy engineer on the pit wall during a live race.
You receive signals from three specialist analysts every few seconds.
Your job: make one clear, confident strategy call per update.

Rules:
- Safety car opportunity always takes priority
- Be decisive. "Monitor" is only valid if no signal exceeds 70% confidence
- Keep calls under 20 words. Engineers are busy.
- Format: ACTION — one-line reasoning

Examples:
  BOX NOW — undercut window open, 2.1s gap to Verstappen
  STAY OUT — SC window missed, tires have 8 laps left
  BOX NOW — VSC deployed, free stop, switch to hards
"""
```

---

## Implementation order (suggested)

1. `core/openf1_client.py` — async polling client, test against a 2024 race replay
2. `core/race_state.py` — shared state dataclass, update on each poll
3. `agents/tire_strategist.py` — simplest agent, pure math on stint data
4. `agents/gap_monitor.py` — interval arithmetic
5. `agents/safety_car_detector.py` — parse race_control messages
6. `agents/synthesizer.py` — Claude call with all three signals
7. `agents/orchestrator.py` — wire everything together in an async loop
8. `api/main.py` — FastAPI + WebSocket so a frontend can subscribe
9. Frontend (optional) — simple HTML dashboard showing live strategy calls

---

## Testing strategy

- Save real OpenF1 API responses as JSON fixtures in `tests/fixtures/`
- Use the 2024 Monaco GP — lots of SC events, tire drama, undercut battles
- Unit test each agent independently against fixture data
- Integration test: replay a full race session at 10x speed

```bash
# replay a past race for testing
python -m scripts.replay --session 9158 --speed 10x
```

---

## Environment variables

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
OPENF1_BASE_URL=https://api.openf1.org/v1
TARGET_DRIVER=1          # Verstappen by default
POLL_INTERVAL_SECS=2
LOG_LEVEL=INFO
```

---

## LinkedIn post angle

> F1 teams spend millions on strategy engineers.
> I built an AI pit wall in a weekend.
>
> 5 agents. Live telemetry. Real-time strategy calls.
>
> Here's how it works 🧵

Show the architecture diagram. Show a sample strategy call output.
Tag: #AgenticAI #Formula1 #OpenSource #BuildingInPublic

Repo name suggestion: `f1-strategist.ai`