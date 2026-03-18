# TASKS.md

This file defines the incremental implementation tasks for f1-strategist.ai.

Claude should only complete **one task at a time** and should not attempt to implement future tasks unless required for scaffolding.

Each task should leave the application in a **runnable state**.

---

# Phase 1 — Project Foundation

## Task 1.1 — Project scaffold and dependencies

Set up the Python project structure, virtual environment config, and all required dependencies.

Requirements:

- Create `pyproject.toml` with dependencies: `fastapi`, `uvicorn`, `httpx`, `pydantic`, `anthropic`, `python-dotenv`
- Create `.env.example` with all required env vars: `ANTHROPIC_API_KEY`, `OPENF1_BASE_URL`, `TARGET_DRIVER`, `POLL_INTERVAL_SECS`, `LOG_LEVEL`
- Create empty `__init__.py` files for `agents/`, `core/`, `api/`, `tests/` packages
- Create `tests/fixtures/` directory with a `.gitkeep`

Expected outcomes:

- `pyproject.toml` is valid and `pip install -e .` succeeds
- All package directories exist with `__init__.py`
- `.env.example` documents every required variable

---

## Task 1.2 — Pydantic domain models

Implement all typed signal and state models in `core/models.py`.

Requirements:

- Define `TireSignal` with fields: `driver: int`, `recommend_pit: bool`, `suggested_compound: str`, `pit_window_laps: tuple[int, int]`, `deg_rate: float`
- Define `GapSignal` with fields: `driver: int`, `undercut_viable: bool`, `overcut_viable: bool`, `gap_ahead: float`, `gap_behind: float`
- Define `SafetyCarSignal` with fields: `sc_active: bool`, `vsc_active: bool`, `pit_opportunity: bool`, `reasoning: str`
- Define `StrategyCall` with fields: `driver: int`, `action: str` (enum: `BOX NOW`, `STAY OUT`, `MONITOR`), `confidence: float`, `reasoning: str`, `lap: int`
- All models extend `pydantic.BaseModel`

Expected outcomes:

- `from core.models import TireSignal, GapSignal, SafetyCarSignal, StrategyCall` succeeds
- Each model can be instantiated with valid data and rejects invalid data

---

## Task 1.3 — Race state dataclass

Implement the shared mutable race state in `core/race_state.py`.

Requirements:

- Define `RaceState` as a Python `dataclass` with fields: `session_key: str`, `lap: int`, `driver: int`, `compound: str`, `stint_lap: int`, `gap_ahead: float`, `gap_behind: float`, `sc_active: bool`, `vsc_active: bool`, `last_updated: float` (unix timestamp)
- Provide a `RaceState.default(session_key, driver)` classmethod returning a zeroed initial state
- Include a `update_from_poll(...)` method that accepts raw OpenF1 response dicts and mutates the state in place

Expected outcomes:

- `RaceState.default("9158", 1)` returns a valid zeroed state
- `update_from_poll` mutates fields without raising on partial data (missing keys default to existing values)

---

# Phase 2 — OpenF1 Data Pipeline

## Task 2.1 — Async OpenF1 HTTP client

Implement the async HTTP client in `core/openf1_client.py`.

Requirements:

- Use `httpx.AsyncClient` with base URL from `OPENF1_BASE_URL` env var
- Implement async methods: `get_positions(session_key, driver)`, `get_intervals(session_key)`, `get_stints(session_key, driver)`, `get_race_control(session_key)`
- Each method returns the raw parsed JSON list (no transformation)
- Respect ~1 req/s per endpoint — add a configurable `request_delay` param (default 0.1s between requests)
- Raise a custom `OpenF1Error` on non-200 responses

Expected outcomes:

- Client can be instantiated and all four methods called against live `https://api.openf1.org/v1`
- Returns non-empty list for a known 2024 session key (e.g. `9158`)
- `OpenF1Error` raised on a 429 or 500 response (test with mock)

---

## Task 2.2 — Save OpenF1 fixtures for offline testing

Fetch and save real OpenF1 API responses as JSON fixtures for the 2024 Monaco GP (session key `9158`, driver `1`).

