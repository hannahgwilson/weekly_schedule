# Weekly Schedule — project notes for Claude

AI-assisted weekly household schedule generator. Pulls 3 Google Calendars + Open Brain
notes, analyzes work schedules, and generates a WhatsApp-ready family schedule via Claude.
See [README.md](README.md) for the full feature list, setup, and usage.

## How to run

Runtime code lives in the `weekly_schedule/` package; run everything from the repo root
so the package is importable.

```bash
# Web UI
python -m uvicorn weekly_schedule.web:app --port 8077 --log-level warning
# CLI
python -m weekly_schedule.generate_schedule            # next week
python -m weekly_schedule.generate_schedule 2026-04-13 # specific Monday
```

Config, secrets, and OAuth files (`config.yaml`, `.env`, `credentials.json`, `token.json`)
live at the repo root; the package resolves them via `Path(__file__).resolve().parent.parent`.

## Architecture

Household/recurring/dinner data lives in **Supabase** (family-calendar extension of OB1),
read via [weekly_schedule/db.py](weekly_schedule/db.py); `load_config()` merges DB + yaml.
App-behavior settings (format, emoji map, group name, excluded-event regexes) live in
**`config.yaml`** `schedule_output:` block (gitignored). The **work calendar id** is
editable and lives in `config.yaml` `calendars.work` (blank = none; falls back to
`GCAL_WORK_ID` only if the key is absent) — `_resolve_cal_ids()` in
[weekly_schedule/generate_schedule.py](weekly_schedule/generate_schedule.py) resolves it.
Personal & family calendar ids come from `.env`. The adults' **work schedules** (work
days/hours, commute, leaves/returns, au-pair daily hours) are editable in the Config page
and written back to Supabase via `db.fetch_adult_schedules()` / `db.save_adult_schedule()`.
Conflict/coverage detection happens **inside the Claude prompt**, not as structured Python.

### Web UI
- [weekly_schedule/web.py](weekly_schedule/web.py) — FastAPI JSON API. Endpoints:
  `GET /`, `GET /api/events`, `POST /api/generate`, `POST /api/capture`,
  `POST /api/process-entities`, `GET|POST /api/config`, `GET /api/work-schedules`,
  `POST /api/work-schedules`, `GET /api/household`, `POST /api/household/{people,pets,dinner}`,
  `GET /api/history`. `_extract_flags()` scrapes warning lines (‼️ ⚠️ 🐣 / "coverage gap",
  "overtime", "behind", "conflict") from generated output for badge chips.
- [weekly_schedule/templates/index.html](weekly_schedule/templates/index.html) — single-page
  app shell (vanilla JS + fetch), sage/clay light palette, responsive. Views: **Run**
  (format toggle, notes, generate, flag chips, copy), **Calendar** (7-day GCal grid with
  deep-links), **Configuration** (emoji-map/format/excluded editing, **editable work
  schedules + work calendar**, and **full add/edit/remove of people, pets & dinner
  defaults** — all written to Supabase/yaml), **History**. People/pets save via reconcile
  (omitted rows are deleted; FKs cascade or null). `db.fetch_household_editable()` /
  `save_household_people()` / `save_household_pets()` / `save_dinner_defaults()` back it.
- [weekly_schedule/config_io.py](weekly_schedule/config_io.py) — round-trip YAML editor
  (ruamel) so saving config keeps comments. `width=4096` (no re-wrap), `allow_unicode=True`.
- [weekly_schedule/runs.py](weekly_schedule/runs.py) — run-history persistence to Supabase
  `schedule_runs`. Degrades gracefully (empty/no-op) if table not migrated or creds absent.
- [weekly_schedule/gcal.py](weekly_schedule/gcal.py) — `fetch_events()` returns `id` +
  `html_link` (event deep-links).

### Supabase
Household data is served by the family-calendar extension of OB1; this repo only carries the
`schedule_runs` migration for the optional History view. Set `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `DEFAULT_USER_ID` in `.env`. To enable History, apply
`supabase/migrations/0001_schedule_runs.sql` (via `supabase db push` after linking, or the
dashboard SQL editor).

## Notes
- Editing the excluded-events list via the Config textarea drops inline YAML comments
  (e.g. `# therapist`) — inherent to textarea editing.
