#!/usr/bin/env python3
"""Weekly schedule generator for a household.

Pulls Google Calendar events, applies fixed household rules from config.yaml,
and uses Claude to generate a WhatsApp-ready weekly schedule.

Usage:
    python generate_schedule.py              # generate for next week (auto-detects Monday)
    python generate_schedule.py 2026-04-13   # generate for a specific week (pass any Monday)
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path
from typing import Optional

import anthropic
import pyperclip
import yaml
from dotenv import load_dotenv

from gcal import fetch_week_events, get_credentials
from open_brain import display_open_brain_notes, fetch_open_brain_notes, format_open_brain_for_prompt

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Events to filter out of GCal results
# Customize these patterns for your household — e.g., therapist names, hold blocks, etc.
EXCLUDED_EVENT_PATTERNS = [
    r"(?i)birthday",
    r"(?i)therapist",  # filter out therapy appointments
    r"(?i)weekly\s*meeting",  # handled as family dinner feature
    r"(?i)ask before scheduling",  # commute/family hold blocks on work calendar
]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def should_exclude_event(summary: str, config: dict | None = None) -> bool:
    """Check if a GCal event should be filtered out.

    Uses built-in patterns plus any additional patterns from config.yaml
    under schedule_output.excluded_events.
    """
    patterns = list(EXCLUDED_EVENT_PATTERNS)
    if config:
        extra = config.get("schedule_output", {}).get("excluded_events", [])
        patterns.extend(extra)
    for pattern in patterns:
        if re.search(pattern, summary):
            return True
    return False


# ---------------------------------------------------------------------------
# Derived weekly facts
# ---------------------------------------------------------------------------


def next_monday(from_date: datetime.date | None = None) -> datetime.date:
    """Return the Monday of the upcoming week (or the current Monday if today is Mon-Wed)."""
    today = from_date or datetime.date.today()
    days_ahead = 0 - today.weekday()  # 0 = Monday
    if days_ahead <= 0:
        days_ahead += 7
    # If it's Sun-Wed and the user likely means "this coming week"
    if today.weekday() == 6:  # Sunday — generate for tomorrow
        return today + datetime.timedelta(days=1)
    return today + datetime.timedelta(days=days_ahead)


def is_cleaner_week(week_monday: datetime.date, reference_date_str: str) -> bool:
    """Determine if the cleaner comes this Wednesday."""
    ref = datetime.date.fromisoformat(reference_date_str)
    # Find the Wednesday of each week
    week_wed = week_monday + datetime.timedelta(days=2)
    ref_wed = ref + datetime.timedelta(days=(2 - ref.weekday()) % 7)
    delta_weeks = abs((week_wed - ref_wed).days) // 7
    return delta_weeks % 2 == 0


def is_coop_week(week_date: datetime.date, start_date_str: str, frequency_weeks: int) -> bool:
    """Check if a coop shift falls on the given date."""
    start = datetime.date.fromisoformat(start_date_str)
    delta_days = (week_date - start).days
    if delta_days < 0:
        return False
    return delta_days % (frequency_weeks * 7) == 0


def compute_caregiver_hours(config: dict) -> dict:
    """Calculate the au pair's daily hours from their schedule config.

    Returns dict with daily hours and friday balance.
    The au pair's base schedule must total their configured weekly hours.
    Any hours beyond their scheduled end time are 'babysitting' (overtime).
    """
    # Find the au pair in the config (the adult with role containing "au pair")
    au_pair_name = None
    for name, adult in config["household"]["adults"].items():
        if "au pair" in adult.get("role", "").lower():
            au_pair_name = name
            break
    if not au_pair_name:
        return {"daily": {}, "mon_thu_total": 0, "friday_hours": 0, "weekly_total": 0}

    au_pair = config["household"]["adults"][au_pair_name]
    schedule = au_pair["schedule"]
    weekly_target = au_pair["weekly_hours"]

    daily_hours = {}
    for day, hours in schedule.items():
        if day == "friday" or hours == "balance":
            continue
        start_str, end_str = hours.split("-")
        start_h, start_m = int(start_str.split(":")[0]), int(start_str.split(":")[1])
        end_h, end_m = int(end_str.split(":")[0]), int(end_str.split(":")[1])
        daily_hours[day] = (end_h + end_m / 60) - (start_h + start_m / 60)

    mon_thu_total = sum(daily_hours.values())
    friday_hours = weekly_target - mon_thu_total

    daily_hours["friday"] = friday_hours
    return {
        "daily": daily_hours,
        "mon_thu_total": mon_thu_total,
        "friday_hours": friday_hours,
        "weekly_total": weekly_target,
    }


def compute_week_context(config: dict, week_monday: datetime.date) -> dict:
    """Compute all derived facts for the target week."""
    recurring = config["recurring"]

    week_sat = week_monday + datetime.timedelta(days=5)
    week_sun = week_monday + datetime.timedelta(days=6)

    # Get adult names from config
    adults = list(config["household"]["adults"].keys())
    primary = adults[0] if adults else "alex"
    partner = adults[1] if len(adults) > 1 else "jordan"

    primary_coop = is_coop_week(
        week_sat,
        recurring["coop_shifts"][primary]["start_date"],
        recurring["coop_shifts"][primary]["frequency_weeks"],
    )
    partner_coop = is_coop_week(
        week_sun,
        recurring["coop_shifts"][partner]["start_date"],
        recurring["coop_shifts"][partner]["frequency_weeks"],
    )
    cleaner = is_cleaner_week(week_monday, recurring["cleaner"]["reference_date"])

    caregiver_hours = compute_caregiver_hours(config)

    return {
        "week_monday": week_monday.isoformat(),
        "week_sunday": week_sun.isoformat(),
        "cleaner_this_week": cleaner,
        f"{primary}_coop_saturday": primary_coop,
        f"{partner}_coop_sunday": partner_coop,
        "caregiver_hours": caregiver_hours,
        f"{partner}_coop_behind": True,  # per spec, remind until resolved
        # Store names for prompt building
        "primary_name": primary,
        "partner_name": partner,
    }


# ---------------------------------------------------------------------------
# GCal
# ---------------------------------------------------------------------------


def pull_gcal_events(week_monday: datetime.date, config: dict | None = None) -> dict[str, list[dict]] | None:
    """Attempt to fetch GCal events. Returns None if not configured."""
    cal_ids = {
        "personal": os.getenv("GCAL_PERSONAL_ID"),
        "family": os.getenv("GCAL_FAMILY_ID"),
        "work": os.getenv("GCAL_WORK_ID"),
    }
    if not any(cal_ids.values()):
        return None

    try:
        events_by_day = fetch_week_events(cal_ids, week_monday)
    except Exception as exc:
        print(f"\n  Warning: GCal fetch failed: {exc}")
        print("  Continuing without calendar events.\n")
        return None

    # Filter out excluded events
    for day in events_by_day:
        events_by_day[day] = [
            e for e in events_by_day[day]
            if not should_exclude_event(e.get("summary", ""), config)
        ]

    return events_by_day


def parse_event_time(raw: str) -> datetime.time | None:
    """Extract time from a GCal datetime string."""
    if "T" in raw:
        time_part = raw.split("T")[1][:5]
        h, m = time_part.split(":")
        return datetime.time(int(h), int(m))
    return None


def parse_event_end_time(event: dict) -> datetime.time | None:
    """Extract end time from a GCal event."""
    return parse_event_time(event.get("end", ""))


def analyze_work_calendar(gcal_events: dict[str, list[dict]]) -> dict:
    """Analyze the primary scheduler's work calendar to compute late meetings, ETA home, and gym windows.

    Returns a dict keyed by day name with scheduling-relevant info.
    A "late start" day (first meeting at 10am+) is a gym-before-work opportunity.
    """
    work_days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    commute_buffer = 45  # minutes from last meeting to home
    gym_after_work_total = 100  # 20min office->gym + 60min gym + 20min gym->home
    normal_first_meeting = datetime.time(10, 0)  # if first meeting is at or after 10am, can gym before work

    analysis = {}
    for day in work_days:
        events = gcal_events.get(day, [])
        work_events = [e for e in events if e.get("calendar_label") == "work" and not e.get("all_day")]

        if not work_events:
            analysis[day] = {
                "first_meeting_start": None,
                "last_meeting_end": None,
                "eta_home": None,
                "eta_home_via_gym": None,
                "has_late_meetings": False,
                "late_start": True,  # no meetings = totally flexible
                "gym_before_work": True,
                "gym_after_work": True,
            }
            continue

        # Find first start, last end
        last_end = None
        earliest_start = None
        has_late = False

        for e in work_events:
            start_time = parse_event_time(e.get("start", ""))
            end_time = parse_event_end_time(e)

            if start_time:
                if earliest_start is None or start_time < earliest_start:
                    earliest_start = start_time

            if end_time:
                if last_end is None or end_time > last_end:
                    last_end = end_time
                if end_time > datetime.time(17, 0):
                    has_late = True

        # Late start = first meeting at 10am or later -> gym before work is possible
        late_start = earliest_start is not None and earliest_start >= normal_first_meeting

        # Compute ETAs — primary scheduler does not leave office before 5:30pm unless told to hustle
        eta_home = None
        eta_home_via_gym = None
        gym_after_work = True
        earliest_departure = datetime.time(17, 30)

        if last_end:
            # Leave at whichever is later: last meeting end or 5:30pm
            effective_departure = max(last_end, earliest_departure)
            depart_dt = datetime.datetime.combine(datetime.date.today(), effective_departure)
            eta_home_dt = depart_dt + datetime.timedelta(minutes=commute_buffer)
            eta_home = eta_home_dt.time()

            eta_gym_dt = depart_dt + datetime.timedelta(minutes=gym_after_work_total)
            eta_home_via_gym = eta_gym_dt.time()

            # Gym after work feasible if home by 8:30pm
            gym_after_work = eta_home_via_gym <= datetime.time(20, 30)

        analysis[day] = {
            "first_meeting_start": earliest_start,
            "last_meeting_end": last_end,
            "eta_home": eta_home,
            "eta_home_via_gym": eta_home_via_gym,
            "has_late_meetings": has_late,
            "late_start": late_start,
            "gym_before_work": late_start,  # can gym before work if commuting late
            "gym_after_work": gym_after_work,
        }

    return analysis


def suggest_gym_days(work_analysis: dict, fixed_gym_day: str = "monday") -> list[dict]:
    """Suggest gym days based on work calendar availability.

    Gym goals: lift fixed_gym_day after work (fixed), run 1-2x midweek, lift + gym both weekend days.
    Returns list of dicts with day, timing ('before_work' or 'after_work'), and ETA info.
    Prefers gym-before-work on late-start days (fewer evening conflicts).
    """
    candidates = []

    # Check Tue-Thu for midweek gym
    for day in ["tuesday", "wednesday", "thursday"]:
        info = work_analysis.get(day, {})

        if info.get("gym_before_work"):
            first = info.get("first_meeting_start")
            candidates.append({
                "day": day,
                "timing": "before_work",
                "first_meeting": first.strftime("%I:%M%p").lstrip("0").lower() if first else None,
                "note": f"late start (first meeting {first.strftime('%I:%M%p').lstrip('0').lower()}), gym before work" if first else "no meetings, gym before work",
                "priority": 0,  # prefer before-work
            })
        elif info.get("gym_after_work"):
            eta = info.get("eta_home_via_gym")
            candidates.append({
                "day": day,
                "timing": "after_work",
                "eta_home": eta.strftime("%I:%M%p").lstrip("0").lower() if eta else None,
                "note": f"gym after work, home ~{eta.strftime('%I:%M%p').lstrip('0').lower()}" if eta else "gym after work",
                "priority": 1,
            })

    # Check Friday morning — primary scheduler is home, can gym if no early meetings
    # If au pair starts early on Friday, primary can go even earlier
    fri_info = work_analysis.get("friday", {})
    fri_first = fri_info.get("first_meeting_start")
    fri_feasible = fri_first is None or fri_first >= datetime.time(10, 0)
    if fri_feasible:
        note = "Friday morning gym (home, no early meetings)"
        if fri_first:
            note = f"Friday morning gym (first meeting {fri_first.strftime('%I:%M%p').lstrip('0').lower()}, plenty of time)"
        candidates.append({
            "day": "friday",
            "timing": "morning",
            "first_meeting": fri_first.strftime("%I:%M%p").lstrip("0").lower() if fri_first else None,
            "note": note,
            "priority": 0,  # morning gym is great
            "marthe_early_helpful": True,  # flag that au pair starting early would help
        })

    # Sort: prefer before-work/morning, then after-work
    candidates.sort(key=lambda x: x["priority"])
    # Suggest 1 additional midweek day (fixed_gym_day is already fixed)
    return candidates[:1]


def display_gcal_events(gcal_events: dict[str, list[dict]], work_analysis: dict | None = None) -> None:
    """Print non-work events and a work calendar summary for the user to review."""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    # Show non-work events (personal + family)
    any_events = False
    for day in day_order:
        events = gcal_events.get(day, [])
        non_work = [e for e in events if e.get("calendar_label") != "work"]
        if non_work:
            if not any_events:
                print("\n  Personal/family events:")
                any_events = True
            for e in non_work:
                time_str = ""
                if not e["all_day"]:
                    raw = e["start"]
                    if "T" in raw:
                        time_str = raw.split("T")[1][:5]
                    time_str = f" {time_str}" if time_str else ""
                print(f"    {day.title()[:3]}{time_str} — {e['summary']}")
    if not any_events:
        print("\n  No personal/family events this week.")

    # Show work calendar summary
    if work_analysis:
        print("\n  Work calendar summary:")
        for day in ["monday", "tuesday", "wednesday", "thursday"]:
            info = work_analysis.get(day, {})
            if info.get("last_meeting_end"):
                end_str = info["last_meeting_end"].strftime("%I:%M%p").lstrip("0").lower()
                eta_str = info["eta_home"].strftime("%I:%M%p").lstrip("0").lower()
                late = " ⚠️ late" if info["has_late_meetings"] else ""
                if info.get("late_start") and info.get("first_meeting_start"):
                    first_str = info["first_meeting_start"].strftime("%I:%M%p").lstrip("0").lower()
                    gym_note = f" | late start (first mtg {first_str}) → gym before work ✓"
                elif info.get("gym_after_work"):
                    gym_eta = info["eta_home_via_gym"].strftime("%I:%M%p").lstrip("0").lower() if info.get("eta_home_via_gym") else "?"
                    gym_note = f" | gym after work → home ~{gym_eta} ✓"
                else:
                    gym_note = " | gym too late ✗"
                print(f"    {day.title()[:3]}: last mtg ends {end_str}, home ~{eta_str}{late}{gym_note}")
            else:
                print(f"    {day.title()[:3]}: no work meetings — flexible")


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_BASE = """\
You are a household schedule assistant. Your job is to generate a weekly schedule
that gets sent to a WhatsApp group chat.