Requirements:

- Create `scripts/save_fixtures.py` that calls all four client methods and writes results to `tests/fixtures/`
- Save as: `positions.json`, `intervals.json`, `stints.json`, `race_control.json`
- Script accepts `--session` and `--driver` CLI args

Expected outcomes:

- Running `python scripts/save_fixtures.py --session 9158 --driver 1` creates four fixture files
- Each fixture file is valid JSON with at least one record

---

# Phase 3 — Subagents

## Task 3.1 — Tire strategist agent

Implement `agents/tire_strategist.py`.

Requirements:

- Define `TireStrategist` class with method `analyze(state: RaceState, stints_data: list[dict]) -> TireSignal`
- Flag `recommend_pit=True` if lap delta (estimated from `stint_lap` and `deg_rate`) has increased >0.3s/lap for 3 consecutive laps
- `deg_rate` calculated as total lap time increase / stint laps (use compound baseline constants: SOFT=0.08s/lap, MEDIUM=0.05s/lap, HARD=0.03s/lap)
- `pit_window_laps` = (current lap, current lap + 5) when recommending pit, else (0, 0)
- `suggested_compound` rotates: SOFT→MEDIUM→HARD based on current compound

Expected outcomes:

- `analyze()` returns a valid `TireSignal`
- Unit test in `tests/test_tire_strategist.py` using `stints.json` fixture passes
- `recommend_pit=True` when stint_lap > compound's expected life (SOFT=25, MEDIUM=35, HARD=45)

---

## Task 3.2 — Gap monitor agent

Implement `agents/gap_monitor.py`.

Requirements:

- Define `GapMonitor` class with method `analyze(state: RaceState, intervals_data: list[dict]) -> GapSignal`
- Parse `intervals_data` to extract `gap_to_leader` and compute `gap_ahead` / `gap_behind` for the target driver
- `undercut_viable=True` if `gap_ahead < 22.0` (estimated pit loss in seconds)
- `overcut_viable=True` if `gap_behind > 25.0` and `gap_ahead > 22.0`

Expected outcomes:

- `analyze()` returns a valid `GapSignal`
- Unit test in `tests/test_gap_monitor.py` using `intervals.json` fixture passes
- Correctly identifies undercut/overcut scenarios from fixture data

---

## Task 3.3 — Safety car detector agent

Implement `agents/safety_car_detector.py`.

Requirements:

- Define `SafetyCarDetector` class with method `analyze(state: RaceState, race_control_data: list[dict]) -> SafetyCarSignal`
- Parse `race_control_data` messages; detect SC by `flag == "SAFETY CAR"`, VSC by `flag == "VIRTUAL SAFETY CAR"`
- `pit_opportunity=True` when SC or VSC is active and `state.stint_lap > 5` (not just pitted)
- `reasoning` should be a human-readable string explaining the recommendation

Expected outcomes:

- `analyze()` returns a valid `SafetyCarSignal`
- Unit test in `tests/test_safety_car_detector.py` using `race_control.json` fixture passes
- Correctly fires `pit_opportunity=True` on known SC events in fixture data

---

# Phase 4 — Synthesis & Orchestration

## Task 4.1 — Synthesizer agent

Implement `agents/synthesizer.py`.

Requirements:

- Define `Synthesizer` class with async method `synthesize(tire: TireSignal, gap: GapSignal, sc: SafetyCarSignal, state: RaceState) -> StrategyCall`
- Load `ANTHROPIC_API_KEY` from env; use `anthropic.AsyncAnthropic` client
- Use model `claude-sonnet-4-6`
- Build a prompt combining all three signals; use the system prompt defined in `CLAUDE.md`
- Parse Claude's response into `StrategyCall` — extract action, confidence, and reasoning
- Priority fallback: if Claude call fails, derive action from signal priorities (SC > undercut > tire deg > neutral)

Expected outcomes:

- `synthesize()` returns a valid `StrategyCall` with `action` in `["BOX NOW", "STAY OUT", "MONITOR"]`
- Works end-to-end with a live Anthropic API key
- Fallback logic returns a valid call even when `ANTHROPIC_API_KEY` is unset

