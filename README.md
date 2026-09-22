# TrainingPeaks Sync

[![Mauro Quality Gate](https://img.shields.io/badge/Mauro%20Quality%20Gate-Passed-2ea44f?style=flat&logo=github)](https://github.com/MauroDruwel/quality-gate)
[![CI](https://github.com/MauroDruwel/trainingpeaks-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/MauroDruwel/trainingpeaks-sync/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-171%20passed-brightgreen.svg)](#-running-tests)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/github/license/MauroDruwel/trainingpeaks-sync)](LICENSE)

Multi-source workout aggregator & synchronization bridge for [TrainingPeaks](https://www.trainingpeaks.com/). Fuses watch telemetry from **Strava**, swimming lane reservation tickets from **LAGO**, and university pool bookings from your **StudentApp** into enriched, verified TrainingPeaks activities — with **OpenAI-compatible AI coaching analysis**, automatic duration preservation during pool rest pauses, and synthetic workout generation if you forget your watch.

---

## 🌊 How It Works (The 3 Synchronized Sources)

When heading out for a swim, your session is captured across three distinct channels:

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
                   │     Workout Fusion Engine     │
                   │   • Time Correlation (±90m)   │
                   │   • Full Slot Duration Lock   │
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

1. **Watch Telemetry (Strava)**: Captures split times, distance, stroke cadence, heart rate, and indoor pool laps.
2. **LAGO Swimming Reservation**: Scans confirmation emails & PDF e-tickets (`Reserveringsbewijs.pdf` / `E-tickets.pdf`) sent to `swimming@maurodruwel.be` via IMAP to verify facility (e.g. LAGO Kortrijk Weide, Rozebroeken) and booked time slot.
3. **StudentApp Pool Booking**: Parses `.har` network exports or connects to the student sports API to verify campus pool reservations (e.g. GUSB Gent).

---

## ✨ Features

- 🏊 **Full Slot Duration Preservation**: Resting at the pool wall or auto-pauses in Strava won't truncate your workout. Automatically expands the session to your booked slot (e.g. 105 mins / 1h 45m) in both metadata and TCX trackpoints.
- ⌚ **"Forgot My Watch" Synthetic TCX**: Forgot your watch at home? The engine synthesizes a valid, TrainingPeaks-compliant TCX file with paced lap intervals from your verified reservation so your calendar never misses a workout.
- 🔗 **Smart Multi-Source Reconciler**: Correlates sessions occurring within a configurable window ($\pm 90$ mins) and enriches activities with facility names, reservation codes, and telemetry.
- ⏱️ **Headless & Cron-Ready**: Designed for unattended background automation via standard `crontab`, `systemd`, or built-in `--daemon` loop.
- 🧠 **Universal OpenAI-Compatible AI Coaching**: Connect to **any** OpenAI-compatible endpoint — local models (Ollama, LM Studio, vLLM) or cloud providers (OpenRouter, Groq, DeepSeek, OpenAI).
- 💾 **Idempotent Atomic State**: Persisted safely in `.sync_state.json` to prevent duplicates across runs.
- 📧 **Direct TrainingPeaks Upload**: Optionally emails generated `.tcx` workout files directly to your personal TrainingPeaks upload mailbox (`username.upload@trainingpeaks.com`).
- 🧪 **171 Automated Tests**: 100% test pass rate covering IMAP email parsing, HAR extraction, reconciler logic, TCX formatting, and CLI handlers.

---

## 🛠️ CLI Commands

The CLI tool is available as `tp-sync` (or `trainingpeaks-sync`):

| Command | What it does | Example |
| :--- | :--- | :--- |
| `tp-sync sync` | Run multi-source synchronization | `tp-sync sync --once` |
| `tp-sync sync --daemon` | Run continuous background sync loop | `tp-sync sync --daemon --interval 3600` |
| `tp-sync lago` | Inspect recent LAGO reservation confirmations from email | `tp-sync lago --days 7` |
| `tp-sync studentapp` | Inspect StudentApp pool bookings from HAR / API | `tp-sync studentapp --har session.har` |
| `tp-sync status` | Inspect pipeline status, credentials, and sync history | `tp-sync status` |
| `tp-sync auth` | Perform interactive Strava OAuth 2.0 setup | `tp-sync auth` |
| `tp-sync analyze` | Generate AI coaching feedback for an activity | `tp-sync analyze --activity-id 123456` |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/MauroDruwel/trainingpeaks-sync.git
cd trainingpeaks-sync

# Create virtual environment and install with uv
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

*Or with standard python:*
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
chmod 600 .env
```

---

## ⚙️ Configuration

All configuration is managed via environment variables in `.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| **Strava Telemetry** | | |
| `STRAVA_CLIENT_ID` | — | Strava API application client ID |
| `STRAVA_CLIENT_SECRET` | — | Strava API application client secret |
| `STRAVA_REFRESH_TOKEN` | — | Strava OAuth 2.0 refresh token |
| **LAGO Email Parser** | | |
| `LAGO_IMAP_SERVER` | `mailserver.maurodruwel.be` | IMAP mail server hostname |
| `LAGO_IMAP_PORT` | `993` | IMAP SSL port |
| `LAGO_MAILBOX_USER` | `sports@maurodruwel.be` | IMAP mailbox username |
| `LAGO_MAILBOX_PASSWORD` | — | IMAP mailbox password |
| `LAGO_TARGET_EMAIL` | `swimming@maurodruwel.be` | Target address where LAGO reservations are delivered |
| `LAGO_LOOKBACK_DAYS` | `7` | How many days back to scan for reservation emails |
| **StudentApp Pool Bookings** | | |
| `STUDENTAPP_HAR_PATH` | — | Path to `.har` export from StudentApp |
| `STUDENTAPP_API_URL` | — | Live StudentApp API endpoint (if applicable) |
| `STUDENTAPP_BEARER_TOKEN` | — | Bearer token for live API requests |
| **Multi-Source Fusion Engine** | | |
| `SYNTHETIC_WORKOUT_IF_NO_WATCH` | `true` | Generate synthetic TCX if watch was forgotten |
| `SYNTHETIC_SWIM_DISTANCE_METERS`| `2000` | Default distance for synthetic swim workouts |
| `SYNTHETIC_SWIM_DURATION_MINS` | `105` | Default duration (1h 45m) for swim workouts |
| `MATCH_WINDOW_MINUTES` | `90` | Correlation time window between watch & reservation |
| **OpenAI-Compatible AI Coaching** | | |
| `AI_COACHING_ENABLED` | `false` | Enable automated post-workout AI analysis |
| `AI_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint URL |
| `AI_MODEL` | `llama3.2` | Model identifier |
| `AI_API_KEY` | `ollama` | API key (or provider token) |
| **TrainingPeaks Output** | | |
| `ACTIVITIES_OUTPUT_DIR` | `./synced_activities` | Local directory for exported `.tcx` files |
| `SYNC_STATE_FILE` | `.sync_state.json` | Path to persistent sync state file |
| `TP_EMAIL` | — | Personal TrainingPeaks upload email (`user.upload@...`) |
| `SMTP_SERVER` | — | SMTP server for automated TCX email delivery |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |

---

## 🤖 OpenAI-Compatible AI Coaching

The analysis engine works with **any** OpenAI-compatible API:

| Provider | `AI_BASE_URL` | `AI_MODEL` | `AI_API_KEY` |
| :--- | :--- | :--- | :--- |
| **Local Ollama** | `http://localhost:11434/v1` | `llama3.2` | `ollama` |
| **Local LM Studio** | `http://localhost:1234/v1` | `local-model` | `lm-studio` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.2-3b-instruct` | `sk-or-v1-...` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | `sk-...` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | `gsk_...` |
| **OpenAI** | *(standard)* | `gpt-4o-mini` | `sk-proj-...` |

---

## ⏰ Automation & Cron

### Crontab Setup

To run a headless sync check every hour:

```bash
crontab -e

# Run hourly sync in the background
0 * * * * cd /path/to/trainingpeaks-sync && .venv/bin/tp-sync sync --once >> cron.log 2>&1
```

### Docker Container

```bash
# Build Docker image
docker build -t trainingpeaks-sync .

# Run continuous sync daemon
docker run -d \
  --name tp-sync \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/synced_activities:/app/synced_activities \
  trainingpeaks-sync
```

---

## 🧪 Running Tests

```bash
# Run full test suite
pytest -v

# Run with coverage report
pytest --cov=src --cov-report=term-missing
```

---

## 🏗️ Architecture & Code Quality

This project strictly adheres to the **[Mauro Quality Gate (MQG)](https://github.com/MauroDruwel/quality-gate)**:
- **Zero-Warning Strictness**: Clean linting and formatting via `ruff`.
- **Automated Testing**: 171 unit and integration tests across data ingestion, TCX generation, and multi-source reconciliation.
- **Atomic State**: Synchronization state is persisted atomically in `.sync_state.json` to prevent partial writes.
- **Secret Hygiene**: Sensitive credentials remain strictly inside `.env` (gitignored).

```
trainingpeaks-sync/
├── src/
│   ├── config.py                 # Unified configuration settings
│   ├── models.py                 # Core domain models (Sport, SwimReservation, FusedWorkout)
│   ├── cli.py                    # CLI entrypoint (sync, lago, studentapp, status, auth)
│   ├── sources/                  # Data ingestion providers
│   │   ├── strava.py             # Strava REST API & OAuth token refresh
│   │   ├── lago.py               # LAGO email parser & IMAP client
│   │   └── studentapp.py         # StudentApp HAR parser & API client
│   ├── fusion/                   # Reconciler & Synthetic workout generation
│   │   ├── reconciler.py         # Multi-source time correlation & slot duration lock
│   │   └── synthetic_tcx.py      # Generates valid TCX when watch is forgotten
│   ├── tcx/                      # TCX telemetry formatting & validation
│   │   ├── builder.py            # Stream to TCX converter
│   │   ├── formatter.py          # TrainingPeaks swim XML fixup & slot duration extension
│   │   └── processor.py          # Trackpoint cleaning & Euclidean reduction
│   ├── ai/                       # Universal OpenAI-compatible AI coaching
│   │   ├── analyzer.py           # Training analysis generator
│   │   └── tts.py                # Optional speech synthesis
│   └── sync/                     # Automation engine
│       ├── engine.py             # Multi-source orchestrator
│       ├── state.py              # Atomic JSON state persistence (.sync_state.json)
│       ├── scheduler.py          # Cron & daemon loops
│       └── email.py              # TrainingPeaks SMTP uploader
├── tests/                        # 171 comprehensive unit tests
├── pyproject.toml                # Modern Python packaging & tool configuration
├── Dockerfile                    # Background daemon container
├── Makefile                      # Developer targets (make test, make sync)
└── .env.example                  # Complete configuration template
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create your feature branch: `git checkout -b feat/amazing-feature`
3. Commit your changes: `git commit -m 'feat: add amazing feature'`
4. Push to the branch: `git push origin feat/amazing-feature`
5. Open a Pull Request

---

## 📄 License

MIT © [Mauro Druwel](https://maurodruwel.be)

---

<p align="center">
  Made with ❤️ by <a href="https://maurodruwel.be">Mauro Druwel</a> · ⭐ Star this repo if you find it useful!
</p>
