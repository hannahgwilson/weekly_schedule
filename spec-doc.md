# Weekly Schedule Generator — Spec Document

## Overview

An AI-assisted tool that generates a weekly household schedule and sends it to a WhatsApp group every Sunday. The schedule coordinates childcare, pet care, meals, gym scheduling, and adult schedules for a household with two parents, an au pair, a toddler, and a dog.

---

## Household Members

The tool is configured via `config.yaml`. The example configuration uses these placeholder names:

| Person | Role | Key Constraints |
|--------|------|-----------------|
| Alex (A) | Primary scheduler | Office Mon–Thu 9–5:30, configurable commute. **Home on Fridays.** Gym 3x/week+ (Mon lift after work, run 1–2x midweek, gym both weekend days). **One workout per day max.** Coop shift every 6th Saturday. |
| Jordan (J) | Partner/Teacher | Leaves 7:15am, home ~5pm. Pool Thu (straight from school); occasionally Tue (usually home first). Squash 1–2x/week, typically one weekend day — added to shared GCal. Coop shift every 6 Sundays. 10pm dog walk every night. |
| Sam (S) | Au pair | 45hrs/week. Mon 9–6 (9hrs), Tue 8–5 (9hrs), Wed 8–5 (9hrs), Thu 8–6:30 (10.5hrs), Fri balance (7.5hrs). Schedule is stable week-to-week; changes are lasting, not one-offs. Any hours beyond scheduled end times are overtime ("babysitting 🐣") requiring explicit ask. |
| Baby | Toddler (18mo) | Swim Tue 11am (30min). Forest school Thu 9–10:30am. Nap ~1–3:30/4pm daily. Bed 7:30pm. Wake 6:30–7am. |
| Buddy | Dog (3yo) | 4 walks/day. A walks at 6:30am. Dog walker Tue–Thu (30min midday). J confirmed for 10pm walk every night. |

> **Note:** These are placeholder names. The system prompt uses template variables (`{primary}`, `{pa}`, `{partner}`, `{ra}`, etc.) that are filled from `config.yaml` at runtime — so the schedule output always uses your actual household names.

---

## Fixed Weekly Schedule

### Monday
- S: 9–6pm (9hrs)
- J: leaves 7:15am, home ~5pm, **in charge of dinner**
- A: office, gym (lift) after work — ETA home based on last meeting + gym time

### Tuesday
- S: 8–5pm (9hrs)
- Baby: swim 11am (30min)
- J: pool league — sometimes straight from school, sometimes home first
- A: office, **chicken dinner** ("Chicken Tuesday")
- Dog walker: midday walk

### Wednesday
- S: 8–5pm (9hrs)
- Cleaner: every other Wednesday morning (assume coming unless told otherwise)
- A: office
- Dog walker: midday walk
- Dinner: negotiable (assigned by generator)

### Thursday
- S: 8–6:30pm (10.5hrs)
- Baby: forest school 9–10:30am
- J: pool league straight from school
- A: office
- Dog walker: midday walk
- Dinner: negotiable (assigned by generator)

### Friday
- S: balance of 45hr week (7.5hrs, flex start/end)
- **A home all day (no office)**
- A: gym in the morning if no early meetings; S starting early helps
- Dinner: negotiable

### Saturday
- A: grocery shopping at grocery store; gym
- A: coop shift every 6th Saturday
- J: squash (if weekend day selected) — check shared GCal
- No S unless paid overtime (flagged explicitly)

### Sunday
- J: squash (if weekend day selected) — check shared GCal
- J: coop shift every 6 Sundays
- If J has coop shift, J does grocery shopping
- Schedule generated and sent to WhatsApp group
- No S unless paid overtime

---

## Dog Walk Schedule

| Walk | Time | Who |
|------|------|-----|
| Morning (long) | ~6:30am | A (back before J leaves at 7:15am) |
| Midday | Tue–Thu | Dog walker (30min) |
| Evening | 5–7pm | Whoever is home |
| Night | ~10pm | J (every night, no exceptions) |

On Mon, Fri, Sat, Sun — midday walk must be manually assigned (no dog walker).

---

## Dinner Assignment Rules

| Day | Assignee |
|-----|----------|
| Monday | J (fixed) |
| Tuesday | A — chicken (fixed) |
| Wed–Sun | Generator assigns A or J based on who is home/available |

- If one parent has an evening event, the other cooks
- If both are out (date night), no cook assigned — note the plan
- Only mark "TBD" if genuinely not enough info