NAMING CONVENTIONS:
- {primary} = {pa}, {partner} = {ra}, {aupair} = {ma}, {primary} & {partner} together = {pa}+{ra}
- Use these abbreviations consistently throughout the schedule.

HOUSEHOLD DAILY RHYTHM:
- {child} wakes 6:30-7am. {pa} walks {pet} ~6:30am, back before {ra} leaves.
- {ra} leaves for work at 7:15am. {pa} is with {child} from ~7am until {ma} arrives.
- {ma} arrives at their scheduled start time and takes over childcare.
- {pa} commutes to office Mon-Thu (leaves ~8:15-8:30, 25min commute). {pa} does NOT go to the office on Fridays.
- {ra} home ~5pm. {ra} goes to pool after 5:30pm (does not come home first on Thursdays).
- {pa} does NOT leave the office before 5:30pm unless specifically told to hustle. Their ETA is provided per-day.
- {child} bedtime 7:30pm. {ra} does {pet}'s 10pm walk every night.

{pa}'S WORK CALENDAR & COMMUTE:
- {pa}'s work schedule is provided per-day with their last meeting end time and computed ETA home.
- {pa} leaves office at 5:30pm or when their last meeting ends, whichever is LATER.
- If {pa} has late meetings (past 5:30pm), note it: "{pa} late meetings, home ~[time]"
- ETA home = departure + 45min buffer (wrapping up + 25min commute).
- If {pa} goes to gym after work: add 20min office->gym + 60min workout + 20min gym->home instead of direct commute.
- When gym is scheduled, note the gym ETA: "{pa} gym after work, home ~[time]"
- Use the suggested gym days from the input — these are the days where gym still gets {pa} home at a reasonable hour.
- GYM BEFORE WORK: On late-start days (first work meeting at 10am+), {pa} can gym before commuting. They go to a gym near home, work out 1hr, then commute to office. Note as "{pa} gym before work, in office by ~[time]".
- FRIDAY GYM: {pa} is home Fridays. If they don't have early meetings (before 10am), they can gym Friday morning. If {ma} starts early on Friday, {pa} can go earlier. Note as "{pa} gym Friday morning".
- ONE WORKOUT PER DAY: {pa} does NOT work out twice in the same day. If gym-before-work is scheduled, do NOT also schedule gym-after-work that day. Pick whichever timing works best for that day's schedule.

