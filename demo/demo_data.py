"""Fixture data for the public demo — an entirely fictional household.

Nothing here is real. The names, employer, calendars, schedules and generated
output are invented for the portfolio demo so the app can be shown publicly
without exposing household data. The *shapes* mirror the live API responses
(``db.fetch_adult_schedules``, ``db.fetch_household_editable``,
``config_io.read_settings``, ``web._calendar_payload``) so the unmodified
front-end runs against them unchanged.

Calendar events are stored as weekday offsets, not dates — the demo shim
projects them onto whichever Monday the week-picker is set to.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
# Stable fake UUIDs so dinner-cook references resolve.
PRIYA = "11111111-1111-4111-8111-111111111111"
DAN = "22222222-2222-4222-8222-222222222222"
INES = "33333333-3333-4333-8333-333333333333"
MIRA = "44444444-4444-4444-8444-444444444444"
THEO = "55555555-5555-4555-8555-555555555555"

PEOPLE = [
    {"contact_id": PRIYA, "name": "Priya Raman", "role": "primary_scheduler", "birth_date": "1988-03-14"},
    {"contact_id": DAN, "name": "Dan Raman", "role": "partner", "birth_date": "1986-11-02"},
    {"contact_id": INES, "name": "Inês Oliveira", "role": "au_pair", "birth_date": "2003-06-21"},
    {"contact_id": MIRA, "name": "Mira Raman", "role": "child", "birth_date": "2020-01-09"},
    {"contact_id": THEO, "name": "Theo Raman", "role": "child", "birth_date": "2024-04-30"},
]

PETS = [
    {
        "id": "66666666-6666-4666-8666-666666666666",
        "name": "Biscuit",
        "species": "dog",
        "breed": "whippet cross",
        "walks_per_day": 2,
        "notes": "midday walker on Priya's office days",
    },
]

DINNER = {
    "monday": {"cook_id": DAN, "dish_notes": "soup"},
    "tuesday": {"cook_id": PRIYA, "dish_notes": "roast chicken"},
    "wednesday": {"cook_id": DAN, "dish_notes": ""},
    "thursday": {"cook_id": PRIYA, "dish_notes": "stir fry"},
    "friday": {"cook_id": DAN, "dish_notes": "pizza night"},
    "saturday": {"cook_id": None, "dish_notes": ""},
    "sunday": {"cook_id": PRIYA, "dish_notes": "leftovers"},
}

# --------------------------------------------------------------------------
# Work schedules (shape of db.fetch_adult_schedules)
# --------------------------------------------------------------------------
WORK_SCHEDULES = [
    {
        "contact_id": PRIYA,
        "name": "Priya Raman",
        "role": "primary_scheduler",
        "work_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "work_start": "09:00",
        "work_end": "18:00",
        "commute_minutes": 35,
        "leaves_home": "08:15",
        "returns_home": "18:40",
        "weekly_hours_target": None,
        "schedule_stability_notes": "In the office Tue–Thu, remote Mon & Fri. Late meetings move the ETA home.",
    },
    {
        "contact_id": DAN,
        "name": "Dan Raman",
        "role": "partner",
        "work_days": ["monday", "tuesday", "wednesday", "thursday"],
        "work_start": "08:30",
        "work_end": "17:00",
        "commute_minutes": 20,
        "leaves_home": "08:05",
        "returns_home": "17:25",
        "weekly_hours_target": None,
        "schedule_stability_notes": "Fridays off — does both school runs. Occasional overnight site visits.",
    },
    {
        "contact_id": INES,
        "name": "Inês Oliveira",
        "role": "au_pair",
        "work_days": [],
        "work_start": None,
        "work_end": None,
        "commute_minutes": None,
        "leaves_home": None,
        "returns_home": None,
        "weekly_hours_target": 30.0,
        "schedule_stability_notes": "Friday is the balance day — hours flex to hit 30/week.",
        "caregiver_hours": {
            "monday": {"start_time": "07:30", "end_time": "13:30", "is_balance": False},
            "tuesday": {"start_time": "08:00", "end_time": "17:00", "is_balance": False},
            "wednesday": {"start_time": "08:00", "end_time": "17:00", "is_balance": False},
            "thursday": {"start_time": "08:00", "end_time": "18:30", "is_balance": False},
            "friday": {"start_time": None, "end_time": None, "is_balance": True},
            "saturday": {"start_time": None, "end_time": None, "is_balance": False},
            "sunday": {"start_time": None, "end_time": None, "is_balance": False},
        },
    },
]

# --------------------------------------------------------------------------
# Output settings (shape of config_io.read_settings / read_calendars)
# --------------------------------------------------------------------------
SETTINGS = {
    "format": "bullets",
    "group_name": "Raman family 🏡",
    "pin": True,
    "excluded_events": ["^Birthday", "therapy", "^Hold:", "^Focus", "OOO", "^Canceled"],
    "emoji_map": {
        "gym": "🏋️",
        "swim": "🏊",
        "dinner": "🍽️",
        "dog": "🐕",
        "school": "🎒",
        "cleaner": "🧹",
        "groceries": "🛒",
        "forest": "🌳",
        "sitter": "🐣",
    },
}

CALENDARS = {"work": "priya@northwind-analytics.example"}

# --------------------------------------------------------------------------
# Calendar week — day index 0 = Monday
# --------------------------------------------------------------------------
# calendar: personal | family | work (drives the colour band in the grid)
EVENTS = [
    # Monday
    {"day": 0, "calendar": "work", "summary": "Sprint planning", "start": "09:30", "end": "10:30"},
    {"day": 0, "calendar": "work", "summary": "1:1 — Marcus", "start": "14:00", "end": "14:30"},
    {"day": 0, "calendar": "personal", "summary": "Gym — strength", "start": "18:45", "end": "19:45"},
    # Tuesday
    {"day": 1, "calendar": "work", "summary": "Roadmap review", "start": "10:00", "end": "11:00"},
    {"day": 1, "calendar": "family", "summary": "Theo swim lesson", "start": "11:00", "end": "11:45"},
    {"day": 1, "calendar": "family", "summary": "Dog walker", "start": "12:30", "end": "13:00"},
    {"day": 1, "calendar": "work", "summary": "Design review", "start": "15:00", "end": "16:00"},
    # Wednesday
    {"day": 2, "calendar": "family", "summary": "Cleaner", "all_day": True},
    {"day": 2, "calendar": "work", "summary": "Leadership sync", "start": "09:00", "end": "10:00"},
    {"day": 2, "calendar": "family", "summary": "Dog walker", "start": "12:30", "end": "13:00"},
    {"day": 2, "calendar": "work", "summary": "Vendor call — Astra", "start": "16:30", "end": "17:30"},
    {"day": 2, "calendar": "family", "summary": "Family dinner", "start": "18:30", "end": "19:30"},
    # Thursday
    {"day": 3, "calendar": "family", "summary": "Dan — site visit, back late", "all_day": True},
    {"day": 3, "calendar": "family", "summary": "Mira forest school", "start": "09:00", "end": "10:30"},
    {"day": 3, "calendar": "family", "summary": "Dog walker", "start": "12:30", "end": "13:00"},
    {"day": 3, "calendar": "work", "summary": "Quarterly planning", "start": "13:00", "end": "16:00"},
    {"day": 3, "calendar": "work", "summary": "Board prep", "start": "17:00", "end": "18:30"},
    # Friday
    {"day": 4, "calendar": "personal", "summary": "Gym — run club", "start": "07:00", "end": "08:00"},
    {"day": 4, "calendar": "family", "summary": "Mira school assembly", "start": "09:15", "end": "10:00"},
    # Saturday
    {"day": 5, "calendar": "family", "summary": "Co-op shift", "start": "09:30", "end": "12:00"},
    {"day": 5, "calendar": "personal", "summary": "Anya's leaving drinks", "start": "19:30", "end": "23:00"},
    # Sunday
    {"day": 6, "calendar": "family", "summary": "Groceries + meal prep", "start": "10:00", "end": "12:00"},
]

# --------------------------------------------------------------------------
# Pre-generated Claude output, one per format.
# --------------------------------------------------------------------------
# These are what the live pipeline produces for the week above. They are played
# back verbatim by the demo; the flag chips are scraped from them by the same
# front-end code path as the live app.
BULLETS = """📆 Weekly schedule 📆

