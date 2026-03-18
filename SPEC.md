# f1-strategist.ai

## Overview

f1-strategist.ai is a real-time Formula 1 race strategy system powered by a multi-agent AI swarm. It ingests live telemetry from the OpenF1 API and produces actionable pit stop recommendations — undercut windows, tire degradation alerts, and safety car opportunities — in plain English, every polling cycle. Built for smaller F1 constructors and open-source enthusiasts who can't afford a full strategy department.

---

# Goals

The system should:

- Poll live OpenF1 telemetry every ~2 seconds during a race session
- Detect undercut and overcut windows based on gap intervals
- Track tire degradation and flag optimal pit windows per compound
- Respond immediately to safety car and VSC events as free-stop opportunities
- Synthesize all signals into a single, confident strategy call via Claude
- Expose a WebSocket endpoint so a live dashboard can subscribe to calls

---

# Non Goals

The application will NOT initially support:

- Multi-driver simultaneous strategy tracking (single target driver only)
- Historical race analytics or post-race review UI
- Custom tire degradation model training
- Authentication or multi-user accounts
- Mobile app or native client

The focus is strictly real-time single-driver strategy recommendation during a live race session.

---

# Core Features

## Live Telemetry Polling

An async orchestrator polls four OpenF1 endpoints every 2 seconds: `/position`, `/intervals`, `/stints`, and `/race_control`. It maintains a shared race state object updated on each cycle and fans out events to the relevant subagents.

## Tire Strategy Analysis

The tire strategist tracks stint length and lap delta per compound. If lap delta increases more than 0.3s/lap for 3 consecutive laps, it flags a pit recommendation with a suggested compound and pit window range.

## Gap & Undercut/Overcut Monitoring

The gap monitor watches intervals to the car ahead and behind. If the gap ahead is less than estimated pit loss (~22s), an undercut window is flagged. If a car behind pits and the gap is large enough, an overcut is flagged as viable.

## Safety Car Detection

The safety car detector parses `/race_control` messages for SC, VSC, and red flag events. On an SC deployment, it immediately signals a free-stop opportunity and calculates net gain versus staying out on current rubber.

## Strategy Synthesis via Claude

The synthesizer receives signals from all three subagents each cycle and calls Claude claude-sonnet-4-6 to resolve conflicts and produce a final strategy call: action (`BOX NOW` / `STAY OUT` / `MONITOR`), confidence score, and one-line reasoning. Priority order: SC opportunity > undercut window > tire degradation > gap neutral.

## WebSocket Dashboard Feed

A FastAPI WebSocket endpoint streams strategy calls to any connected client in real time, enabling a live dashboard without polling.

---

# System Architecture

Single-process async Python application. An orchestrator loop runs on a timer, updates shared state, and dispatches to subagents concurrently. The synthesizer aggregates and calls the Claude API. FastAPI exposes a REST health endpoint and a WebSocket feed.

Core components:

- `agents/orchestrator.py` — polling loop, state dispatch
- `agents/tire_strategist.py` — tire degradation logic
- `agents/gap_monitor.py` — interval arithmetic
- `agents/safety_car_detector.py` — race control parser
- `agents/synthesizer.py` — Claude API call, final call output
- `core/openf1_client.py` — async HTTP client
- `core/race_state.py` — shared state dataclass
- `core/models.py` — Pydantic signal models
- `api/main.py` — FastAPI app + WebSocket endpoint

---

# Tech Stack

## Backend
Python 3.11+, FastAPI, asyncio

## Frontend
Optional — plain HTML/JS dashboard consuming the WebSocket feed

## Database
None — all state is in-memory per race session

## Background Jobs
Async polling loop via `asyncio` (no external queue)

## External APIs
- OpenF1 API (`https://api.openf1.org/v1`) — free, no auth, ~1 req/s rate limit
- Anthropic API (Claude claude-sonnet-4-6) — strategy synthesis

---

# Domain Models

## RaceState

Shared mutable object updated each polling cycle.

Fields include:

- `session_key` — OpenF1 session identifier
- `lap` — current lap number
- `driver` — target driver number
- `compound` — current tire compound
- `stint_lap` — laps on current stint
- `gap_ahead` / `gap_behind` — seconds to adjacent cars
- `sc_active` / `vsc_active` — safety car flags
- `last_updated` — timestamp of last poll

## TireSignal

Output from the tire strategist agent.

Fields include:

- `driver`, `recommend_pit`, `suggested_compound`
- `pit_window_laps` — tuple of (earliest, latest) lap
- `deg_rate` — seconds per lap lost

## GapSignal

Output from the gap monitor agent.

Fields include:

- `driver`, `undercut_viable`, `overcut_viable`
- `gap_ahead`, `gap_behind` — seconds

## SafetyCarSignal

Output from the safety car detector agent.

Fields include:

- `sc_active`, `vsc_active`, `pit_opportunity`, `reasoning`

## StrategyCall

Final output from the synthesizer.

Fields include:

- `driver`, `action` (`BOX NOW` / `STAY OUT` / `MONITOR`)
- `confidence` — float 0.0–1.0
- `reasoning` — one-line string
- `lap` — lap number when call was made

---

# Data Flow

1. Orchestrator fires every 2s, calls OpenF1 endpoints concurrently
2. Race state is updated with latest telemetry
3. Orchestrator dispatches updated state to all three subagents in parallel
4. Each subagent computes its signal and returns a typed Pydantic model
5. Synthesizer receives all three signals, builds a prompt, calls Claude
6. Claude returns a strategy call; synthesizer parses it into `StrategyCall`
7. FastAPI WebSocket endpoint broadcasts the call to all connected clients

---

# User Interface

## Live Dashboard (optional)

A single-page HTML/JS client connected via WebSocket.

Displays:

- Current lap, driver, tire compound, stint age
- Latest strategy call (action + reasoning + confidence)
- Rolling feed of last 10 calls
- SC/VSC indicator

---

# Security

The application must:

- Store `ANTHROPIC_API_KEY` in environment variables only — never in source
- Respect OpenF1 rate limits (~1 req/s per endpoint) to avoid IP bans
- Validate all OpenF1 responses before passing to agents (Pydantic parsing)

---

# Milestones

## Milestone 1 — Core Data Pipeline
OpenF1 async client, race state model, and fixture-based tests against a 2024 race replay.

## Milestone 2 — Subagents
Tire strategist, gap monitor, and safety car detector — each unit-tested against fixture data.

## Milestone 3 — Synthesis & API
Synthesizer with Claude integration, orchestrator wiring all agents, FastAPI + WebSocket endpoint live.

## Milestone 4 — Dashboard & Polish
Optional HTML dashboard, replay script for offline testing at 10x speed, README and LinkedIn post assets.
