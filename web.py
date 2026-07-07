"""FastAPI UI for the weekly schedule generator.

Single-page app shell (templates/index.html) backed by a small JSON API:

  GET  /                     -> the app shell
  GET  /api/events?week=     -> calendar grid for the week (with GCal deep-links)
  POST /api/generate         -> run the pipeline; returns schedule + flags; saves history
  POST /api/capture          -> capture notes to Open Brain
  POST /api/process-entities -> drain the entity-extraction queue
  GET  /api/config           -> editable settings + work calendar + household summary
  POST /api/config           -> patch schedule_output settings + work calendar id
  GET  /api/work-schedules   -> adults' editable work schedules (from Supabase)
  POST /api/work-schedules   -> save adults' work schedules + au pair daily hours
  GET  /api/household        -> editable people / pets / dinner defaults
  POST /api/household/people -> reconcile household members (add/edit/remove)
  POST /api/household/pets   -> reconcile pets (add/edit/remove)
  POST /api/household/dinner -> set per-day dinner defaults (cook + dish note)
  GET  /api/history          -> recent generated schedules

Run with:
    uvicorn web:app --reload
"""

from __future__ import annotations

import datetime
import re
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from generate_schedule import (
    analyze_work_calendar,
    build_user_prompt,
    compute_week_context,
    generate_with_claude,
    get_system_prompt,
    load_config,
    next_monday,
    parse_event_time,
    pull_gcal_events,
    suggest_gym_days,
)
from entity_extraction import drain_entity_queue
from open_brain import capture_thoughts, fetch_open_brain_notes
import config_io
import db
import runs

app = FastAPI(title="Weekly Schedule")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Markers that signal something the family needs to act on / be aware of.
FLAG_MARKERS = ("‼", "⚠", "\U0001f423")  # ‼️  ⚠️  🐣
FLAG_KEYWORDS = ("coverage gap", "overtime", "behind", "conflict", "double-book", "no coverage")


def _split_blocks(text: str) -> list[str]:
    """Split a notes textarea into blank-line-separated blocks, trimmed."""
    return [b.strip() for b in text.strip().split("\n\n") if b.strip()]


def _parse_week(week: str) -> datetime.date:
    """Parse a YYYY-MM-DD week string, defaulting to next Monday."""
    if not week:
        return next_monday()
    return datetime.date.fromisoformat(week)


def _extract_flags(schedule: str) -> list[str]:
    """Pull action/warning lines out of a generated schedule for badge chips.

    Heuristic: a line counts as a flag if it carries a warning emoji or one of a
    few keywords. Deduped, stripped of bullet glyphs, capped at 8.
    """
    flags: list[str] = []
    seen = set()
    for raw in schedule.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        hit = any(m in line for m in FLAG_MARKERS) or any(k in low for k in FLAG_KEYWORDS)
        if not hit:
            continue
        clean = line.lstrip("-*•‣◦ ").strip()
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        flags.append(clean)
        if len(flags) >= 8:
            break
    return flags


def _calendar_payload(week_monday: datetime.date) -> dict:
    """Build a JSON-friendly week grid from GCal, including deep-links."""
    config = load_config()
    by_day = pull_gcal_events(week_monday, config) or {d: [] for d in DAYS}

    days = []
    for i, name in enumerate(DAYS):
        date = week_monday + datetime.timedelta(days=i)
        items = []
        for e in by_day.get(name, []):
            start_t = parse_event_time(e.get("start", "")) if not e.get("all_day") else None
            end_t = parse_event_time(e.get("end", "")) if not e.get("all_day") else None
            items.append({
                "summary": e.get("summary", "(no title)"),
                "all_day": e.get("all_day", False),
                "start": start_t.strftime("%-I:%M%p").lower() if start_t else None,
                "end": end_t.strftime("%-I:%M%p").lower() if end_t else None,
                "calendar": e.get("calendar_label", ""),
                "link": e.get("html_link"),
            })
        # All-day first, then timed in chronological order (timed already sorted).
        items.sort(key=lambda x: (not x["all_day"], x["start"] or ""))
        days.append({
            "name": name,
            "label": name.capitalize(),
            "date": date.isoformat(),
            "display": date.strftime("%b %-d"),
            "events": items,
        })

    return {
        "week": week_monday.isoformat(),
        "week_end": (week_monday + datetime.timedelta(days=6)).isoformat(),
        "days": days,
        "configured": pull_gcal_events(week_monday, config) is not None,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "week": next_monday().isoformat(),
            "formats": list(config_io.VALID_FORMATS),
            "history_enabled": runs.history_enabled(),
        },
    )


@app.get("/api/events")
def api_events(week: str = "") -> JSONResponse:
    try:
        monday = _parse_week(week)
    except ValueError:
        return JSONResponse({"error": f"Invalid date: {week!r}. Use YYYY-MM-DD."}, status_code=400)
    try:
        return JSONResponse(_calendar_payload(monday))
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not load calendar: {exc}"}, status_code=500)