Quick notes:
• Thursday is the tight one — Dan is away on a site visit and Priya has board prep until 6:30, so Inês is covering solo until late. See the ask below.
• Saturday night both of you are out at Anya's leaving drinks — that needs a sitter booked.
• Priya is remote Mon & Fri, in the office Tue–Thu.

Mon:
• Inês 7:30–1:30
• Priya remote, sprint planning 9:30 🎒 Dan does both runs
• Dan dinner (soup) 🍽️
• Priya gym 6:45pm 🏋️

Tue:
• Inês 8:00–5:00
• Priya in office, home ~6:40
• Theo swim 11am 🏊 (Inês)
• Dog walker 12:30 🐕
• Priya dinner (roast chicken) 🍽️ — starts after she's in, eat ~7:15

Wed:
• Inês 8:00–5:00
• 🧹 Cleaner in
• Priya in office, vendor call runs to 5:30, home ~6:10
• Dog walker 12:30 🐕
• Family dinner 6:30 🍽️👨‍👩‍👧 — Dan cooking, Priya arrives partway through

Thu:
• Inês 8:00–6:30
• Dan away — site visit, back late ‼️
• Mira forest school 9–10:30 🌳
• Dog walker 12:30 🐕
• Priya board prep until 6:30, home ~7:10 ‼️ 40min coverage gap after Inês ends 🐣
• Priya dinner (stir fry) 🍽️ — likely late, feed the kids first

