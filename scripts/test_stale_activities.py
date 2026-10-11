#!/usr/bin/env python3
"""Regression tests: an activity removed from Supabase must stop appearing in schedules.

Wilson's swim and forest school were dropped and replaced with nature days, but they
kept turning up in generated schedules — because the activities were hardcoded in the
prompt (and `_build_children` only whitelisted those two types), so editing the database
changed nothing. These tests pin that shut.

The important test is `generation_has_no_removed_activities`, which runs real Claude
calls and checks the actual output. The offline tests are fast guards on the inputs.

Run from the repo root:
    python scripts/test_stale_activities.py           # offline tests + live DB config
    python scripts/test_stale_activities.py --live    # also generate real schedules
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weekly_schedule import db
from weekly_schedule.generate_schedule import (
    build_user_prompt,
    compute_week_context,
    generate_with_claude,
    get_system_prompt,
    load_config,
)

# Activities that were removed from the household. None of these words may appear in a
# prompt or a generated schedule. Kept as whole-word patterns so "swim" doesn't match
# inside an unrelated word.
REMOVED = {
    "swim": r"\bswim\w*\b",
    "forest school": r"\bforest[\s_]school\b",
    "pool on tuesday": r"\btue(?:sday)?\b[^.\n]{0,40}\bpool\b",
}

MONDAY = datetime.date(2026, 9, 28)


# ---------------------------------------------------------------------------
# Fixtures — hermetic, no Supabase. Shaped like load_config()'s output.
# ---------------------------------------------------------------------------


def _config(child_activities: dict) -> dict:
    """A minimal household config. `child_activities` is the children.<name>.activities dict."""
    return {
        "household": {
            "adults": {
                "hannah": {
                    "role": "Primary scheduler",
                    "work_days": ["monday", "tuesday", "wednesday", "thursday"],
                    "work_hours": "09:00-17:30",
                    "preferences": "Gym: Monday lift after work. Home all day Fridays (no office).",
                },
                "ryan": {
                    "role": "Partner",
                    "leaves_home": "07:15",
                    "returns_home": "17:00",
                    "preferences": (
                        "Teacher. Pool league Thursday straight from school "
                        "(does not come home first). Nightly dog walk at 22:00."
                    ),
                },
                "marthe": {
                    "role": "Au pair",
                    "weekly_hours": 45.0,
                    "schedule": {
                        "monday": "09:00-18:00",
                        "tuesday": "08:00-17:00",
                        "wednesday": "08:00-17:00",
                        "thursday": "08:00-18:30",
                        "friday": "balance",
                    },
                    "notes": "Schedule is stable week-to-week.",
                },
            },
            "children": {
                "wilson": {
                    "nap": "13:00-15:30",
                    "bedtime": "19:30",
                    "wake": "06:30-07:00",
                    "activities": child_activities,
                }
            },
            "pets": {
                "olive": {
                    "type": "dog",
                    "walks_per_day": 4,
                    "dog_walker": {"name": "Felicia", "days": ["tuesday", "wednesday", "thursday"]},
                }
            },
        },
        "recurring": {
            "cleaner": {"name": "Fabiola", "reference_date": "2026-04-08"},
            "coop_shifts": {
                "hannah": {"frequency_weeks": 6, "day": "saturday", "start_date": "2026-04-11"},
                "ryan": {"frequency_weeks": 6, "day": "sunday", "start_date": "2026-04-26"},
            },
        },
        "dinner": {"defaults": {"monday": "Ryan", "tuesday": "Hannah", "thursday": "Hannah (Chicken)"}},
    }


NATURE_DAYS = {
    "nature_days": {
        "label": "Nature days",
        "days": ["monday", "tuesday", "wednesday", "thursday"],
        "time": "09:00-12:30",
        "duration_min": 210,
        "location": None,
    }
}

# The pre-removal state, used as a negative control.
OLD_ACTIVITIES = {
    "swim": {
        "label": "Swim",
        "days": ["tuesday"],
        "time": "11:00-11:30",
        "duration_min": 30,
        "location": "904 Pacific St",
    },
    "forest_school": {
        "label": "Forest school",
        "days": ["thursday"],
        "time": "09:00-10:30",
        "duration_min": 90,
        "location": None,
    },
}


def _prompt(activities: dict) -> str:
    cfg = _config(activities)
    return build_user_prompt(cfg, compute_week_context(cfg, MONDAY), None, "")


def _hits(text: str) -> list[str]:
    """Which removed activities appear in `text`."""
    return [name for name, pattern in REMOVED.items() if re.search(pattern, text, re.IGNORECASE)]


# ---------------------------------------------------------------------------
# Offline tests
# ---------------------------------------------------------------------------


def test_build_children_passes_through_unknown_activity_type():
    """A type nobody hardcoded must still reach the config (the old whitelist dropped it)."""
    contacts = [{
        "id": "c1", "name": "Wilson", "tags": ["household_member"],
        "household_details": {"role": "child"},
    }]
    events = [{
        "contact_id": "c1", "activity_type": "nature_days", "title": "Nature days",
        "day_of_week": d, "start_time": "09:00:00", "end_time": "12:30:00", "location": None,
    } for d in ("monday", "tuesday", "wednesday", "thursday")]

    acts = db._build_children(contacts, events)["wilson"]["activities"]
    assert "nature_days" in acts, f"unknown activity type was dropped: {acts}"
    assert acts["nature_days"]["days"] == ["monday", "tuesday", "wednesday", "thursday"], acts
    assert acts["nature_days"]["time"] == "09:00-12:30", acts


def test_build_children_omits_deleted_activity():
    """With no swim row in the DB, nothing swim-shaped may survive into the config."""
    contacts = [{
        "id": "c1", "name": "Wilson", "tags": ["household_member"],
        "household_details": {"role": "child"},
    }]
    events = [{
        "contact_id": "c1", "activity_type": "nature_days", "title": "Nature days",
        "day_of_week": "monday", "start_time": "09:00:00", "end_time": "12:30:00", "location": None,
    }]

    child = db._build_children(contacts, events)["wilson"]
    hits = _hits(repr(child))
    assert not hits, f"deleted activities leaked into the child config: {hits}"


def test_prompt_renders_activity_from_data():
    """Nature days must appear on each of its days, with its real time."""
    prompt = _prompt(NATURE_DAYS)
    fixed = prompt[prompt.index("FIXED WEEKLY EVENTS"):]
    for day in ("Mon", "Tue", "Wed", "Thu"):
        line = next(ln for ln in fixed.splitlines() if ln.strip().startswith(f"- {day}:"))
        assert "nature days" in line.lower(), f"{day} missing nature days: {line}"
        assert "09:00-12:30" in line, f"{day} missing the time: {line}"
    fri = next(ln for ln in fixed.splitlines() if ln.strip().startswith("- Fri:"))
    assert "nature days" not in fri.lower(), f"nature days on a day it doesn't happen: {fri}"


def test_user_prompt_has_no_removed_activities():
    hits = _hits(_prompt(NATURE_DAYS))
    assert not hits, f"removed activities still in the user prompt: {hits}"


def test_system_prompt_has_no_removed_activities():
    """Covers all three output formats — the stale literals were in the format examples."""
    cfg = _config(NATURE_DAYS)
    for fmt in ("bullets", "person", "grid"):
        hits = _hits(get_system_prompt(fmt, cfg))
        assert not hits, f"removed activities still in the {fmt} system prompt: {hits}"


def test_negative_control_detects_activities_when_present():
    """Guards against a vacuously-passing suite.

    If swim and forest school are put back in the data, the checks above MUST fire.
    A green suite is only meaningful if this test proves the detection works.
    """
    hits = _hits(_prompt(OLD_ACTIVITIES))
    assert "swim" in hits, "detection is broken — swim in the data went unnoticed"
    assert "forest school" in hits, "detection is broken — forest school in the data went unnoticed"


def test_removed_activity_disappears_when_data_changes():
    """The end-to-end claim at prompt level: change the data, the prompt follows."""
    before = _prompt(OLD_ACTIVITIES)
    after = _prompt(NATURE_DAYS)
    assert _hits(before), "fixture problem: the 'before' prompt should contain the old activities"
    assert not _hits(after), f"prompt did not follow the data: {_hits(after)}"
    assert "nature days" in after.lower(), "replacement activity missing from the prompt"


def test_real_config_has_no_removed_activities():
    """The actual merged config from Supabase + yaml.

    This is the one that catches a stale config.yaml fallback as well as stale DB rows.
    Skipped if credentials aren't available.
    """
    try:
        cfg = load_config()
    except Exception as exc:
        print(f"    SKIP (no config/credentials: {exc})")
        return

    hits = _hits(repr(cfg.get("household", {})))
    assert not hits, f"removed activities present in the live merged config: {hits}"

    prompt = build_user_prompt(cfg, compute_week_context(cfg, MONDAY), None, "")
    hits = _hits(prompt)
    assert not hits, f"removed activities present in the live prompt: {hits}"


# ---------------------------------------------------------------------------
# Live test — real Claude calls against the real config
# ---------------------------------------------------------------------------


def test_generation_has_no_removed_activities():
    """Generate real schedules and check the output.

    The complaint was about generated schedules, not prompts, so this is the test that
    actually answers it. Several weeks and all three formats, because the leak was
    intermittent — the stale literals lived in format examples, so it showed up in
    some formats and not others.
    """
    cfg = load_config()
    cases = [
        ("bullets", MONDAY),
        ("bullets", MONDAY + datetime.timedelta(days=7)),
        ("person", MONDAY),
        ("grid", MONDAY),
    ]
    failures = []
    for fmt, monday in cases:
        ctx = compute_week_context(cfg, monday)
        out = generate_with_claude(get_system_prompt(fmt, cfg), build_user_prompt(cfg, ctx, None, ""))
        hits = _hits(out)
        label = f"{fmt} / week of {monday}"
        if hits:
            failures.append(f"{label}: {hits}")
            print(f"    ✗ {label} — found {hits}")
        else:
            print(f"    ✓ {label} — clean")
        if "nature" not in out.lower():
            failures.append(f"{label}: nature days missing from output entirely")
            print(f"    ✗ {label} — nature days missing")
    assert not failures, "generated schedules still contain removed activities:\n  " + "\n  ".join(failures)


OFFLINE = [
    test_build_children_passes_through_unknown_activity_type,
    test_build_children_omits_deleted_activity,
    test_prompt_renders_activity_from_data,
    test_user_prompt_has_no_removed_activities,
    test_system_prompt_has_no_removed_activities,
    test_negative_control_detects_activities_when_present,
    test_removed_activity_disappears_when_data_changes,
    test_real_config_has_no_removed_activities,
]

LIVE = [test_generation_has_no_removed_activities]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="also generate real schedules via the Claude API (costs tokens)")
    args = ap.parse_args()

    tests = OFFLINE + (LIVE if args.live else [])
    failed = 0
    for t in tests:
        print(f"  {t.__name__} ...")
        try:
            t()
            print("    PASS")
        except AssertionError as exc:
            failed += 1
            print(f"    FAIL: {exc}")
        except Exception as exc:
            failed += 1
            print(f"    ERROR: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if not args.live:
        print("(offline only — rerun with --live to check real generated output)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
