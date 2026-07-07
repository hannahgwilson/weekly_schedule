# Weekly Schedule — project notes for Claude

AI-assisted weekly household schedule generator. Pulls 3 Google Calendars + Open Brain
notes, analyzes work schedules, and generates a WhatsApp-ready family schedule via Claude.
See [README.md](README.md) for the full feature list and CLI usage.

## How to run

**Use `hdubs.venv` — it is the live environment.** The `.venv` is broken: its shebang
points at a stale `weekly_schedule` (underscore) path from before the dir was renamed with
a hyphen. `run.sh` and the README still reference `.venv`; not yet fixed.

```bash
# Web UI
hdubs.venv/bin/python -m uvicorn web:app --port 8077 --log-level warning
# CLI
hdubs.venv/bin/python generate_schedule.py            # next week
hdubs.venv/bin/python generate_schedule.py 2026-04-13 # specific Monday
```

## Architecture

Household/recurring/dinner data lives in **Supabase** (via [db.py](db.py),
`load_config()` merges DB + yaml). App-behavior settings (format, emoji map, group name,
excluded-event regexes) live in **[config.yaml](config.yaml)** `schedule_output:` block.
The primary scheduler's **work calendar id** is editable and lives in `config.yaml`
`calendars.work` (blank = none; falls back to `GCAL_WORK_ID` only if the key is absent) —
`_resolve_cal_ids()` in [generate_schedule.py](generate_schedule.py) resolves it. Personal
& family calendar ids still come from `.env`. The adults' **work schedules** (work
days/hours, commute, leaves/returns, au-pair daily hours) are editable in the Config page
and written back to Supabase via `db.fetch_adult_schedules()` / `db.save_adult_schedule()`.
Conflict/coverage detection happens **inside the Claude prompt**, not as structured Python.

### Web UI (added this session)
- [web.py](web.py) — FastAPI JSON API. Endpoints: `GET /`, `GET /api/events`,
  `POST /api/generate`, `POST /api/capture`, `POST /api/process-entities`,
  `GET|POST /api/config`, `GET /api/history`. `_extract_flags()` scrapes warning lines
  (‼️ ⚠️ 🐣 / "coverage gap", "overtime", "behind", "conflict") from generated output for
  badge chips.
- [templates/index.html](templates/index.html) — single-page app shell (vanilla JS + fetch),
  sage/clay light palette, responsive. Views: **Run** (format toggle, notes, generate,
  flag chips, copy), **Calendar** (7-day GCal grid with deep-links), **Configuration**
  (inline emoji-map/format/excluded editing, **editable work schedules + work calendar**,
  and **full add/edit/remove of people, pets & dinner defaults** — all written to
  Supabase/yaml), **History**. People/pets save via reconcile (omitted rows are deleted;
  FKs cascade or null). `db.fetch_household_editable()` / `save_household_people()` /
  `save_household_pets()` / `save_dinner_defaults()` back it.
- [config_io.py](config_io.py) — round-trip YAML editor (ruamel) so saving config keeps
  comments. `width=4096` (no re-wrap), `allow_unicode=True` (literal emoji).
- [runs.py](runs.py) — run-history persistence to Supabase `schedule_runs`. Degrades
  gracefully (empty/no-op) if table not migrated or creds absent.
- [gcal.py](gcal.py) — `fetch_events()` now also returns `id` + `html_link` (event
  deep-links).

### Supabase
Linked to project ref `deqemblldnslikaybbcv` (matches `SUPABASE_URL`).
[supabase/config.toml](supabase/config.toml) + `supabase/.temp/project-ref` wire `db push`.
**Run-history migration is NOT yet applied.** To enable the History view:
```bash
supabase login && supabase link --project-ref deqemblldnslikaybbcv && supabase db push
# OR paste supabase/migrations/0001_schedule_runs.sql into the dashboard SQL editor
```

## Status (as of 2026-06-24)

Full UI redesign built and smoke-tested (shell, config read/write round-trip, live GCal
events w/ links, flag extractor). Generate endpoint reuses the CLI pipeline unchanged
(not fired in tests, to avoid a paid Claude call). App confirmed working in browser.

## Next steps

1. **Formatting feedback (tomorrow's main task)** — user will review the generated-schedule
   output formatting and request tweaks. Output formats are `bullets` / `person` / `grid`,
   driven by `get_system_prompt()` in [generate_schedule.py](generate_schedule.py).
2. Apply the `schedule_runs` migration to turn on History (see Supabase section).
3. Recreate `.venv` cleanly and point `run.sh` + README at it (or standardize on
   `hdubs.venv`).
4. Known limitation: editing the excluded-events list via the Config textarea drops inline
   YAML comments (e.g. `# therapist`) — inherent to textarea editing.
5. Separate project (not this repo): job-hunt — role requirement breakdowns should be a
   function of the role, not the resume-match process; add 1–2 sentence summaries + the
   proposed tweaks. Captured from an Untitled scratch file; revisit in job-hunt.