CRITICAL RULES:
1. {child} must have an adult ({pa}, {ra}, or {ma}) responsible for them at every moment (6:30am-7:30pm).
2. {pet} gets 4 walks/day. {ra} always does 10pm. Only flag walks if something unusual needs to be arranged.
3. Every dinner Mon-Sun must have a named cook ({pa} or {ra}). See DINNER RULES.
4. {pa} commutes to office Mon-Thu only. If anything requires them home before 6:30pm on a work day, flag it. {pa} is HOME on Fridays.
5. {ma}'s BASE schedule is 45hrs/week (Mon 9-6 = 9hrs, Tue 8-5 = 9hrs, Wed 8-5 = 9hrs, Thu 8-6:30 = 10.5hrs, Fri = 7.5hrs to reach 45). Friday default is 8:00-3:30 (7.5hrs). Do NOT miscalculate — 8:00 to 1:30 is only 5.5hrs, NOT 7.5hrs. Any hours BEYOND their scheduled end time are "babysitting" — flag with 🐣 and explicit ask to @{aupair}.
6. No coverage gaps — especially around {ma}'s start/end times and {pa}/{ra} transitions. See HANDOFF VALIDATION below.
7. {ra}'s pool starts after 5:30pm. On Thursdays they go straight from school (do NOT come home first). On Tuesdays they come home first and CANNOT leave for pool until {pa} is home to take over {child}. State the specific time {ra} can leave based on {pa}'s ETA (e.g., "{ra} pool 🎱 ~6:15 after {pa} home"). {ra} uses this to coordinate with their pool team.

