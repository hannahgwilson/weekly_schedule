"""Persistence for generated schedules ("run history").

Stores each generated schedule in the Supabase `schedule_runs` table so the UI
can re-open recent weeks without regenerating. Every function degrades
gracefully: if Supabase isn't configured or the table hasn't been migrated yet,
saves are silently dropped and lists return empty — the app still works.

Apply supabase/migrations/0001_schedule_runs.sql to enable persistence.
"""

from __future__ import annotations

import os

from db import get_client, _user_id

TABLE = "schedule_runs"


def save_run(*, week: str, fmt: str, schedule: str, flags: list[str], notes: str = "") -> dict | None:
    """Persist one generated schedule. Returns the inserted row, or None on failure."""
    try:
        sb = get_client()
        row = {
            "user_id": _user_id(),
            "week": week,
            "format": fmt,
            "schedule": schedule,
            "flags": flags,
            "notes": notes,
        }
        res = sb.table(TABLE).insert(row).execute()
        return res.data[0] if res.data else None
    except Exception as exc:  # table missing, no creds, network — never block a generate
        print(f"  Run history save skipped: {exc}")
        return None


def list_runs(limit: int = 10) -> list[dict]:
    """Return the most recent runs (newest first). Empty list on any failure."""
    try:
        sb = get_client()
        res = (
            sb.table(TABLE)
            .select("id, week, format, schedule, flags, notes, created_at")
            .eq("user_id", _user_id())
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        print(f"  Run history list skipped: {exc}")
        return []


def history_enabled() -> bool:
    """True if Supabase creds are present (table may still need migrating)."""
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
