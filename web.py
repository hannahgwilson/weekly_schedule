"""FastAPI UI for the weekly schedule generator.

Two-step flow:
  1. Type notes -> POST /capture -> each blank-line-separated block becomes a thought
     in Open Brain via the `capture_thought` MCP tool.
  2. Click generate -> POST /generate -> runs the same pipeline as
     `generate_schedule.py` (GCal + Open Brain + Claude) and renders the schedule.

Run with:
    uvicorn web:app --reload
"""

from __future__ import annotations

import datetime
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    pull_gcal_events,
    suggest_gym_days,
)
from entity_extraction import drain_entity_queue
from open_brain import capture_thoughts, fetch_open_brain_notes

app = FastAPI(title="Weekly Schedule")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _split_blocks(text: str) -> list[str]:
    """Split textarea into blank-line-separated blocks, trimmed."""
    return [b.strip() for b in text.strip().split("\n\n") if b.strip()]


def _render(
    request: Request,
    *,
    captured: list[str] | None = None,
    schedule: str | None = None,
    error: str | None = None,
    week: str | None = None,
    notes: str = "",
    entity_result: dict | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "captured": captured,
            "schedule": schedule,
            "error": error,
            "week": week or next_monday().isoformat(),
            "notes": notes,
            "entity_result": entity_result,
        },
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _render(request)


@app.post("/capture", response_class=HTMLResponse)
def capture(request: Request, notes: str = Form("")) -> HTMLResponse:
    blocks = _split_blocks(notes)
    if not blocks:
        return _render(request, error="No notes to capture — type something first.", notes=notes)

    try:
        confirmations = capture_thoughts(blocks)
    except Exception as exc:
        return _render(request, error=f"Capture failed: {exc}", notes=notes)

    return _render(request, captured=confirmations)


@app.post("/generate", response_class=HTMLResponse)
def generate(request: Request, week: str = Form("")) -> HTMLResponse:
    try:
        target_monday = datetime.date.fromisoformat(week) if week else next_monday()
    except ValueError:
        return _render(request, error=f"Invalid date: {week!r}. Use YYYY-MM-DD.", week=week)

    try:
        config = load_config()
        context = compute_week_context(config, target_monday)

        gcal_events = pull_gcal_events(target_monday, config)
        if gcal_events:
            work_analysis = analyze_work_calendar(gcal_events)
            context["work_analysis"] = work_analysis
            context["gym_suggestions"] = suggest_gym_days(work_analysis)

        try:
            ob_notes = fetch_open_brain_notes(target_monday)
        except Exception as exc:
            print(f"Open Brain fetch failed: {exc}")
            ob_notes = []

        output_format = config.get("schedule_output", {}).get("format", "bullets")
        system_prompt = get_system_prompt(output_format, config)
        user_prompt = build_user_prompt(config, context, gcal_events, "", ob_notes)
        schedule = generate_with_claude(system_prompt, user_prompt)
    except Exception as exc:
        traceback.print_exc()
        return _render(request, error=f"Generation failed: {exc}", week=week)

    return _render(request, schedule=schedule, week=target_monday.isoformat())


@app.post("/process-entities", response_class=HTMLResponse)
def process_entities(request: Request) -> HTMLResponse:
    try:
        result = drain_entity_queue()
    except Exception as exc:
        traceback.print_exc()
        return _render(request, error=f"Entity processing failed: {exc}")
    return _render(request, entity_result=result)