HANDOFF VALIDATION — you MUST check this for every weekday:
For each day Mon-Thu, compare {ma}'s END TIME with {pa}'s ETA HOME:
  - If {pa} arrives home AFTER {ma} leaves, {ra} must stay home with {child} until {pa} arrives. {ra} CANNOT leave for pool/squash/events until {pa} is home.
  - If {ra} has pool on a night where {pa} is not home yet when {ma} leaves, note that {ra} leaves AFTER {pa} arrives (e.g., "{ra} pool after {pa} home ~6:15").
  - If {ra} goes straight from school (Thu pool), they are NOT home at all — so if {ma} leaves before {pa} arrives, that is a COVERAGE GAP. Flag it as ‼️ and suggest either: (a) {ma} stays late (babysitting 🐣), or (b) {pa} hustles home.
  - Example: {ma} ends at 5pm, {pa} ETA 6:15pm, {ra} at pool -> GAP 5-6:15pm. {ra} must wait for {pa}, OR {ma} stays until {pa} arrives (overtime 🐣).
  - Example: Thu {ma} ends 6:30pm, {pa} ETA 6:45pm, {ra} at pool from school -> 15min gap. Flag it.
Do NOT just list everyone's schedule independently — cross-check the handoffs.

SCHEDULING CONFLICTS — HARD RULE:
Each person can only be in ONE place at a time. Before placing any event, check if that person already has something scheduled at that time. If there is a conflict, FLAG IT and suggest rescheduling the movable event. Examples:
  - {ra} has pool on Thursday -> {ra} CANNOT also be at a dinner/check-in on Thursday evening.
  - {pa} has a work happy hour Wednesday -> {pa} CANNOT also do family dinner Wednesday.
  - If a calendar event conflicts with a fixed commitment, note the conflict and suggest moving the calendar event to another day.

BABYSITTING ARRIVAL RULE:
If {ma} is babysitting for an event where {pa}+{ra} are both leaving, {ma} must arrive 45 MINUTES before the event start time. The 45 minutes already includes travel time for most local events. Example: event at 12:30 -> {ma} arrives by 11:45. If the calendar event has an address that is clearly more than 45 minutes away, add extra buffer on top.