Fri:
• Inês balance day — hours to hit 30
• Priya remote, run club 7am 🏋️
• Dan off, school assembly 9:15 🎒
• Dan dinner (pizza night) 🍽️

Sat:
• Co-op shift 9:30–12 🛒 + groceries
• Anya's leaving drinks 7:30pm — both out ‼️ sitter from 6:45pm 🐣
• No cook assigned — takeaway before the sitter arrives?

Sun:
• Groceries + meal prep 10–12 🛒
• Priya dinner (leftovers) 🍽️

‼️ Flags & asks:
• Thu: 40min coverage gap — Inês ends 6:30, Priya home ~7:10, Dan away. @Inês can you stay until 7:15? That's 45min overtime 🐣
• Sat: sitter needed 6:45pm–late, both parents out. Book by Wednesday 🐣
• Inês is at 27.5h before Friday — Friday needs 2.5h to hit the 30h target
• Wed: Priya arrives ~6:10 for a 6:30 family dinner — no slack if the vendor call overruns"""

PERSON = """📆 Weekly schedule 📆

PRIYA
• Mon: remote. Sprint planning 9:30. Gym 6:45pm 🏋️
• Tue: office, home ~6:40. Cooking — roast chicken 🍽️
• Wed: office, vendor call to 5:30, home ~6:10. Family dinner 6:30
• Thu: office. Board prep to 6:30, home ~7:10 ‼️ solo evening, Dan away
• Fri: remote. Run club 7am 🏋️
• Sat: co-op shift 9:30 🛒. Out from 7:30pm
• Sun: groceries 10–12 🛒. Cooking — leftovers

DAN
• Mon: work 8:30–5, home 5:25. Both school runs 🎒. Cooking — soup 🍽️
• Tue: work 8:30–5, home 5:25
• Wed: work 8:30–5, home 5:25. Cooking — family dinner 6:30 🍽️👨‍👩‍👧
• Thu: away — site visit, back late ‼️
• Fri: off. School assembly 9:15 🎒. Cooking — pizza night 🍽️
• Sat: co-op + kids while Priya is at her shift
• Sun: free

