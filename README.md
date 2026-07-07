# Weekly Schedule Generator

AI-assisted weekly household schedule generator. Pulls Google Calendar events, fetches notes from [Open Brain](https://github.com/NateBJones-Projects/OB1), analyzes work schedules, and generates a WhatsApp-ready family schedule using Claude — from the command line or a small web app.

Built for families juggling childcare, work commutes, caregiver handoffs, meals, activities, and recurring chores — the kind of coordination that usually lives in one parent's head.

> **Heads up:** this is one app in a larger personal "second brain" system. Household data (people, pets, schedules, dinners) lives in **Supabase**, managed by the family-calendar extension of [Open Brain / OB1](https://github.com/NateBJones-Projects/OB1). The generator reads that data and layers Google Calendar + Claude on top. You can adapt it to your own household, but it expects the Supabase schema described below — it is not a zero-config clone-and-run demo.

## What It Does

- **Pulls 3 Google Calendars** (personal, family, work) and filters out noise (birthdays, therapy, hold blocks)
- **Pulls Open Brain notes** — meal plans, family events, schedule changes captured during the week
- **Analyzes the work calendar** to compute ETA home each day and identify gym windows
- **Opens with a "Quick notes" summary** — key context for the family before the daily breakdown
- **Validates caregiver handoffs** — cross-checks end times vs. parent ETAs to catch coverage gaps
- **Detects scheduling conflicts** — ensures no person is double-booked
- **Computes babysitting arrival** — 45 minutes before event time when both parents are out
- **Places a family dinner** on the best available night
- **Assigns dinner** based on availability (not just "TBD")
- **Flags overtime** as explicit asks to the caregiver
- **Computes recurring events** — cleaner cadence, coop/volunteer shifts
- **Three output formats** — bullets (best for phone), person view, or compact grid

## Web App

A small FastAPI app wraps the generator in a browser UI:

```bash
python -m uvicorn weekly_schedule.web:app --port 8077
# then open http://localhost:8077
```

Views:
- **Run** — pick a week and format, drop in this week's notes, generate, and copy the result. Warning/ask lines are surfaced as flag chips.
- **Calendar** — a 7-day grid of your linked Google Calendars, with deep-links back to each event.
- **Configuration** — edit everything that used to require hand-editing YAML or the database:
  - **Work schedules** — each adult's work days, hours, and commute; the au pair's per-day hours (with a "balance" flex day). Written back to Supabase.
  - **Work calendar** — the Google Calendar whose meetings drive ETA-home and gym timing. Blank = none. (Editable so you're not stuck when a job changes.)
  - **People, pets & dinner defaults** — add / edit / remove household members and pets, and set who cooks each night.
  - **Output settings** — default format, WhatsApp group name, excluded-event regexes, and the keyword→emoji map.
- **History** — re-open previously generated schedules without regenerating (optional; requires the `schedule_runs` migration).

## Architecture

| Layer | Where it lives |
|-------|----------------|
| Household / recurring / dinner data | **Supabase** (family-calendar extension of OB1), read via [`weekly_schedule/db.py`](weekly_schedule/db.py) |
| App-behavior settings (format, group name, emoji map, excluded events, **work calendar**) | [`config.yaml`](config.example.yaml) `schedule_output` + `calendars` blocks (gitignored) |
| Personal & family calendar IDs, API keys | `.env` (gitignored) |
| Scheduling logic + Claude prompt | [`weekly_schedule/generate_schedule.py`](weekly_schedule/generate_schedule.py) |
| Web UI | [`weekly_schedule/web.py`](weekly_schedule/web.py) (JSON API) + [`weekly_schedule/templates/index.html`](weekly_schedule/templates/index.html) (single-page app) |

`load_config()` merges the Supabase household data with the `config.yaml` app-behavior settings. Conflict/coverage detection happens **inside the Claude prompt**, not as structured Python — the prompt encodes the household's rules (handoff validation, dinner assignment, gym logic) as instructions.

## Quick Start

**Requires Python 3.11+**

```bash
# 1. Create a virtual environment and install deps
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy .env.example to .env and fill in your secrets
cp .env.example .env

# 3. Copy the example config (app-behavior settings)
cp config.example.yaml config.yaml

# 4. Point at your Supabase household data (see Setup → Household data)

# 5. Run it
python -m weekly_schedule.generate_schedule                # next week (auto-detects Monday)
python -m weekly_schedule.generate_schedule 2026-04-13     # specific week
#   ...or launch the web app:
python -m uvicorn weekly_schedule.web:app --port 8077
```

## Setup

### Claude API Key
1. Go to https://console.anthropic.com/settings/keys
2. Create a new API key and add it to `.env` as `ANTHROPIC_API_KEY`
3. Ensure your account has credits (even $5 is plenty)

### Google Calendar
1. Go to [Google Cloud Console](https://console.cloud.google.com/), create a project, and enable the **Google Calendar API**
2. **APIs & Services > Credentials > Create Credentials > OAuth client ID** (Desktop app) → download the JSON → save as `credentials.json`
3. On the **OAuth consent screen**, add your Gmail as a test user
4. Find each calendar's ID (Google Calendar > Settings > calendar > "Integrate calendar" > Calendar ID)
5. Add to `.env`: `GCAL_PERSONAL_ID`, `GCAL_FAMILY_ID`. The **work calendar** is set in the Configuration page (or `config.yaml` `calendars.work`); `GCAL_WORK_ID` in `.env` is only a fallback.
6. First run opens a browser for OAuth. After authorizing, `token.json` is saved locally and auto-refreshed.

**Separate work account?** Share the work calendar with your personal Gmail (Work GCal > Settings > Share with specific people > "See all event details").

### Household data (Supabase)
Household members, pets, recurring events, and dinner defaults are stored in Supabase and managed by the family-calendar extension of [Open Brain / OB1](https://github.com/NateBJones-Projects/OB1). Add to `.env`:

```
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...        # server-side read/write (bypasses RLS)
DEFAULT_USER_ID=...                  # the user_id whose household to load
```

Once connected, you add and edit people, pets, and dinner defaults right in the **Configuration** page of the web app.

### Open Brain (optional)
If you use [Open Brain](https://github.com/NateBJones-Projects/OB1) for notes, the generator auto-pulls recent thoughts (meal plans, schedule changes, family events) as context. Add your MCP URL to `.env` as `OPEN_BRAIN_MCP_URL`:

```
https://YOUR_PROJECT_REF.supabase.co/functions/v1/open-brain-mcp?key=YOUR_ACCESS_KEY
```

### Run history (optional)
To enable the History view, apply the `schedule_runs` migration:

```bash
supabase link --project-ref YOUR_PROJECT_REF && supabase db push
# OR paste supabase/migrations/0001_schedule_runs.sql into the dashboard SQL editor
```

### Sunday auto-launch (macOS)

```bash
# Update the path in com.weekly-schedule.plist first
cp com.weekly-schedule.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.weekly-schedule.plist
```

Fires every Sunday at 1pm. Set a phone alarm as a backup reminder.

## The Claude prompt

The scheduling "brain" is the system prompt in [`weekly_schedule/generate_schedule.py`](weekly_schedule/generate_schedule.py). It uses template placeholders (`{pa}`, `{ra}`, `{ma}`, `{child}`, `{pet}`, …) that are filled from your household data at runtime, so the same rules work for any family. If your household's rules differ (handoff timing, dinner conventions, gym logic), that prompt is the place to adjust them.

Output format is set via `config.yaml` → `schedule_output.format`:
- **`bullets`** (default) — day headers with bullet points, easiest to scan on a phone
- **`person`** — grouped by person, best for "what's my week?"
- **`grid`** — compact text table, most information-dense

To filter events out of the schedule, add regex patterns in the Configuration page (or `config.yaml` → `schedule_output.excluded_events`); built-in patterns live in `EXCLUDED_EVENT_PATTERNS` in `weekly_schedule/generate_schedule.py`.

## Files

The runtime code lives in the `weekly_schedule/` package:

| Path | Purpose |
|------|---------|
| `weekly_schedule/generate_schedule.py` | Main script + Claude prompt + scheduling logic |
| `weekly_schedule/web.py` | FastAPI web app (JSON API behind the single-page UI) |
| `weekly_schedule/templates/index.html` | Single-page web UI (Run / Calendar / Configuration / History) |
| `weekly_schedule/db.py` | Supabase reads/writes for household data |
| `weekly_schedule/config_io.py` | Round-trip editor for the `config.yaml` app-behavior settings |
| `weekly_schedule/gcal.py` | Google Calendar integration |
| `weekly_schedule/open_brain.py` | Open Brain MCP integration |
| `weekly_schedule/entity_extraction.py` | Nightly entity-extraction queue drain |
| `weekly_schedule/runs.py` | Run-history persistence (optional) |
| `setup_wizard.py` | Interactive setup wizard for `config.yaml` |
| `config.example.yaml` | Example app-behavior config (copy to `config.yaml`) |
| `.env.example` | Template for `.env` |
| `supabase/` | Migrations + CLI config for the run-history table |
| `docs/example_schedules` | Example generated output |
| `spec-doc.md` | Full product spec |
| `com.weekly-schedule.plist` / `run.sh` | macOS launchd auto-run (Sunday 1pm) |

**Never committed** (gitignored): `.env`, `config.yaml`, `credentials.json`, `token.json` — anything with real names, addresses, or secrets.

## Automation Roadmap

- **Phase 1 (current)** — local script / web app, manual paste to WhatsApp
- **Phase 2** — scheduled cron + WhatsApp API auto-send
- **Phase 3** — one-tap approval + auto-pin

## License

MIT
