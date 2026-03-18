# AGENTS.md

> f1-strategist.ai - Real-time F1 race strategy optimization using a multi-agent swarm.
> Built for open source
> Stack: FastAPI · OpenF1 API · Claude `claude-sonnet-4-6` · Python · uv

---

## Purpose

This file is the working contract for Codex contributors in this repo.
Use it as the default execution guide for implementation, testing, and commits.

---

## Codex workflow (required)

After completing each task in `TASKS.md`:

1. Verify expected outcomes listed for that task.
2. Write pytest coverage in `tests/` for all testable logic (agents, core modules, API endpoints).
3. Run `uv run pytest tests/` and confirm all tests pass.
4. Commit before starting the next task (one commit per task).
5. Use commit format: `feat(scaffold): task N.M - <name>`.
6. Continue with the next unchecked task in `TASKS.md`.

Notes:
- Skip tests only for pure scaffolding/setup tasks.
- If a task requires networked APIs, prioritize fixture-backed tests for deterministic runs.

---

## Local setup

```bash
uv sync
cp .env.example .env
uv run uvicorn api.main:app --reload
```

### Verify environment

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
Smaller constructors (Haas, Sauber, etc.) cannot afford massive strategy departments.
This project simulates an AI pit wall: a swarm of specialized agents that monitor live telemetry and push actionable strategy calls in real time.

Hook:

> F1 teams spend millions on strategy engineers. I built an AI pit wall in a weekend.

---

## Agent architecture

```text
OpenF1 stream
     |
     v
+-----------------+
|  Orchestrator   |  Routes incoming events to the right subagents
+--------+--------+
         |
    +----+------------------+
    |           |           |
    v           v           v
+--------+ +---------+ +--------------+
|  Tire  | |  Gap    | |  Safety Car  |
|Analyst | |Monitor  | |   Detector   |
+----+---+ +----+----+ +------+-------+
     |          |             |
     +----------+-------------+
                |
                v
        +---------------+
        |  Synthesizer  |  Resolves conflicts, weighs signals
        +-------+-------+
                |
                v
        +---------------+
        | Strategy Call |  "BOX NOW - undercut window open"
        +---------------+
```

---

## Agent responsibilities

### 1. Orchestrator
- Poll OpenF1 `/position`, `/car_data`, `/intervals`, `/race_control` every ~2s.
- Parse incoming events and fan out to relevant subagents.
- Maintain shared race state (lap, compound per driver, gaps).
- Do not generate final strategy calls directly.

### 2. Tire strategist
- Track stint length and estimated degradation by compound.
- Compare current lap deltas against compound performance curves.
- Output: pit window (lap range), suggested compound.
- Rule of thumb: if lap delta worsens by >0.3s/lap for 3 consecutive laps, flag pit risk.

### 3. Gap monitor
- Watch intervals to cars ahead/behind.
- Undercut heuristic: if gap to car ahead < pit loss (~22s), undercut window is open.
- Overcut heuristic: if car behind pits and current gap > pit loss, staying out may be viable.
- Output: `undercut open`, `overcut viable`, or `gap neutral`.

### 4. Safety car detector
- Monitor `/race_control` for VSC/SC/red flag events.
- On SC/VSC, immediately signal orchestrator.
- Estimate net gain of pitting under neutralized conditions.
- Output: `SC pit now` or `SC stay out` with reasoning.

### 5. Synthesizer
- Receive all specialist signals each cycle.
- Resolve conflicts with priority:
  1. SC/VSC opportunity
  2. Undercut/overcut window
  3. Tire degradation
  4. Neutral/no-op signal
- Call Claude `claude-sonnet-4-6` to produce natural-language recommendation.
- Output: final strategy call string + confidence + reasoning.

---

## OpenF1 API usage

Base URL: `https://api.openf1.org/v1`

Key endpoints:
- `GET /position?session_key={key}&driver_number={n}`
- `GET /car_data?session_key={key}&driver_number={n}`
- `GET /intervals?session_key={key}`
- `GET /stints?session_key={key}`
- `GET /race_control?session_key={key}`
- `GET /sessions?year=2025&session_name=Race`

Guidelines:
- No auth required.
- Be polite with polling (about 1 req/sec per endpoint).
- For tests, prefer stored fixtures (e.g., 2024 sessions) over live network calls.

---

## Project structure

```text
f1-strategist.ai/
|- AGENTS.md
|- CLAUDE.md
|- README.md
|- pyproject.toml
|- .env.example
|
|- agents/
|  |- __init__.py
|  |- orchestrator.py
|  |- tire_strategist.py
|  |- gap_monitor.py
|  |- safety_car_detector.py
|  |- synthesizer.py
|
|- core/
|  |- openf1_client.py
|  |- race_state.py
|  |- models.py
|
|- api/
|  |- main.py
|
|- scripts/
|  |- replay.py
|
|- tests/
|  |- fixtures/
|  |- test_tire_strategist.py
|  |- test_gap_monitor.py
```

---

## Key data models

```python
from pydantic import BaseModel

class TireSignal(BaseModel):
    driver: int
    recommend_pit: bool
    suggested_compound: str
    pit_window_laps: tuple[int, int]
    deg_rate: float

class GapSignal(BaseModel):
    driver: int
    undercut_viable: bool
    overcut_viable: bool
    gap_ahead: float
    gap_behind: float

class SafetyCarSignal(BaseModel):
    sc_active: bool
    vsc_active: bool
    pit_opportunity: bool
    reasoning: str

class StrategyCall(BaseModel):
    driver: int
    action: str
    confidence: float
    reasoning: str
    lap: int
```

---

## Synthesizer prompt contract

```python
SYNTHESIZER_SYSTEM = """
You are a Formula 1 strategy engineer on the pit wall during a live race.
You receive signals from three specialist analysts every few seconds.
Your job: make one clear, confident strategy call per update.

Rules:
- Safety car opportunity always takes priority
- Be decisive. "MONITOR" only if no signal exceeds 70% confidence
- Keep calls under 20 words
- Format: ACTION - one-line reasoning

Examples:
  BOX NOW - undercut window open, 2.1s gap to car ahead
  STAY OUT - SC window missed, tires have 8 laps left
  BOX NOW - VSC deployed, free stop, switch to hards
"""
```

---

## Suggested implementation order

1. `core/openf1_client.py`
2. `core/race_state.py`
3. `agents/tire_strategist.py`
4. `agents/gap_monitor.py`
5. `agents/safety_car_detector.py`
6. `agents/synthesizer.py`
7. `agents/orchestrator.py`
8. `api/main.py`
9. Optional frontend dashboard

---

## Testing strategy

- Save real OpenF1 responses to `tests/fixtures/`.
- Use race sessions with strategic variation (SC/VSC, pit windows, undercut battles).
- Unit test each agent independently against fixtures.
- Add integration-style replay tests where practical.

```bash
uv run python scripts/replay.py --session 9158 --speed 10x
```

---

## Environment variables

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENF1_BASE_URL=https://api.openf1.org/v1
TARGET_DRIVER=1
POLL_INTERVAL_SECS=2
LOG_LEVEL=INFO
```

---

## Build-in-public angle

> F1 teams spend millions on strategy engineers.
> I built an AI pit wall in a weekend.
>
> 5 agents. Live telemetry. Real-time strategy calls.
>
> Here's how it works.

Tags: `#AgenticAI #Formula1 #OpenSource #BuildingInPublic`