---

## Family Dinner

One night per week, A, J, and S eat together at home. Also serves as the A+S weekly check-in.

- Eligible days: Mon–Thu or Sunday
- Never Friday or Saturday
- Placed on the night where A and J are both home earliest with no evening conflicts

---

## Work Calendar Intelligence

The generator analyzes the primary scheduler's work calendar to compute:

- **Last meeting end time** per day → ETA home (departure + 45min buffer). Does not leave before 5:30pm unless told to hustle.
- **Late start detection**: If first meeting is 10am+, can **gym before work** (1hr gym + commute to office)
- **Gym after work ETA**: Last meeting + 20min to gym + 60min gym + 20min home
- **Friday morning gym**: Home all day; feasible if no early remote meetings. Au pair starting early helps.

Filtered from work calendar: "ask before scheduling" blocks (commute/family holds), birthdays, therapy appointments.

---

## Gym Scheduling

| Slot | Timing | Notes |
|------|--------|-------|
| Monday (fixed) | After work | Lift. ETA home = last meeting + 1hr40min |
| Midweek (1-2x) | Before work (late start days) or after work | Run or lift. Generator picks best days from work calendar. |
| Friday | Morning | If no early meetings. Au pair starting early helps. |
| Weekend (2x) | Flexible | Lift 1 day, run/gym 1 day |

**Hard rule: one workout per day.** If gym-before-work is scheduled, do not also schedule gym-after-work that same day.

---

## Validation Criteria ("Good Schedule")

1. **Child coverage:** An adult (A, J, or S) responsible at every waking hour. No gaps at handoffs.
2. **Handoff validation:** For each weekday, cross-check S's end time vs A's ETA. If A arrives after S leaves, J must stay until A is home. If J is also out (e.g., pool straight from school), flag the gap and suggest S overtime or A hustling.
3. **Scheduling conflicts:** A person can only be in one place at a time. If a calendar event conflicts with a fixed commitment, flag it and suggest rescheduling.
4. **Babysitting arrival:** When both parents leave for an event, S arrives 45 minutes before event start time (travel baked in).
5. **Dog's 4 walks:** Assigned daily. J owns 10pm every night.
6. **Dinner assigned:** All dinners Mon–Sun have a named cook before A shops Sat/Sun.
7. **A's commute:** A can get to office Mon–Thu. Late departures flagged against work calendar.
8. **S's hours:** Base schedule = 45hrs/week. Overtime = "babysitting 🐣", explicitly flagged.
9. **No unsupervised gaps:** Especially at S start/end and A/J transitions.
10. **Family dinner:** Placed once/week on an eligible night (Mon–Thu or Sun). Not eligible if A has late meetings (home after 7pm) or evening events.

---

## Output Format

Sent to the family WhatsApp group. Primary scheduler pins it each week.

**All formats start with a "Quick notes before the week" summary section** — 2-4 bullet points with key context (coop status, meal plan changes, follow-ups, Open Brain highlights) before the daily breakdown. This gives the family context at a glance.

**Configurable via `config.yaml` → `schedule_output.format`**. Three options:

### `bullets` (default — current preference)
"Quick notes" summary, then day headers with bullet points. Each bullet is one fact. Blank lines between days for readability. Easiest to scan on a phone.
```
**Quick notes before the week:**
– J caught up on coop shifts — no nudge needed 👍
– Chicken moved to Sunday this week — Tuesday is leftovers

---

Mon:
• S: 9-6
• A gym after work 🏋️, home ~7:15
• J dinner
```

### `person`
Grouped by person (A, J, Baby, S). Each person's week summarized in 2-4 lines. Dinners on one line. Best for "what's my week look like?"

### `grid`
Compact text table with columns: day, S hours, dinner, notes. Most information-dense but depends on phone font width.

**Shared style rules (all formats):**
- Use A, J, S abbreviations throughout
- Emojis: 🏊 swim, 🎱 pool, 🌳 forest school, 🏋️ gym, 🐔 chicken, 🧹 cleaner, ‼️ urgent, 🛒 coop, 🐣 babysitting, 🍽️👨‍👩‍👦 family dinner
- Babysitting asks: `@Sam` with 🐣 inline
- Short flags section at end only if there are open questions
- Casual, warm tone — group text from a competent parent, not a corporate memo

---

## Inputs to the Generator