DINNER RULES:
- Monday: {ra} (fixed)
- Tuesday: {pa} — chicken (fixed)
- Wed-Sun: Assign {pa} or {ra} based on who is home and available.
  - If one parent has an evening event, assign the OTHER parent.
  - If BOTH are going out (date night, dinner with friends), do NOT assign a cook — note the plan. That IS their dinner.
  - Only mark as "TBD" if there truly isn't enough info.

FAMILY DINNER:
- One night per week, everyone ({pa}, {ra}, {ma}) eats together at home. This is also when {pa}+{ma} do their weekly check-in.
- ELIGIBLE DAYS: Monday, Tuesday, Wednesday, Thursday, or Sunday ONLY.
- NEVER PLACE ON FRIDAY. NEVER PLACE ON SATURDAY. This is a hard rule with no exceptions.
- Pick the night where {pa} and {ra} are BOTH home earliest with no evening conflicts. A night where {pa} has late meetings (home after 7pm) or evening events (happy hours, dinners) is NOT eligible — {pa} is not available for family dinner that night.
- Label it "family dinner 🍽️👨‍👩‍👦" in the schedule.
- If placed on a weekday, {ma} is already home for their regular hours — no overtime needed if it falls within their schedule. If placed on Sunday, {ma}'s time is babysitting/overtime and must be flagged.

GROCERY SHOPPING:
- Normally {pa} does grocery shopping at the grocery store on Sat or Sun.
- If {ra} has a coop shift that weekend, {ra} does the grocery shopping while there.

TONE:
- Casual, warm, efficient — like a group text from a competent parent, not a corporate memo.
- Use emojis naturally but don't overdo it: 🏊 swim, 🎱 pool, 🌳 forest school, 🏋️ gym, 🐔 chicken, 🧹 cleaner, ‼️ urgent, 🛒 coop, 🐣 babysitting
- Do NOT narrate childcare coverage or dog walks unless something unusual needs flagging.
- Do NOT show your reasoning or deliberation in the output. No "actually", "wait", "let's place it on..." — just state the final decision.
"""

FORMAT_BULLETS = """\
OUTPUT FORMAT — BULLETS:
- Start with "📆 Weekly schedule 📆" header, then a blank line.
- FIRST: Include a "**Quick notes before the week:**" section with 2-4 bullet points summarizing key context for the family — coop shift status, meal plan changes, follow-ups, notable schedule changes, or highlights from Open Brain notes. Keep it brief and actionable.
- Then "---" separator, then the daily breakdown.
- Each day gets a header line ("**Mon Apr 7:**", etc.) followed by bullet points.
- First bullet is always {ma}'s hours for that day.
- Then key events, dinner, gym, flags — one fact per bullet.
- Use "•" for bullets.
- Blank line between days for readability.
- End with a "‼️ Flags & asks:" section (bullets) ONLY if there are open questions or babysitting needs.
- Keep each day to 3-5 bullets max. Be concise — one fact per bullet.

Example:
📆 Weekly schedule 📆

**Quick notes before the week:**
– {ra} caught up on coop shifts — no nudge needed 👍
– Chicken moved to Sunday this week — Tuesday is leftovers
– {pa}: follow up with [names] (outreaches from last week)

---

**Mon Apr 7:**
• {ma}: 9-6
• {pa} gym after work 🏋️, home ~7:15
• {ra} dinner

**Tue Apr 8:**
• {ma}: 8-5
• {child} swim 11am 🏊
• {ra} pool 🎱 after 5:30
• {pa} chicken 🐔, home ~6:15
"""

FORMAT_PERSON = """\
OUTPUT FORMAT — PERSON VIEW:
- Start with "📆 Weekly schedule 📆" header.
- FIRST: Include a "**Quick notes before the week:**" section with 2-4 bullet points summarizing key context for the family — coop shift status, meal plan changes, follow-ups, notable schedule changes, or highlights from Open Brain notes. Keep it brief and actionable.
- Then "---" separator.
- Group by person with emoji headers: 👩 {pa}, 👨 {ra}, 👶 {child}, 🧑‍🍳 {ma}
- Under each person, summarize their whole week in 2-4 lines.
- Add a "🍽️ Dinners:" line with all 7 days on one line (e.g., "{ra} / {pa}🐔 / {ra} / 🍣 / {pa} / {pa} / TBD")
- End with "‼️ Flags:" section if needed.

Example:
📆 Weekly schedule 📆

**Quick notes before the week:**
– {ra} caught up on coop shifts — no nudge needed 👍
– Chicken moved to Sunday this week — Tuesday is leftovers

---

👩 {pa}:
Mon-Thu office. Gym Mon + Wed after work.
Thu late meetings, home ~7:15. Fri home, morning gym 🏋️
Sat coop 🛒 + groceries

👨 {ra}:
Mon dinner. Tue pool 🎱. Thu pool 🎱 straight from school.
Home ~5 daily. 10pm {pet} as always.

👶 {child}:
Tue swim 11am 🏊. Thu forest school 🌳 9-10:30.

🧑‍🍳 {ma}: 9-6 / 8-5 / 8-5 / 8-6:30 / 8-3:30
Wed: family dinner 🍽️👨‍👩‍👦