@app.post("/api/generate")
async def api_generate(request: Request) -> JSONResponse:
    body = await request.json()
    week = (body.get("week") or "").strip()
    fmt = (body.get("format") or "").strip() or None
    notes = (body.get("notes") or "").strip()

    try:
        monday = _parse_week(week)
    except ValueError:
        return JSONResponse({"error": f"Invalid date: {week!r}. Use YYYY-MM-DD."}, status_code=400)

    try:
        config = load_config()
        context = compute_week_context(config, monday)

        gcal_events = pull_gcal_events(monday, config)
        if gcal_events:
            work_analysis = analyze_work_calendar(gcal_events)
            context["work_analysis"] = work_analysis
            context["gym_suggestions"] = suggest_gym_days(work_analysis)

        try:
            # Same asyncio.run()-in-a-running-loop constraint as capture.
            ob_notes = await run_in_threadpool(fetch_open_brain_notes, monday)
        except Exception as exc:
            print(f"Open Brain fetch failed: {exc}")
            ob_notes = []

        output_format = fmt or config.get("schedule_output", {}).get("format", "bullets")
        system_prompt = get_system_prompt(output_format, config)
        user_prompt = build_user_prompt(config, context, gcal_events, notes, ob_notes)
        schedule = generate_with_claude(system_prompt, user_prompt)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Generation failed: {exc}"}, status_code=500)

    flags = _extract_flags(schedule)
    runs.save_run(week=monday.isoformat(), fmt=output_format, schedule=schedule, flags=flags, notes=notes)

    return JSONResponse({
        "week": monday.isoformat(),
        "format": output_format,
        "schedule": schedule,
        "flags": flags,
    })


@app.post("/api/capture")
async def api_capture(request: Request) -> JSONResponse:
    body = await request.json()
    blocks = _split_blocks(body.get("notes", ""))
    if not blocks:
        return JSONResponse({"error": "No notes to capture — type something first."}, status_code=400)
    try:
        # capture_thoughts uses asyncio.run() internally, which is illegal from
        # this running event loop — run it in a worker thread (no loop there).
        confirmations = await run_in_threadpool(capture_thoughts, blocks)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Capture failed: {exc}"}, status_code=500)
    return JSONResponse({"captured": confirmations})


@app.post("/api/process-entities")
def api_process_entities() -> JSONResponse:
    try:
        result = drain_entity_queue()
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Entity processing failed: {exc}"}, status_code=500)
    return JSONResponse({"result": result})


def _household_summary(config: dict) -> dict:
    """A compact, read-only view of who/what is in the household config."""
    hh = config.get("household", {}) or {}
    adults = {k: v.get("role", "") for k, v in (hh.get("adults", {}) or {}).items()}
    children = {k: v.get("age", "") for k, v in (hh.get("children", {}) or {}).items()}
    pets = {k: v.get("type", "") for k, v in (hh.get("pets", {}) or {}).items()}
    dinner = config.get("dinner", {}) or {}
    return {
        "adults": adults,
        "children": children,
        "pets": pets,
        "dinner_defaults": dinner.get("defaults", {}) or {},
        "dinner_negotiable": dinner.get("negotiable", []) or [],
    }


@app.get("/api/config")
def api_config_get() -> JSONResponse:
    try:
        settings = config_io.read_settings()
        calendars = config_io.read_calendars()
        household = _household_summary(load_config())
        return JSONResponse({"settings": settings, "calendars": calendars, "household": household})
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not load config: {exc}"}, status_code=500)


@app.post("/api/config")
async def api_config_post(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        excluded = body.get("excluded_events")
        if isinstance(excluded, str):
            excluded = [line.strip() for line in excluded.splitlines() if line.strip()]
        settings = config_io.update_settings(
            format=body.get("format"),
            group_name=body.get("group_name"),
            emoji_map=body.get("emoji_map"),
            excluded_events=excluded,
        )
        calendars = None
        if "work_calendar" in body:
            calendars = config_io.update_work_calendar(body.get("work_calendar") or "")
        return JSONResponse({"settings": settings, "calendars": calendars or config_io.read_calendars()})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not save config: {exc}"}, status_code=500)


@app.get("/api/work-schedules")
def api_work_get() -> JSONResponse:
    try:
        return JSONResponse({"adults": db.fetch_adult_schedules()})
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not load work schedules: {exc}"}, status_code=500)


@app.post("/api/work-schedules")
async def api_work_post(request: Request) -> JSONResponse:
    body = await request.json()
    adults = body.get("adults")
    if not isinstance(adults, list) or not adults:
        return JSONResponse({"error": "No work schedules to save."}, status_code=400)
    try:
        for adult in adults:
            db.save_adult_schedule(adult)
        return JSONResponse({"adults": db.fetch_adult_schedules()})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not save work schedules: {exc}"}, status_code=500)


@app.get("/api/household")
def api_household_get() -> JSONResponse:
    try:
        return JSONResponse(db.fetch_household_editable())
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not load household: {exc}"}, status_code=500)


@app.post("/api/household/people")
async def api_household_people(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        db.save_household_people(body.get("people") or [])
        return JSONResponse(db.fetch_household_editable())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not save people: {exc}"}, status_code=500)


@app.post("/api/household/pets")
async def api_household_pets(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        db.save_household_pets(body.get("pets") or [])
        return JSONResponse(db.fetch_household_editable())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not save pets: {exc}"}, status_code=500)


@app.post("/api/household/dinner")
async def api_household_dinner(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        db.save_dinner_defaults(body.get("dinner") or [])
        return JSONResponse(db.fetch_household_editable())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": f"Could not save dinner defaults: {exc}"}, status_code=500)


@app.get("/api/history")
def api_history(limit: int = 10) -> JSONResponse:
    return JSONResponse({"runs": runs.list_runs(limit=limit)})