### Pulled automatically
- Google Calendar: personal, shared family, and work calendars
- Open Brain MCP: recent thoughts (last 7 days) + semantic search for upcoming week content (meal plans, events, travel, schedule changes)
- Fixed recurring rules from config.yaml (au pair hours, children's classes, dog walker, cleaner cadence, coop shifts)
- Work calendar analysis (last meeting times, late starts, gym windows)

### Filtered out automatically
- Birthdays, therapy appointments, "ask before scheduling" blocks

### Prompted via Saturday alerts (Phase 2)
- Primary scheduler: finalize dinner assignments for Wed–Sun
- WhatsApp group: "Any events or schedule changes?"
- Au pair: "Any babysitting or schedule conflicts next week?"

### Included in every schedule
- Coop backlog reminder (if configured)

---

## Automation Phases

### Phase 1 — MVP (AI-Assisted) ← CURRENT
- Local Python script on macOS
- macOS launchd trigger at **Sunday 1pm** (toddler nap time)
- Pulls GCal events, analyzes work calendar, prompts for notes
- Claude API (claude-sonnet-4-6) generates schedule with gym suggestions
- Output copied to clipboard; paste into WhatsApp and pin
- All secrets in `.env`, household config in `config.yaml`

### Phase 2 — Semi-Automated
- Move cron to **GitHub Actions** (no Mac dependency)
- Saturday alerts via WhatsApp (Green API)
- Sunday draft auto-generated and delivered for approval

### Phase 3 — Fully Automated
- One-tap approval via WhatsApp reply
- Auto-send and auto-pin to family chat

---

## Integrations

| Integration | Purpose | Status |
|-------------|---------|--------|
| Google Calendar API | Personal + family + work calendars | ✅ Connected |
| Claude API | Schedule generation (claude-sonnet-4-6) | ✅ Connected |
| Open Brain MCP | Auto-pull notes (meal plans, events, schedule changes) | ✅ Connected via StreamableHTTP |
| WhatsApp (Green API) | Send to family chat | Phase 2 |
| macOS launchd | Sunday 1pm trigger | ✅ Configured |
| GitHub Actions | Phase 2 cron replacement | Phase 2 |

---

## Testing Checklist

- [x] Script runs end-to-end with GCal + Claude API
- [x] Alternating cleaner Wednesday logic correct
- [x] Coop shift cadence calculation correct
- [x] Au pair hours compute to 45hrs/week (37.5 Mon-Thu + 7.5 Fri)
- [x] Work calendar "ask before scheduling" blocks filtered
- [x] Birthdays and therapy appointments filtered
- [x] Late-start days detected for gym-before-work
- [x] Gym after work ETAs computed correctly
- [x] Friday morning gym suggested when feasible
- [x] Family dinner placed Mon-Thu or Sunday, never Fri/Sat
- [x] Dinner assigned to A or J (not left as TBD when avoidable)
- [x] Babysitting/overtime flagged as 🐣 with @Sam ask
- [x] Coop backlog reminder included
- [x] Output uses A/J/S abbreviations
- [x] Open Brain MCP integration pulls recent thoughts and semantic search
- [x] Open Brain notes deduplicated and meta/technical notes filtered out
- [x] Handoff validation: S end time vs A ETA cross-checked per weekday
- [x] Scheduling conflict detection (no double-booking)
- [x] Babysitting arrival rule (45min before event, travel baked in)
- [x] J pool Tuesday: explicit departure time tied to A's ETA
- [x] Family dinner ineligible when A has late meetings (home after 7pm)
- [x] S's Friday hours calculated correctly (8-3:30 = 7.5hrs, not 8-1:30)
- [x] One workout per day max — no double gym sessions
- [x] "Quick notes before the week" summary section in all output formats
- [x] Template-based name replacement (no fragile regex on single letters)
- [x] GCal auto-reauth when refresh token expires (no manual `rm token.json`)
- [ ] Tighten Claude output to suppress reasoning/deliberation in schedule text
- [ ] Test with different weeks to verify edge cases
- [ ] Validate against example schedules in `docs/example_schedules`
- [ ] Set up work calendar sharing if using a separate work Google account
- [ ] Install launchd plist and test Sunday auto-trigger

---

## Open Questions

- [ ] **WhatsApp API (Phase 2):** Green API account setup needed
- [ ] **Work calendar access:** If using a separate work Google account, share the work calendar with your personal Gmail
- [ ] **Claude output quality:** Schedule sometimes includes reasoning/deliberation text — needs stronger suppression in system prompt