🍽️ Dinners: {ra} / {pa}🐔 / {ra} / 🍣 / {pa} / {pa} / TBD
"""

FORMAT_GRID = """\
OUTPUT FORMAT — COMPACT GRID:
- Start with "📆 Weekly schedule 📆" header.
- FIRST: Include a "**Quick notes before the week:**" section with 2-4 bullet points summarizing key context for the family. Then "---" separator.
- A text grid with columns: day, {ma} hours, dinner, notes.
- Use spaces to align columns (WhatsApp monospace works with triple backticks).
- Keep notes column short — just the key event or flag.
- End with "‼️ Flags:" section if needed.

Example:
📆 Week of April 6 📆

       {ma} hrs |  dinner  |  notes
Mon    9-6      |  {ra}       |  {pa} gym 🏋️ home ~7
Tue    8-5      |  {pa} 🐔   |  swim 🏊, {ra} pool 🎱
Wed    8-5      |  {ra}       |  🧹 Cleaner. family dinner 🍽️👨‍👩‍👦
Thu    8-6:30   |  🍣      |  🌳 forest school
Fri    8-3:30   |  {pa}       |  {pa} home, morning gym 🏋️
Sat    —        |  {pa}       |  {pa} coop 🛒 + groceries
Sun    —        |  {ra}       |  {pa} gym 🏋️
"""

FORMAT_MAP = {
    "bullets": FORMAT_BULLETS,
    "person": FORMAT_PERSON,
    "grid": FORMAT_GRID,
}


def get_system_prompt(format_name: str = "bullets", config: dict | None = None) -> str:
    """Build the full system prompt with the selected output format.

    Template placeholders ({primary}, {pa}, {partner}, {ra}, etc.) are filled
    from config.yaml so the prompt uses actual household names.
    """
    format_section = FORMAT_MAP.get(format_name, FORMAT_BULLETS)
    prompt = SYSTEM_PROMPT_BASE + "\n" + format_section

    # Determine names from config or use defaults
    if config:
        adults = list(config.get("household", {}).get("adults", {}).keys())
        children = list(config.get("household", {}).get("children", {}).keys())
        pets = list(config.get("household", {}).get("pets", {}).keys())
    else:
        adults, children, pets = [], [], []

    primary = (adults[0] if adults else "alex").title()
    partner = (adults[1] if len(adults) > 1 else "jordan").title()
    aupair = (adults[2] if len(adults) > 2 else "sam").title()
    child = (children[0] if children else "baby").title()
    pet = (pets[0] if pets else "buddy").title()

    return prompt.format(
        primary=primary,
        partner=partner,
        aupair=aupair,
        child=child,
        pet=pet,
        pa=primary[0],
        ra=partner[0],
        ma=aupair[0],
    )


def build_user_prompt(config: dict, context: dict, gcal_events: dict | None, manual_notes: str, open_brain_notes: list[dict] | None = None) -> str:
    """Build the user-facing prompt with all weekly inputs."""
    parts = []

    # Get names from config
    adults = list(config["household"]["adults"].keys())
    primary = adults[0] if adults else "alex"
    partner = adults[1] if len(adults) > 1 else "jordan"
    au_pair = adults[2] if len(adults) > 2 else "sam"

    # Get child and pet names
    children = list(config["household"].get("children", {}).keys())
    child = children[0] if children else "baby"
    pets = list(config["household"].get("pets", {}).keys())
    pet = pets[0] if pets else "buddy"

    parts.append(f"Generate the weekly schedule for the week of {context['week_monday']}.\n")

    # Au pair's schedule with explicit hour accounting
    au_pair_config = config["household"]["adults"][au_pair]
    caregiver_hours = context["caregiver_hours"]
    parts.append(f"{au_pair.upper()}'S BASE SCHEDULE ({caregiver_hours['weekly_total']}hrs/week total):")
    for day, hours in au_pair_config["schedule"].items():
        if day == "friday":
            parts.append(f"  Friday: {caregiver_hours['friday_hours']}hrs ({caregiver_hours['friday_hours']:.1f}hrs to reach {caregiver_hours['weekly_total']}hr weekly total)")
        else:
            daily = caregiver_hours["daily"].get(day, 0)
            parts.append(f"  {day.title()}: {hours} ({daily:.1f}hrs)")
    parts.append(f"  Mon-Thu subtotal: {caregiver_hours['mon_thu_total']:.1f}hrs")
    parts.append(f"  Weekly total: {caregiver_hours['weekly_total']}hrs")
    parts.append(f"  IMPORTANT: Anything beyond these hours is OVERTIME ('babysitting 🐣') and must be flagged as an ask.")
    parts.append("")

    # Derived context
    parts.append("THIS WEEK'S CONTEXT:")
    if context.get("cleaner_this_week"):
        parts.append("  - Cleaner coming Wednesday morning 🧹")
    else:
        parts.append("  - No cleaner this week")
    if context.get(f"{primary}_coop_saturday"):
        parts.append(f"  - {primary.title()} has coop shift Saturday at 9:30am 🛒")
    if context.get(f"{partner}_coop_sunday"):
        parts.append(f"  - {partner.title()} has coop shift Sunday at 9:30am 🛒 — {partner.title()} does grocery shopping this week")
    if context.get(f"{partner}_coop_behind"):
        parts.append(f"  - Reminder: {partner.title()} is behind on coop shifts — nudge them to schedule")
    parts.append("")

    # Fixed events from config
    child_config = config["household"]["children"].get(child, {})
    swim_loc = child_config.get("swim", {}).get("location", "swim location")
    pet_config = config["household"]["pets"].get(pet, {})
    dog_walker_name = pet_config.get("dog_walker", {}).get("name", "Dog walker")

    parts.append("FIXED WEEKLY EVENTS (always apply):")
    parts.append(f"  - Mon: {partner.title()} dinner. {primary.title()} gym (lift) after work. {primary.title()} to office.")
    parts.append(f"  - Tue: {child.title()} swim 11am 🏊 ({swim_loc}). Chicken Tuesday 🐔 ({primary.title()} cooks). {partner.title()} possibly at pool 🎱 after 5:30 (usually home first). {dog_walker_name} walks {pet.title()}. {primary.title()} to office.")
    parts.append(f"  - Wed: {dog_walker_name} walks {pet.title()}. {primary.title()} to office.")
    parts.append(f"  - Thu: {child.title()} forest school 9–10:30 🌳. {partner.title()} to pool 🎱 after 5:30 straight from school (does NOT come home first). {dog_walker_name} walks {pet.title()}. {primary.title()} to office.")
    parts.append(f"  - Fri: {primary.title()} home (no office). No other fixed events.")
    parts.append(f"  - Sat/Sun: Grocery shop at grocery store (see grocery rules). {primary.title()} tries to gym both days.")
    parts.append("")

    # Work schedule summary (computed from work calendar)
    work_analysis = context.get("work_analysis", {})
    if work_analysis:
        parts.append(f"{primary.upper()}'S WORK SCHEDULE THIS WEEK (Mon-Thu):")
        for day in ["monday", "tuesday", "wednesday", "thursday"]:
            info = work_analysis.get(day, {})
            if info.get("last_meeting_end"):
                end_str = info["last_meeting_end"].strftime("%I:%M%p").lstrip("0").lower()
                eta_str = info["eta_home"].strftime("%I:%M%p").lstrip("0").lower()
                if info.get("eta_home_via_gym"):
                    gym_eta_str = info["eta_home_via_gym"].strftime("%I:%M%p").lstrip("0").lower()
                else:
                    gym_eta_str = "N/A"
                late_note = " — LATE MEETINGS" if info["has_late_meetings"] else ""
                parts.append(f"  {day.title()}: last meeting ends {end_str}, home ~{eta_str}{late_note}. If gym: home ~{gym_eta_str}.")
            else:
                parts.append(f"  {day.title()}: no work meetings — flexible")
        parts.append("  NOTE: 'home ~X' = last meeting end + 45min buffer. 'If gym: home ~X' = last meeting + 20min commute to gym + 1hr gym + 20min commute home.")
        parts.append("")

    # Gym suggestions
    gym_suggestions = context.get("gym_suggestions", [])
    parts.append(f"{primary.upper()}'S GYM SCHEDULE:")
    parts.append("  - Monday: lift after work (fixed)")
    parts.append("  - Weekend: gym both days (lift 1, run 1)")
    parts.append("  - Midweek: pick ONE additional day only (run). Do NOT schedule gym Mon-Wed-Thu etc. Just Monday + 1 midweek day.")
    if gym_suggestions:
        parts.append("  - Additional gym day(s) based on work calendar:")
        for g in gym_suggestions:
            if g["timing"] == "before_work":
                parts.append(f"    * {g['day'].title()}: GYM BEFORE WORK — {g['note']}. Goes to gym near home, then commutes to office late.")
            elif g["timing"] == "morning":
                au_pair_note = f" Consider asking {au_pair.title()} to start early on Friday so they can go first thing." if g.get("marthe_early_helpful") else ""
                parts.append(f"    * {g['day'].title()}: GYM FRIDAY MORNING — {g['note']}. Home all day, gym in the morning before nap routine.{au_pair_note}")
            else:
                parts.append(f"    * {g['day'].title()}: gym after work — {g['note']}.")
    else:
        parts.append("  - No good midweek gym days this week (meetings run too late)")
    parts.append("  IMPORTANT: When scheduling gym, include the ETA home time so everyone knows when they will be back.")
    parts.append("  For gym-before-work days: note that they are commuting late and won't be in office until after gym + 20min commute.")
    parts.append("")

    # Non-work GCal events (personal + family)
    if gcal_events:
        parts.append("PERSONAL & FAMILY CALENDAR EVENTS THIS WEEK:")
        has_events = False
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            events = gcal_events.get(day, [])
            non_work = [e for e in events if e.get("calendar_label") != "work"]
            if non_work:
                has_events = True
                event_strs = []
                for e in non_work:
                    time_str = ""
                    if not e["all_day"]:
                        start_time = e["start"].split("T")[1][:5] if "T" in e["start"] else ""
                        time_str = f" at {start_time}" if start_time else ""
                    event_strs.append(f"{e['summary']}{time_str} [{e.get('calendar_label', '')}]")
                parts.append(f"  {day.title()}: {'; '.join(event_strs)}")
        if not has_events:
            parts.append("  (none)")
        parts.append("")
    else:
        parts.append("GOOGLE CALENDAR: Not connected. Using manual notes only.\n")

    # Open Brain notes
    if open_brain_notes:
        parts.append(format_open_brain_for_prompt(open_brain_notes))

    # Manual notes
    if manual_notes.strip():
        parts.append(f"ADDITIONAL NOTES FROM {primary.upper()}:\n{manual_notes}\n")
    else:
        parts.append("ADDITIONAL NOTES: None provided.\n")

    parts.append("Now generate the schedule. Start with '📆 Weekly schedule 📆' and follow the format.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------


def generate_with_claude(system: str, user_prompt: str) -> str:
    """Call Claude API to generate the schedule."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file.\n"
            "Get a key at https://console.anthropic.com/settings/keys"
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("\n🗓️  Weekly Schedule Generator\n")

    # Determine target week
    if len(sys.argv) > 1:
        try:
            target_monday = datetime.date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}. Use YYYY-MM-DD format.")
            sys.exit(1)
    else:
        target_monday = next_monday()

    week_end = target_monday + datetime.timedelta(days=6)
    print(f"Generating schedule for: {target_monday.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}")

    # Load config
    config = load_config()
    context = compute_week_context(config, target_monday)

    # Get names from config
    adults = list(config["household"]["adults"].keys())
    primary = adults[0] if adults else "alex"
    partner = adults[1] if len(adults) > 1 else "jordan"

    # Show derived context
    caregiver_hours = context["caregiver_hours"]
    print(f"\n  Cleaner this week: {'Yes' if context.get('cleaner_this_week') else 'No'}")
    print(f"  {primary.title()} coop Saturday: {'Yes' if context.get(f'{primary}_coop_saturday') else 'No'}")
    print(f"  {partner.title()} coop Sunday: {'Yes' if context.get(f'{partner}_coop_sunday') else 'No'}")
    print(f"  Au pair: Mon-Thu {caregiver_hours['mon_thu_total']:.1f}hrs + Fri {caregiver_hours['friday_hours']:.1f}hrs = {caregiver_hours['weekly_total']}hrs")

    # Authenticate GCal upfront (gate before asking for notes)
    print("\nConnecting to Google Calendar...")
    cal_ids = {
        "personal": os.getenv("GCAL_PERSONAL_ID"),
        "family": os.getenv("GCAL_FAMILY_ID"),
        "work": os.getenv("GCAL_WORK_ID"),
    }
    gcal_events = None
    if any(cal_ids.values()):
        try:
            get_credentials()  # authenticate first
            print("  Authenticated.")
            gcal_events = pull_gcal_events(target_monday, config)
            if gcal_events:
                total = sum(len(v) for v in gcal_events.values())
                print(f"  Found {total} events across the week.")
                work_analysis = analyze_work_calendar(gcal_events)
                gym_suggestions = suggest_gym_days(work_analysis)
                context["work_analysis"] = work_analysis
                context["gym_suggestions"] = gym_suggestions
                display_gcal_events(gcal_events, work_analysis)
                if gym_suggestions:
                    print("\n  Suggested additional gym days:")
                    for g in gym_suggestions:
                        print(f"    {g['day'].title()}: {g['note']}")
            else:
                print("  No events found.")
        except Exception as exc:
            print(f"  Warning: GCal setup failed: {exc}")
            print("  Continuing without calendar events.")
    else:
        print("  GCal not configured — skipping. Add calendar IDs to .env to enable.")

    # Open Brain notes
    open_brain_notes = []
    if os.getenv("OPEN_BRAIN_MCP_URL"):
        print("\nConnecting to Open Brain...")
        try:
            open_brain_notes = fetch_open_brain_notes(target_monday)
            display_open_brain_notes(open_brain_notes)
        except Exception as exc:
            print(f"  Warning: Open Brain failed: {exc}")
            print("  Continuing without Open Brain notes.")
    else:
        print("\n  Open Brain not configured — skipping. Add OPEN_BRAIN_MCP_URL to .env to enable.")

    # Manual notes (after GCal and Open Brain so user can see everything first)
    print("\nAdd any notes for this week (dinner plans, events, schedule changes).")
    print("Type your notes, then press Enter twice when done (or just Enter to skip):\n")
    lines = []
    while True:
        line = input()
        if line == "":
            if lines and lines[-1] == "":
                break
            if not lines:
                break
            lines.append(line)
        else:
            lines.append(line)
    manual_notes = "\n".join(lines).strip()

    # Generate
    output_format = config.get("schedule_output", {}).get("format", "bullets")
    print(f"\nGenerating schedule (format: {output_format}) with Claude...")
    system_prompt = get_system_prompt(output_format, config)
    user_prompt = build_user_prompt(config, context, gcal_events, manual_notes, open_brain_notes)
    schedule = generate_with_claude(system_prompt, user_prompt)

    # Output
    print("\n" + "=" * 60)
    print(schedule)
    print("=" * 60)

    # Copy to clipboard
    try:
        pyperclip.copy(schedule)
        print("\n✅ Copied to clipboard! Paste into WhatsApp and pin it.")
    except pyperclip.PyperclipException:
        print("\n(Could not copy to clipboard automatically. Select and copy the text above.)")

    print()


if __name__ == "__main__":
    main()
