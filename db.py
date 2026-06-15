"""Supabase reads for the weekly schedule generator.

Pulls household data (contacts, pets, events, schedules) from the family-calendar
extension tables and returns a dict in the same shape that the original
config.yaml provided. This keeps `generate_schedule.py` mostly unchanged — only
the source of household data has moved.

Environment variables required:
    SUPABASE_URL              — your Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY — service role key (bypasses RLS for read access)
    DEFAULT_USER_ID           — the user_id whose household to load
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _user_id() -> str:
    return os.environ["DEFAULT_USER_ID"]


# ---------------------------------------------------------------------------
# Low-level fetchers
# ---------------------------------------------------------------------------


def _fetch_contacts(sb: Client) -> list[dict]:
    res = sb.table("contacts").select("*, household_details(*)").eq("user_id", _user_id()).execute()
    return res.data or []


def _fetch_pets(sb: Client) -> list[dict]:
    res = sb.table("pets").select("*").eq("user_id", _user_id()).execute()
    return res.data or []


def _fetch_events(sb: Client) -> list[dict]:
    res = (
        sb.table("events")
        .select("*, contact:contact_id(id,name,tags,service_type), pet:pet_id(id,name), location:location_id(id,name,address)")
        .eq("user_id", _user_id())
        .execute()
    )
    return res.data or []


def _fetch_pet_walks(sb: Client) -> list[dict]:
    res = (
        sb.table("pet_walks")
        .select("*, default_walker:default_walker_contact_id(id,name)")
        .eq("user_id", _user_id())
        .execute()
    )
    return res.data or []


def _fetch_caregiver_hours(sb: Client) -> list[dict]:
    res = (
        sb.table("caregiver_daily_hours")
        .select("*, contact:contact_id(id,name)")
        .eq("user_id", _user_id())
        .execute()
    )
    return res.data or []


def _fetch_dinner_defaults(sb: Client) -> list[dict]:
    res = (
        sb.table("dinner_defaults")
        .select("*, cook:cook_id(id,name)")
        .eq("user_id", _user_id())
        .execute()
    )
    return res.data or []


# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------


def _fmt_time(t: str | None) -> str | None:
    """Postgres returns TIME as 'HH:MM:SS'. Trim to 'HH:MM' to match yaml convention."""
    if not t:
        return None
    return t[:5] if len(t) >= 5 else t


def _fmt_range(start: str | None, end: str | None) -> str | None:
    s, e = _fmt_time(start), _fmt_time(end)
    if s and e:
        return f"{s}-{e}"
    return None


# Role mapping — household_details.role → which adult bucket the person goes into.
# Adults appear in the order [primary, partner, au_pair] as the Python code reads
# adults[0]/[1]/[2] by position.
_ROLE_ORDER = {"primary_scheduler": 0, "partner": 1, "au_pair": 2}


def _build_adults(contacts: list[dict], hours: list[dict]) -> dict[str, dict]:
    """Build the adults dict in config-shape order: primary, partner, au_pair."""
    adults: list[tuple[int, str, dict]] = []  # (order, name_lower, payload)

    # caregiver hours by contact_id
    hours_by_contact: dict[str, list[dict]] = {}
    for h in hours:
        hours_by_contact.setdefault(h["contact_id"], []).append(h)

    for c in contacts:
        if "household_member" not in (c.get("tags") or []):
            continue
        # PostgREST returns 1:1 embeds as object-or-null, but tolerate the
        # list shape just in case (older PostgREST versions, alias quirks).
        hd_raw = c.get("household_details")
        if isinstance(hd_raw, list):
            hd = hd_raw[0] if hd_raw else {}
        elif isinstance(hd_raw, dict):
            hd = hd_raw
        else:
            hd = {}
        role = hd.get("role")
        if role not in _ROLE_ORDER:
            continue  # not an adult (child, etc.)

        name_lower = c["name"].lower()
        payload: dict[str, Any] = {"role": _humanize_role(role)}

        if hd.get("work_days"):
            payload["work_days"] = hd["work_days"]
        wh = _fmt_range(hd.get("work_start"), hd.get("work_end"))
        if wh:
            payload["work_hours"] = wh
        if hd.get("commute_minutes") is not None:
            payload["commute_minutes"] = hd["commute_minutes"]
        if hd.get("leaves_home"):
            payload["leaves_home"] = _fmt_time(hd["leaves_home"])
        if hd.get("returns_home"):
            payload["returns_home"] = _fmt_time(hd["returns_home"])
        if hd.get("weekly_hours_target") is not None:
            payload["weekly_hours"] = float(hd["weekly_hours_target"])
        if hd.get("preferences"):
            payload["preferences"] = hd["preferences"]
        if hd.get("schedule_stability_notes"):
            payload["notes"] = hd["schedule_stability_notes"]

        # Caregivers: include the per-day schedule dict the Python expects
        if role == "au_pair":
            sched: dict[str, str] = {}
            for h in sorted(hours_by_contact.get(c["id"], []),
                            key=lambda x: _DOW_ORDER.get(x["day_of_week"], 99)):
                if h.get("is_balance"):
                    sched[h["day_of_week"]] = "balance"
                else:
                    rng = _fmt_range(h.get("start_time"), h.get("end_time"))
                    if rng:
                        sched[h["day_of_week"]] = rng
            payload["schedule"] = sched

        adults.append((_ROLE_ORDER[role], name_lower, payload))

    adults.sort(key=lambda x: x[0])
    return {name: payload for _order, name, payload in adults}


def _humanize_role(role: str) -> str:
    return {
        "primary_scheduler": "Primary scheduler",
        "partner": "Partner",
        "au_pair": "Au pair",
        "child": "Child",
    }.get(role, role)


_DOW_ORDER = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _build_children(contacts: list[dict], events: list[dict]) -> dict[str, dict]:
    """Children with their nap/bedtime/wake + swim/forest_school events."""
    children: dict[str, dict] = {}

    # Index events by child contact_id
    events_by_contact: dict[str, list[dict]] = {}
    for e in events:
        cid = e.get("contact_id")
        if cid:
            events_by_contact.setdefault(cid, []).append(e)

    for c in contacts:
        if "household_member" not in (c.get("tags") or []):
            continue
        hd_raw = c.get("household_details")
        if isinstance(hd_raw, list):
            hd = hd_raw[0] if hd_raw else {}
        elif isinstance(hd_raw, dict):
            hd = hd_raw
        else:
            hd = {}
        if hd.get("role") != "child":
            continue

        name_lower = c["name"].lower()
        payload: dict[str, Any] = {}

        # Routines
        nap = _fmt_range(hd.get("nap_start"), hd.get("nap_end"))
        if nap:
            payload["nap"] = nap
        if hd.get("bedtime"):
            payload["bedtime"] = _fmt_time(hd["bedtime"])
        wake = _fmt_range(hd.get("wake_start"), hd.get("wake_end"))
        if wake:
            payload["wake"] = wake

        # Birthday / age
        if c.get("birth_date"):
            payload["birth_date"] = c["birth_date"]

        # Look up swim / forest_school events for this child
        for e in events_by_contact.get(c["id"], []):
            atype = e.get("activity_type")
            if atype == "swim":
                payload["swim"] = {
                    "day": e.get("day_of_week"),
                    "time": _fmt_time(e.get("start_time")),
                    "location": (e.get("location") or {}).get("name") or (e.get("location") or {}).get("address"),
                }
                if e.get("end_time") and e.get("start_time"):
                    duration = _duration_min(e["start_time"], e["end_time"])
                    if duration is not None:
                        payload["swim"]["duration_min"] = duration
            elif atype == "forest_school":
                payload["forest_school"] = {
                    "day": e.get("day_of_week"),
                    "time": _fmt_range(e.get("start_time"), e.get("end_time")) or _fmt_time(e.get("start_time")),
                }

        children[name_lower] = payload

    return children


def _duration_min(start: str, end: str) -> int | None:
    try:
        sh, sm = int(start[:2]), int(start[3:5])
        eh, em = int(end[:2]), int(end[3:5])
        return (eh * 60 + em) - (sh * 60 + sm)
    except (ValueError, IndexError):
        return None


def _build_pets(pets: list[dict], walks: list[dict], events: list[dict]) -> dict[str, dict]:
    """Pets with walks_per_day, walk_schedule, dog_walker."""
    result: dict[str, dict] = {}

    walks_by_pet: dict[str, list[dict]] = {}
    for w in walks:
        walks_by_pet.setdefault(w["pet_id"], []).append(w)

    # Dog walker visits: events with activity_type='dog_walker_visit' grouped by vendor + pet
    walker_events_by_pet: dict[str, list[dict]] = {}
    for e in events:
        if e.get("activity_type") == "dog_walker_visit" and e.get("pet_id"):
            walker_events_by_pet.setdefault(e["pet_id"], []).append(e)

    for p in pets:
        name_lower = p["name"].lower()
        payload: dict[str, Any] = {
            "type": p.get("species"),
        }
        if p.get("walks_per_day") is not None:
            payload["walks_per_day"] = p["walks_per_day"]
        if p.get("birth_date"):
            payload["birth_date"] = p["birth_date"]

        # Walk schedule by slot
        walk_schedule: dict[str, dict] = {}
        for w in walks_by_pet.get(p["id"], []):
            slot_info: dict[str, Any] = {}
            if w.get("scheduled_time"):
                slot_info["time"] = _fmt_time(w["scheduled_time"])
            walker = w.get("default_walker") or {}
            if walker.get("name"):
                slot_info["who"] = walker["name"]
            if w.get("notes"):
                slot_info["notes"] = w["notes"]
            walk_schedule[w["slot"]] = slot_info
        if walk_schedule:
            payload["walk_schedule"] = walk_schedule

        # Dog walker: collect vendor + days from walker events
        walker_events = walker_events_by_pet.get(p["id"], [])
        if walker_events:
            walker_name = None
            days: list[str] = []
            duration_min = None
            for ev in walker_events:
                vendor = ev.get("contact") or {}
                if vendor.get("name") and not walker_name:
                    walker_name = vendor["name"]
                if ev.get("day_of_week"):
                    days.append(ev["day_of_week"])
                if duration_min is None and ev.get("start_time") and ev.get("end_time"):
                    duration_min = _duration_min(ev["start_time"], ev["end_time"])
            if walker_name:
                dw: dict[str, Any] = {"name": walker_name, "days": sorted(set(days), key=lambda d: _DOW_ORDER.get(d, 99))}
                if duration_min:
                    dw["duration_min"] = duration_min
                payload["dog_walker"] = dw

        result[name_lower] = payload

    return result


def _build_recurring(events: list[dict]) -> dict[str, Any]:
    """Build the recurring section: cleaner + coop_shifts."""
    recurring: dict[str, Any] = {"coop_shifts": {}}

    for e in events:
        atype = e.get("activity_type")
        contact = e.get("contact") or {}

        if atype == "cleaner":
            recurring["cleaner"] = {
                "role": "Cleaner",
                "name": contact.get("name"),
                "frequency": _describe_cadence(e),
                "reference_date": e.get("reference_date"),
            }
        elif atype == "coop_shift":
            cname = (contact.get("name") or "").lower()
            if cname:
                recurring["coop_shifts"][cname] = {
                    "frequency_weeks": e.get("cadence_weeks"),
                    "day": e.get("day_of_week"),
                    "start_date": e.get("reference_date"),
                    "time": _fmt_time(e.get("start_time")),
                }
                if e.get("notes"):
                    recurring["coop_shifts"][cname]["notes"] = e["notes"]

    return recurring


def _describe_cadence(e: dict) -> str:
    ctype = e.get("cadence_type")
    weeks = e.get("cadence_weeks")
    dow = e.get("day_of_week") or ""
    if ctype == "biweekly":
        return f"every other {dow.title()} morning"
    if ctype == "every_n_weeks" and weeks:
        return f"every {weeks} {dow.title()}s"
    if ctype == "weekly":
        return f"every {dow.title()}"
    return ctype or ""


def _build_dinner(defaults: list[dict]) -> dict[str, Any]:
    """Build the dinner section.

    Returns the defaults dict (day → "Name (notes)") that matches config.yaml shape.
    'negotiable' and 'constraint' aren't stored in the DB; defaults fall back to yaml.
    """
    out: dict[str, str] = {}
    for d in defaults:
        cook = d.get("cook") or {}
        cook_name = cook.get("name", "")
        notes = d.get("dish_notes")
        if notes:
            out[d["day_of_week"]] = f"{cook_name} ({notes})"
        else:
            out[d["day_of_week"]] = cook_name
    return {"defaults": out}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_household_from_db() -> dict[str, Any]:
    """Fetch household + recurring + dinner sections from Supabase.

    Returns a dict in the same shape as the original config.yaml so it can be
    merged with the (now-reduced) yaml for app-behavior settings.
    """
    sb = get_client()

    contacts = _fetch_contacts(sb)
    pets = _fetch_pets(sb)
    events = _fetch_events(sb)
    walks = _fetch_pet_walks(sb)
    hours = _fetch_caregiver_hours(sb)
    dinners = _fetch_dinner_defaults(sb)

    adults = _build_adults(contacts, hours)
    children = _build_children(contacts, events)
    pets_dict = _build_pets(pets, walks, events)

    return {
        "household": {
            "adults": adults,
            "children": children,
            "pets": pets_dict,
        },
        "recurring": _build_recurring(events),
        "dinner": _build_dinner(dinners),
    }