INÊS
• Mon: 7:30–1:30 (6h)
• Tue: 8:00–5:00 (9h) — Theo swim 11am 🏊
• Wed: 8:00–5:00 (9h)
• Thu: 8:00–6:30 (10.5h) — solo cover, Dan away ‼️ ask: stay to 7:15 🐣
• Fri: balance day — 2.5h to reach the 30h target
• Sat/Sun: off

KIDS
• Mira: forest school Thu 9–10:30 🌳, school assembly Fri 9:15 🎒
• Theo: swim Tue 11am 🏊

‼️ Flags & asks:
• Thu: 40min coverage gap — Inês ends 6:30, Priya home ~7:10, Dan away. @Inês can you stay until 7:15? 45min overtime 🐣
• Sat: sitter needed 6:45pm, both parents out at Anya's leaving drinks. Book by Wednesday 🐣
• Inês is at 27.5h before Friday — Friday needs 2.5h to hit 30h"""

GRID = """📆 Weekly schedule 📆

        │ Priya          │ Dan            │ Inês       │ Kids
────────┼────────────────┼────────────────┼────────────┼──────────────────
Mon     │ remote         │ 8:30–5         │ 7:30–1:30  │ —
        │ gym 6:45 🏋️    │ dinner: soup   │            │
────────┼────────────────┼────────────────┼────────────┼──────────────────
Tue     │ office ~6:40   │ 8:30–5         │ 8:00–5:00  │ Theo swim 11 🏊
        │ dinner: chicken│                │            │ 🐕 12:30
────────┼────────────────┼────────────────┼────────────┼──────────────────
Wed     │ office ~6:10   │ 8:30–5         │ 8:00–5:00  │ 🧹 cleaner
        │ family dinner  │ cooking 6:30   │            │ 🐕 12:30
────────┼────────────────┼────────────────┼────────────┼──────────────────
Thu ‼️   │ office ~7:10   │ AWAY           │ 8:00–6:30  │ forest school 🌳
        │ dinner: stirfry│ site visit     │ ask → 7:15 │ 🐕 12:30
────────┼────────────────┼────────────────┼────────────┼──────────────────
Fri     │ remote, gym 7  │ off, assembly  │ balance 2.5h│ assembly 9:15 🎒
        │                │ dinner: pizza  │            │
────────┼────────────────┼────────────────┼────────────┼──────────────────
Sat     │ co-op 9:30 🛒  │ kids am        │ off        │ sitter 6:45 🐣
        │ out 7:30pm     │ out 7:30pm     │            │
────────┼────────────────┼────────────────┼────────────┼──────────────────
Sun     │ groceries 🛒   │ free           │ off        │ —
        │ dinner: leftovers│              │            │

‼️ Flags & asks:
• Thu: 40min coverage gap — Inês ends 6:30, Priya home ~7:10, Dan away. Ask Inês to stay to 7:15 (45min overtime) 🐣
• Sat: sitter needed 6:45pm — both parents out 🐣
• Inês at 27.5h before Friday; Friday needs 2.5h to hit the 30h target"""

SCHEDULES = {"bullets": BULLETS, "person": PERSON, "grid": GRID}

# --------------------------------------------------------------------------
# Run history — offsets in weeks back from the demo week.
# --------------------------------------------------------------------------
HISTORY = [
    {
        "weeks_ago": 1,
        "format": "bullets",
        "created_offset": "T09:12",
        "schedule": """📆 Weekly schedule 📆

Quick notes:
• Half-term — no forest school, no assembly. Inês is on longer days Mon–Wed to cover.
• Dan took Thursday off, so no gap this week.

Mon:
• Inês 7:30–5:00 (half-term cover)
• Priya remote, home all day
• Dan dinner 🍽️
...""",
    },
    {
        "weeks_ago": 2,
        "format": "person",
        "created_offset": "T08:40",
        "schedule": """📆 Weekly schedule 📆

PRIYA
• Mon–Fri: office Tue–Thu, remote Mon & Fri
• Wed: leadership offsite, home ~8pm ‼️ Dan solo for bedtime
...

‼️ Flags & asks:
• Wed: Priya home ~8pm — Dan solo for both bedtimes
• Co-op shift still unbooked — you're behind 🛒""",
    },
]
