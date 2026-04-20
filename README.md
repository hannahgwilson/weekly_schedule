# Weekly Schedule Generator

AI-assisted weekly household schedule generator. Pulls Google Calendar events, fetches notes from [Open Brain](https://github.com/NateBJones-Projects/OB1), analyzes work schedules, and generates a WhatsApp-ready family schedule using Claude.

Built for families juggling childcare, work commutes, caregiver handoffs, meals, activities, and recurring chores — the kind of coordination that usually lives in one parent's head.

## What It Does

- **Pulls 3 Google Calendars** (personal, family, work) and filters out noise (birthdays, therapy, hold blocks)
- **Pulls Open Brain notes** — meal plans, family events, schedule changes captured during the week
- **Analyzes work schedules** to compute ETA home each day and identify gym windows
- **Opens with a "Quick notes" summary** — key context for the family before the daily breakdown
- **Validates caregiver handoffs** — cross-checks end times vs. parent ETAs to catch coverage gaps
- **Detects scheduling conflicts** — ensures no person is double-booked
- **Computes babysitting arrival** — 45 minutes before event time when both parents are out
- **Places a family dinner** on the best available night
- **Assigns dinner** based on availability (not just "TBD")
- **Flags overtime** as explicit asks to the caregiver
- **Computes recurring events** — cleaner cadence, coop/volunteer shifts
- **Three output formats** — bullets (best for phone), person view, or compact grid

## Quick Start

**Requires Python 3.11+**

```bash
# 1. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy .env.example to .env and fill in your secrets
cp .env.example .env
# Edit .env with your API keys and calendar IDs

# 4. Copy config.example.yaml to config.yaml and customize for your household
cp config.example.yaml config.yaml
# Edit config.yaml with your family members, schedules, recurring events

# 5. Run it
python generate_schedule.py                # next week (auto-detects Monday)
python generate_schedule.py 2026-04-13     # specific week
```

The script will:
1. Authenticate with Google Calendar
2. Fetch and display your events (personal + family + work analysis)
3. Pull recent notes from Open Brain (if configured)
4. Prompt you for any additional notes
5. Generate a formatted schedule via Claude API
6. Copy it to your clipboard for pasting into WhatsApp

## Setup

### Claude API Key
1. Go to https://console.anthropic.com/settings/keys
2. Create a new API key
3. Add it to `.env` as `ANTHROPIC_API_KEY`
4. Ensure your account has credits (even $5 is plenty)

### Google Calendar
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Google Calendar API**
3. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID** (Desktop app)
4. Download the JSON file → save as `credentials.json` in this directory
5. **OAuth consent screen:** Add your Gmail as a test user
6. Find your calendar IDs (Google Calendar > Settings > calendar > "Integrate calendar" > Calendar ID)
7. Add to `.env`: `GCAL_PERSONAL_ID`, `GCAL_FAMILY_ID`, `GCAL_WORK_ID`
8. First run opens a browser for OAuth. After authorizing, `token.json` is saved locally. If the token later expires, the script will automatically re-open the browser to re-authenticate.

**Work calendar note:** If your work Google account is separate, share the work calendar with your personal Gmail (Work GCal > Settings > Share with specific people > add your personal email with "See all event details").

### Open Brain (Optional)
If you use [Open Brain](https://github.com/NateBJones-Projects/OB1) for personal knowledge management, the generator can auto-pull recent notes (meal plans, schedule changes, family events) and include them as context.

1. Set up Open Brain per the [OB1 guide](https://promptkit.natebjones.com/20260224_uq1_guide_main)
2. Add your MCP URL to `.env` as `OPEN_BRAIN_MCP_URL`
   - Format: `https://YOUR_PROJECT_REF.supabase.co/functions/v1/open-brain-mcp?key=YOUR_ACCESS_KEY`

### Customizing for Your Household

Edit `config.yaml` with your family's details:
- **Adults**: names, roles, work hours, commute, activities
- **Children**: age, classes, nap/bedtime
- **Pets**: walk schedule, dog walker days
- **Caregiver**: weekly hours, daily schedule
- **Recurring events**: cleaner cadence, volunteer shifts
- **Dinner defaults**: who cooks which nights
- **Output format**: bullets, person view, or grid

The system prompt in `generate_schedule.py` uses template variables (`{primary}`, `{pa}`, `{partner}`, `{ra}`, etc.) that are automatically filled from your `config.yaml` at runtime. You may also want to adjust the scheduling rules (handoff validation, conflict detection, gym logic, etc.) to match your household.

### Sunday Auto-Launch (macOS)

```bash
# Update the path in com.weekly-schedule.plist first
cp com.weekly-schedule.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.weekly-schedule.plist
```

Fires every Sunday at 1pm. Set a phone alarm as a backup reminder.

## Configuration

All household rules live in `config.yaml` (committed). All secrets live in `.env` (gitignored).

To filter events from your work calendar, add regex patterns to `EXCLUDED_EVENT_PATTERNS` in `generate_schedule.py`.

### Output Formats

Configurable via `config.yaml` → `schedule_output.format`:
- **`bullets`** (default) — Day headers with bullet points, easiest to scan on a phone
- **`person`** — Grouped by person, best for "what's my week?"
- **`grid`** — Compact text table, most information-dense

## Files

| File | Purpose | Committed? |
|------|---------|------------|
| `generate_schedule.py` | Main script + Claude prompt + scheduling logic | Yes |
| `gcal.py` | Google Calendar integration | Yes |
| `open_brain.py` | Open Brain MCP integration | Yes |
| `config.example.yaml` | Example household config (copy to `config.yaml`) | Yes |
| `config.yaml` | Your household config | **No** (gitignored) |
| `.env` | API keys, calendar IDs, Open Brain URL | **No** (gitignored) |
| `.env.example` | Template for `.env` | Yes |
| `credentials.json` | Google OAuth client secret | **No** (gitignored) |
| `token.json` | Google OAuth refresh token | **No** (gitignored) |
| `run.sh` | Shell wrapper for launchd | Yes |
| `com.weekly-schedule.plist` | macOS launchd config (Sunday 1pm) | Yes |
| `spec-doc.md` | Full product spec | Yes |
| `docs/example_schedules` | Example schedule outputs for reference | Yes |

## Automation Roadmap

- **Phase 1 (current)**: Local script, manual paste to WhatsApp
- **Phase 2**: GitHub Actions cron + WhatsApp API auto-send
- **Phase 3**: One-tap approval + auto-pin

## License

MIT
