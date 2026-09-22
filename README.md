# Strava to TrainingPeaks (Mauro Edition) ⚡

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-149%20passed-brightgreen.svg)](#running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An automated, reliable bridge to sync your [Strava](https://www.strava.com/) workouts into [TrainingPeaks](https://www.trainingpeaks.com/), with **custom OpenAI-compatible AI coaching analysis** (Ollama, LM Studio, vLLM, OpenRouter, Groq, DeepSeek, or OpenAI) and **unattended cron / daemon automation**.

---

## 🌟 What's New & Cool in This Fork

- ⏱️ **Runs Like a Cronjob**: Fully headless, non-interactive sync engine. Run via `crontab`, `systemd`, or built-in `--daemon` loop.
- 🧠 **Universal OpenAI-Compatible AI Support**: Connect to **ANY** OpenAI-compatible API — local models (Ollama, LM Studio, vLLM, LocalAI) or cloud providers (OpenRouter, Groq, DeepSeek, OpenAI).
- 💾 **State Tracking & Idempotency**: Keeps track of processed workouts in `.sync_state.json`. Never downloads or processes the same activity twice.
- 🧹 **Clean Modular Architecture**: Cleanly separated into `src/strava/`, `src/tcx/`, `src/ai/`, `src/sync/`, and `src/cli.py` instead of a single monolithic script.
- 📦 **Lean Dependencies**: Wiped out bloat (`cx_Freeze`, unnecessary heavy dependencies) for maximum reliability and fast execution.
- 📧 **Optional Auto-Upload to TrainingPeaks**: Can automatically email generated TCX files to your TrainingPeaks upload address (`username.upload@trainingpeaks.com`) via SMTP.
- 🧪 **149 Automated Tests**: Comprehensive test suite covering config, sync engine, state persistence, TCX conversion, AI analyzer, and CLI.

---

## 🚀 Quick Start

### 1. Install

Clone the repository and install with pip or uv:

```bash
git clone https://github.com/MauroDruwel/strava-to-trainingpeaks.git
cd strava-to-trainingpeaks

# Using virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure your credentials:

```bash
cp .env.example .env
```

Minimal `.env` for automated sync:

```env
STRAVA_CLIENT_ID=123456
STRAVA_CLIENT_SECRET=abcdef1234567890abcdef1234567890

# AI Configuration (Ollama example)
AI_ENABLED=true
AI_BASE_URL=http://localhost:11434/v1
AI_MODEL=llama3.2
AI_API_KEY=ollama
AI_LANGUAGE=English

# Sync options
SYNC_OUTPUT_DIR=./synced_activities
SYNC_LIMIT=10
SYNC_AUTO_ANALYZE=true
```

### 3. One-Time Strava Authorization

Run the auth command to authorize your Strava account:

```bash
strava-sync auth
```

A browser window will open for you to grant read access. Once completed, your credentials are saved in `.strava_tokens.json`.

*(Optional for headless servers)*: You can copy the generated `refresh_token` into `STRAVA_REFRESH_TOKEN` in your `.env`, and your server will never need a browser or interactive prompt again!

---

## 🔄 Automation & Cronjob Setup

### Option 1: System Crontab (One-Shot)

Run a sync pass every hour using Linux crontab:

```bash
# Open crontab editor
crontab -e

# Add sync job to run every hour at minute 0:
0 * * * * cd /path/to/strava-to-trainingpeaks && .venv/bin/strava-sync sync --once >> cron_sync.log 2>&1
```

### Option 2: Built-in Daemon Mode

Run continuously in the background (sleeps between checks):

```bash
# Check every hour (3600 seconds)
strava-sync sync --daemon --interval 3600
```

### Option 3: Docker Container

Build and run as a lightweight container:

```bash
docker build -t strava-to-trainingpeaks .
docker run -d \
  --name strava-sync \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/synced_activities:/app/synced_activities \
  strava-to-trainingpeaks
```

---

## 🤖 Universal OpenAI-Compatible AI Coaching

The AI analysis engine works with any OpenAI-compatible provider:

| Provider | `AI_BASE_URL` | `AI_MODEL` | `AI_API_KEY` |
| :--- | :--- | :--- | :--- |
| **Local Ollama** | `http://localhost:11434/v1` | `llama3.2` | `ollama` |
| **Local LM Studio** | `http://localhost:1234/v1` | `model-identifier` | `lm-studio` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.2-3b-instruct` | `sk-or-v1-...` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | `sk-...` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | `gsk_...` |
| **OpenAI** | *(omit or standard)* | `gpt-4o-mini` | `sk-proj-...` |

When enabled (`SYNC_AUTO_ANALYZE=true`), an AI performance analysis is generated and saved as a markdown file alongside each downloaded TCX (e.g., `2026-09-22_Run_Morning_12345_analysis.md`).

---

## 💻 CLI Commands

The CLI provides intuitive subcommands:

```bash
# Run one-shot sync (default)
strava-sync sync --once

# Run sync in daemon mode
strava-sync sync --daemon --interval 1800

# Dry run: check what would be synced without saving files
strava-sync sync --dry-run

# Check system status, token health, and sync history
strava-sync status

# Authorize an athlete
strava-sync auth --name "Mauro"

# Run AI analysis on an existing TCX file
strava-sync analyze ./assets/run.tcx --sport Run --plan "Zone 2 base building"

# Launch the interactive questionnaire wizard
strava-sync interactive

# Launch coach multi-athlete manager
strava-sync coach
```

---

## 🏗️ Project Architecture

```
strava-to-trainingpeaks/
├── src/
│   ├── config.py             # Unified settings & .env loading
│   ├── models.py             # Data classes (Sport, AthleteToken, ActivitySummary)
│   ├── cli.py                # Command-line interface & subcommands
│   ├── strava/
│   │   ├── oauth.py          # OAuth2 flow & token storage
│   │   └── api.py            # Strava REST API client & streams fetcher
│   ├── tcx/
│   │   ├── builder.py        # Converts Strava telemetry streams to TCX XML
│   │   ├── formatter.py      # TCX validation & TrainingPeaks formatting
│   │   └── processor.py      # Trackpoint dataframe processing & Euclidean filtering
│   ├── ai/
│   │   ├── analyzer.py       # Universal OpenAI-compatible training analyzer
│   │   └── tts.py            # Optional text-to-speech audio generator
│   └── sync/
│       ├── engine.py         # Automation engine (download, format, analyze, dispatch)
│       ├── state.py          # Atomic JSON state persistence (.sync_state.json)
│       ├── scheduler.py      # Daemon & cron loop runner
│       └── email.py          # Optional TrainingPeaks email attachment uploader
├── tests/                    # 149 comprehensive unit tests
├── Dockerfile                # Production Docker container for daemon sync
├── Makefile                  # Developer commands (make test, make sync, etc.)
└── .env.example              # Documented configuration template
```

---

## 🧪 Running Tests

Run the full test suite using `pytest`:

```bash
# Run all tests
pytest -v

# Or use the Makefile
make test

# Run tests with coverage
make test-cov
```

---

## 📜 License

MIT License — see the [LICENSE](LICENSE) file for details.
