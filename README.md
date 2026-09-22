# TrainingPeaks Multi-Source Sync (Mauro Edition) ⚡

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-171%20passed-brightgreen.svg)](#running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An automated, intelligent multi-source workout aggregator and synchronization bridge for [TrainingPeaks](https://www.trainingpeaks.com/). Seamlessly reconciles watch telemetry from [Strava](https://www.strava.com/), swimming lane reservations from **LAGO**, and university pool bookings from your **StudentApp**, complete with **OpenAI-compatible AI coaching analysis** (Ollama, LM Studio, vLLM, OpenRouter, Groq, DeepSeek, or OpenAI) and unattended **cron / daemon automation**.

---

## 🌊 The Three Synchronized Sources

When you head out for a swim, your session is tracked across 3 distinct sources:

```
                  ┌───────────────────────────────┐
                  │ 1. Strava (Watch / Telemetry) │
                  │    Distance, HR, Pace, Laps   │
                  └───────────────┬───────────────┘
                                  │
┌─────────────────────────────┐   │   ┌─────────────────────────────┐
│ 2. LAGO Swimming Email      │   │   │ 3. StudentApp Pool Booking  │
│    swimming@maurodruwel.be  ├───┼───┤    .har Export or Live API  │
│    (sports@ IMAP Account)   │   │   │    Facility & Time Slot     │
└─────────────────────────────┘   │   └─────────────────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │   Workout Fusion Engine       │
                   │   • Time Correlation (±90m)   │
                   │   • Watch Forgotten? Synthetic│
                   └───────────────┬───────────────┘
                                  │
                                  ▼
                   ┌───────────────────────────────┐
                   │ TrainingPeaks Activity (.tcx) │
                   │ + AI Coaching Report (.md)    │
                   │ + Optional Email Auto-Upload  │
                   └───────────────────────────────┘
```

1. **Watch Telemetry (Strava)**: Captures distance, lap splits, stroke count, heart rate, and GPS/pool trackpoints.
2. **LAGO Swimming Reservation**: Scans confirmation emails received at `swimming@maurodruwel.be` (fetched from your `sports@maurodruwel.be` IMAP account) to verify pool facility (e.g. LAGO Gent Rozebroeken, Kortrijk Weide) and booked time slot.
3. **StudentApp Pool Booking**: Parses `.har` session exports or queries the student sports API directly to verify student pool sessions (e.g. GUSB Gent).

---

## 💡 Key Features & "Mauro Quality Gate"

- ⌚ **"Forgot My Watch" Synthetic TCX Generation**: Forgot to wear or start your watch at the pool? No problem! The reconciler automatically generates a valid TrainingPeaks-compatible TCX file from your verified LAGO / StudentApp reservation so your training calendar is never incomplete.
- 🔗 **Smart Session Reconciliation**: Correlates sessions occurring within a configurable time window (default: ±90 minutes). Fuses watch telemetry with reservation codes into a single enriched TrainingPeaks activity.
- ⏱️ **Runs Like a Cronjob**: Fully headless, non-interactive execution. Run via standard `crontab`, `systemd`, or the built-in `--daemon` loop.
- 🧠 **Universal OpenAI-Compatible AI Coaching**: Connect to **ANY** OpenAI-compatible endpoint — local models (Ollama, LM Studio, vLLM, LocalAI) or cloud providers (OpenRouter, Groq, DeepSeek, OpenAI).
- 💾 **Idempotent State Management**: Records processed workouts and reservations in `.sync_state.json`. Never duplicates activities or emails.
- 📧 **Optional Auto-Upload to TrainingPeaks**: Emails generated `.tcx` workout files directly to your personal TrainingPeaks upload address (`username.upload@trainingpeaks.com`) via standard SMTP.
- 🧪 **171 Automated Tests**: Comprehensive unit tests covering IMAP email parsing, HAR inspection, multi-source reconciliation, synthetic TCX formatting, AI analysis, and CLI routing.

---

## 🚀 Quick Start

### 1. Install

```bash
git clone https://github.com/MauroDruwel/trainingpeaks-sync.git
cd trainingpeaks-sync

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure your credentials:

```bash
cp .env.example .env
```

Example configuration:

```env
# 1. Strava Credentials
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret

# 2. LAGO Email Reservations
LAGO_ENABLED=true
LAGO_IMAP_SERVER=mail.maurodruwel.be
LAGO_IMAP_PORT=993
LAGO_IMAP_USER=sports@maurodruwel.be
LAGO_IMAP_PASSWORD=your_password
LAGO_TARGET_EMAIL=swimming@maurodruwel.be

# 3. StudentApp Bookings
STUDENTAPP_ENABLED=true
STUDENTAPP_HAR_PATH=./studentapp_session.har

# 4. Multi-Source Reconciliation
FUSION_AUTO_SYNTHETIC=true
SWIM_DEFAULT_DISTANCE_METERS=2000
SWIM_DEFAULT_DURATION_MINUTES=60
FUSION_TIME_WINDOW_MINUTES=90

# 5. AI Coach (Ollama example)
AI_ENABLED=true
AI_BASE_URL=http://localhost:11434/v1
AI_MODEL=llama3.2
AI_API_KEY=ollama
AI_LANGUAGE=English

# 6. Automation
SYNC_OUTPUT_DIR=./synced_activities
SYNC_INTERVAL=3600
SYNC_AUTO_ANALYZE=true
```

### 3. One-Time Strava Authorization

```bash
tp-sync auth
```

*(Optional for headless servers)*: Copy the generated `refresh_token` from `.strava_tokens.json` into `STRAVA_REFRESH_TOKEN` in `.env` to run headlessly without browser prompts forever.

---

## 💻 CLI Commands

The tool provides intuitive console scripts (`trainingpeaks-sync`, `tp-sync`, or `strava-sync`):

```bash
# Run multi-source sync (default one-shot mode)
tp-sync sync --once

# Run as background daemon (checks every hour)
tp-sync sync --daemon --interval 3600

# Inspect status of all 3 sources, AI, and destinations
tp-sync status

# Inspect LAGO reservation emails (from IMAP or .eml file)
tp-sync lago
tp-sync lago --eml ./path/to/confirmation.eml

# Inspect StudentApp pool bookings (from .har file)
tp-sync studentapp --har ./studentapp_session.har

# Analyze an existing TCX file with AI coach
tp-sync analyze ./assets/swim.tcx --sport Swim --plan "Endurance intervals 50m pool"

# Launch original interactive questionnaire
tp-sync interactive
```

---

## 🔄 Cronjob & Automation Setup

### Crontab Setup (One-Shot)

Run a sync check every hour:

```bash
crontab -e

# Add job:
0 * * * * cd /path/to/trainingpeaks-sync && .venv/bin/tp-sync sync --once >> cron.log 2>&1
```

### Docker Container

```bash
docker build -t trainingpeaks-sync .
docker run -d \
  --name tp-sync \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/synced_activities:/app/synced_activities \
  trainingpeaks-sync
```

---

## 🤖 Universal OpenAI-Compatible AI Coaching

The AI analysis engine supports any OpenAI-compatible provider:

| Provider | `AI_BASE_URL` | `AI_MODEL` | `AI_API_KEY` |
| :--- | :--- | :--- | :--- |
| **Local Ollama** | `http://localhost:11434/v1` | `llama3.2` | `ollama` |
| **Local LM Studio** | `http://localhost:1234/v1` | `local-model` | `lm-studio` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.2-3b-instruct` | `sk-or-v1-...` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | `sk-...` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | `gsk_...` |
| **OpenAI** | *(standard)* | `gpt-4o-mini` | `sk-proj-...` |

---

## 🏗️ Architecture

```
trainingpeaks-sync/
├── src/
│   ├── config.py                 # Unified settings (Strava, Lago, StudentApp, AI, Sync)
│   ├── models.py                 # Dataclasses (Sport, SwimReservation, FusedWorkout, ActivitySummary)
│   ├── cli.py                    # CLI entrypoint (sync, lago, studentapp, status, auth, analyze)
│   ├── sources/                  # Data ingestion providers
│   │   ├── strava.py             # Strava REST API & OAuth
│   │   ├── lago.py               # LAGO email parser & IMAP client
│   │   └── studentapp.py         # StudentApp HAR parser & API client
│   ├── fusion/                   # Reconciler & Synthetic workout generation
│   │   ├── reconciler.py         # Multi-source time correlation & deduplication
│   │   └── synthetic_tcx.py      # Generates valid TCX when watch is forgotten
│   ├── tcx/                      # TCX telemetry formatting & validation
│   │   ├── builder.py            # Stream to TCX converter
│   │   ├── formatter.py          # TrainingPeaks swim XML fixup & validation
│   │   └── processor.py          # Trackpoint cleaning & Euclidean reduction
│   ├── ai/                       # Universal OpenAI-compatible AI coaching
│   │   ├── analyzer.py           # Training analysis generator
│   │   └── tts.py                # Optional speech synthesis
│   └── sync/                     # Automation engine
│       ├── engine.py             # Multi-source orchestrator
│       ├── state.py              # Atomic JSON state persistence (.sync_state.json)
│       ├── scheduler.py          # Cron & daemon loops
│       └── email.py              # TrainingPeaks SMTP uploader
├── tests/                        # 165 comprehensive unit tests
├── pyproject.toml                # Modern Python packaging & tool configuration
├── Dockerfile                    # Background daemon container
├── Makefile                      # Developer targets (make test, make sync, etc.)
└── .env.example                  # Complete configuration template
```

---

## 🧪 Running Tests

```bash
# Run all tests
pytest -v

# Or use Makefile
make test

# Run tests with coverage
make test-cov
```

---

## 📜 License

MIT License — see [LICENSE](LICENSE) file for details.