---

## Task 4.2 — Orchestrator

Implement `agents/orchestrator.py`.

Requirements:

- Define `Orchestrator` class with async method `run(session_key: str, driver: int)` that runs the polling loop
- Each cycle: call all four OpenF1 client methods concurrently via `asyncio.gather`
- Update `RaceState` via `update_from_poll`
- Dispatch to `TireStrategist`, `GapMonitor`, `SafetyCarDetector` concurrently
- Pass all signals to `Synthesizer` and emit the resulting `StrategyCall`
- Loop every `POLL_INTERVAL_SECS` (default 2) seconds; log each call to stdout
- Expose a `subscribe(callback)` method so the API layer can register a WebSocket broadcast function

Expected outcomes:

- `Orchestrator.run("9158", 1)` starts without error and emits at least one `StrategyCall` within 10s
- Concurrent polling does not exceed OpenF1 rate limits
- Subscriber callback is invoked with each new `StrategyCall`

---

# Phase 5 — API Layer

## Task 5.1 — FastAPI app with WebSocket endpoint

Implement `api/main.py`.

Requirements:

- Create a `FastAPI` app instance
- `GET /health` returns `{"status": "ok"}`
- `GET /state` returns the current `RaceState` as JSON
- `WebSocket /ws/strategy` streams each new `StrategyCall` as JSON to all connected clients
- On startup (`lifespan`), instantiate `Orchestrator` and start the polling loop as a background `asyncio.Task`
- Manage a set of active WebSocket connections; broadcast to all on each new call
- Load session key and driver from env vars `SESSION_KEY` (add to `.env.example`) and `TARGET_DRIVER`

Expected outcomes:

- `uvicorn api.main:app --reload` starts without error
- `GET /health` returns 200
- WebSocket client receives `StrategyCall` JSON within one polling cycle of connecting
- Disconnected clients are removed from the broadcast set without crashing

---

# Phase 6 — Dashboard & Polish

## Task 6.1 — Replay script for offline testing

Implement `scripts/replay.py` for offline race replay.

Requirements:

- Accept `--session` and `--speed` (e.g. `10x`) CLI args
- Load fixture data from `tests/fixtures/` and simulate telemetry updates at the scaled speed
- Feed data through the full agent pipeline and print each `StrategyCall` to stdout with timestamp
- Does not require a live OpenF1 connection

Expected outcomes:

- `python scripts/replay.py --session 9158 --speed 10x` runs without error
- Emits at least 5 strategy calls using fixture data
- Exits cleanly when fixture data is exhausted

---

## Task 6.2 — HTML dashboard

Implement `api/static/index.html` — a single-page live strategy dashboard.

Requirements:

- Connect to `ws://localhost:8000/ws/strategy` on load
- Display current lap, driver number, tire compound, and stint age
- Show the latest strategy call prominently: action badge (color-coded: red=BOX NOW, green=STAY OUT, yellow=MONITOR), confidence %, and reasoning
- Show a scrolling feed of the last 10 calls
- Show a SC/VSC active indicator that turns red when `sc_active` or `vsc_active` is true
- Pure HTML/CSS/JS — no build step, no npm

Expected outcomes:

- Opening `index.html` in a browser while the server runs shows live strategy calls
- Action badge updates color on each new call
- SC indicator activates correctly from fixture data

---

## Task 6.3 — README and .env.example polish

Finalize the project README and environment config for open-source release.

Requirements:

- Update `README.md` with: project description, architecture diagram (ASCII from `CLAUDE.md`), quickstart instructions (`pip install`, `.env` setup, `uvicorn` command), and replay usage
- Ensure `.env.example` includes `SESSION_KEY` added in Task 5.1
- Add `LICENSE` confirmation (already present) and `.gitignore` covering `.env`, `__pycache__`, `.venv`

Expected outcomes:

- A new contributor can follow `README.md` to run the project locally from scratch
- `.env.example` documents every env var used in the codebase
- `.gitignore` prevents `.env` from being committed
