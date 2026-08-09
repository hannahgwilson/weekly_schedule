/* Demo shim — makes the unmodified front-end run with no backend.
 *
 * The app in weekly_schedule/templates/index.html talks to the FastAPI server
 * exclusively over fetch('/api/...'). This intercepts those calls and answers
 * them from an in-memory copy of demo/demo_data.py (injected below as DEMO),
 * so the page can be served as a static file from GitHub Pages.
 *
 * Everything the user changes — config, work schedules, people, pets, dinner —
 * mutates the in-memory state and is reflected back, exactly as the real API
 * would. It resets on reload; nothing leaves the browser.
 *
 * _extractFlags is a deliberate port of web.py::_extract_flags rather than a
 * hardcoded list, so the flag chips in the demo are derived the same way the
 * live app derives them.
 */
(function () {
  'use strict';

  const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

  // Mutable session state, seeded from the fixtures.
  const state = {
    settings: structuredClone(DEMO.settings),
    calendars: structuredClone(DEMO.calendars),
    work: structuredClone(DEMO.work_schedules),
    people: structuredClone(DEMO.people),
    pets: structuredClone(DEMO.pets),
    dinner: structuredClone(DEMO.dinner),
  };

  /* ---------- helpers ---------- */

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function nextMonday(from) {
    const d = from ? new Date(from + 'T00:00:00') : new Date();
    const shift = (8 - d.getDay()) % 7 || 7;   // always the *next* Monday
    d.setDate(d.getDate() + shift);
    return d;
  }

  function iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
      + '-' + String(d.getDate()).padStart(2, '0');
  }

  function parseWeek(s) {
    if (!s) return nextMonday();
    const d = new Date(s + 'T00:00:00');
    if (isNaN(d)) return nextMonday();
    // Snap to that week's Monday, like _parse_week + next_monday do server-side.
    const back = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - back);
    return d;
  }

  // "09:30" -> "9:30am", matching strftime('%-I:%M%p').lower()
  function pretty(hhmm) {
    if (!hhmm) return null;
    const [h, m] = hhmm.split(':').map(Number);
    const ap = h >= 12 ? 'pm' : 'am';
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}:${String(m).padStart(2, '0')}${ap}`;
  }

  // Port of web.py::_extract_flags — same markers, keywords, dedupe and cap.
  const FLAG_MARKERS = ['‼', '⚠', '\u{1F423}'];
  const FLAG_KEYWORDS = ['coverage gap', 'overtime', 'behind', 'conflict', 'double-book', 'no coverage'];

  function _extractFlags(schedule) {
    const flags = [];
    const seen = new Set();
    for (const raw of schedule.split('\n')) {
      const line = raw.trim();
      if (!line) continue;
      const low = line.toLowerCase();
      const hit = FLAG_MARKERS.some(m => line.includes(m))
        || FLAG_KEYWORDS.some(k => low.includes(k));
      if (!hit) continue;
      const clean = line.replace(/^[-*•‣◦\s]+/, '').trim();
      const key = clean.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      flags.push(clean);
      if (flags.length >= 8) break;
    }
    return flags;
  }

  // Mirrors db._PEOPLE_ORDER — the API returns people in role order, then name.
  const PEOPLE_ORDER = { primary_scheduler: 0, partner: 1, au_pair: 2, child: 3 };

  function sortPeople(people) {
    return people.slice().sort((a, b) =>
      (PEOPLE_ORDER[a.role] ?? 99) - (PEOPLE_ORDER[b.role] ?? 99)
      || (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase()));
  }

  function householdPayload() {
    return {
      people: state.people,
      pets: state.pets,
      dinner: state.dinner,
      members: state.people.filter(p => p.role !== 'child')
        .map(p => ({ contact_id: p.contact_id, name: p.name })),
    };
  }

  function householdSummary() {
    const byRole = r => state.people.filter(p => p.role === r);
    const adults = {};
    byRole('primary_scheduler').concat(byRole('partner'), byRole('au_pair'))
      .forEach(p => { adults[p.name] = p.role.replace(/_/g, ' '); });
    const children = {};
    byRole('child').forEach(p => { children[p.name] = ''; });
    const pets = {};
    state.pets.forEach(p => { pets[p.name] = p.species || ''; });
    return { adults, children, pets, dinner_defaults: {}, dinner_negotiable: [] };
  }

  function calendarPayload(monday) {
    const days = DAYS.map((name, i) => {
      const date = new Date(monday);
      date.setDate(date.getDate() + i);
      // All-day first, then timed chronologically — sorted on the raw 24-hour
      // value, matching web.py::_calendar_payload.
      const events = DEMO.events.filter(e => e.day === i)
        .sort((a, b) => (a.all_day ? 0 : 1) - (b.all_day ? 0 : 1)
          || String(a.start || '').localeCompare(String(b.start || '')))
        .map(e => ({
          summary: e.summary,
          all_day: !!e.all_day,
          start: e.all_day ? null : pretty(e.start),
          end: e.all_day ? null : pretty(e.end),
          calendar: e.calendar,
          link: null,                   // deep-links are disabled in the demo
        }));
      return {
        name,
        label: name[0].toUpperCase() + name.slice(1),
        date: iso(date),
        display: date.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' }),
        events,
      };
    });
    const end = new Date(monday);
    end.setDate(end.getDate() + 6);
    return { week: iso(monday), week_end: iso(end), days, configured: true };
  }

  function historyPayload(monday) {
    return {
      runs: DEMO.history.map(h => {
        const w = new Date(monday);
        w.setDate(w.getDate() - 7 * h.weeks_ago);
        const created = new Date(w);
        created.setDate(created.getDate() - 2);
        return {
          week: iso(w),
          format: h.format,
          schedule: h.schedule,
          flags: _extractFlags(h.schedule),
          created_at: iso(created) + h.created_offset,
        };
      }),
    };
  }

  let newId = 0;
  const nextId = () => `demo-new-${++newId}`;

  /* ---------- routes ---------- */

  const routes = {
    'GET /api/config': () => ({
      settings: state.settings,
      calendars: state.calendars,
      household: householdSummary(),
    }),

    'POST /api/config': body => {
      if ('work_calendar' in body) state.calendars.work = (body.work_calendar || '').trim();
      if (body.format) state.settings.format = body.format;
      if (body.group_name !== undefined) state.settings.group_name = body.group_name;
      if (body.emoji_map) state.settings.emoji_map = body.emoji_map;
      if (body.excluded_events !== undefined) {
        state.settings.excluded_events = typeof body.excluded_events === 'string'
          ? body.excluded_events.split('\n').map(s => s.trim()).filter(Boolean)
          : body.excluded_events;
      }
      return { settings: state.settings, calendars: state.calendars };
    },

    'GET /api/events': (_body, params) => calendarPayload(parseWeek(params.get('week'))),

    'POST /api/generate': async body => {
      await sleep(1500);                       // stand in for the live Claude call
      const fmt = body.format || state.settings.format || 'bullets';
      const schedule = DEMO.schedules[fmt] || DEMO.schedules.bullets;
      return {
        week: iso(parseWeek(body.week)),
        format: fmt,
        schedule,
        flags: _extractFlags(schedule),
      };
    },

    'POST /api/capture': async body => {
      await sleep(500);
      const blocks = (body.notes || '').trim().split('\n\n').map(s => s.trim()).filter(Boolean);
      return { captured: blocks.map(b => 'Captured: ' + b.slice(0, 60)) };
    },

    'POST /api/process-entities': async () => {
      await sleep(700);
      return { result: { processed: 3, entities_created: 5, edges_created: 4 } };
    },

    'GET /api/work-schedules': () => ({ adults: state.work }),

    'POST /api/work-schedules': async body => {
      await sleep(400);
      (body.adults || []).forEach(patch => {
        const cur = state.work.find(a => a.contact_id === patch.contact_id);
        if (!cur) return;
        cur.schedule_stability_notes = patch.schedule_stability_notes;
        if (cur.role === 'au_pair') {
          cur.weekly_hours_target = patch.weekly_hours_target === ''
            ? null : Number(patch.weekly_hours_target);
          cur.caregiver_hours = patch.caregiver_hours;
        } else {
          cur.work_days = patch.work_days;
          cur.work_start = patch.work_start || null;
          cur.work_end = patch.work_end || null;
          cur.commute_minutes = patch.commute_minutes === ''
            ? null : Number(patch.commute_minutes);
          cur.leaves_home = patch.leaves_home || null;
          cur.returns_home = patch.returns_home || null;
        }
      });
      return { adults: state.work };
    },

    'GET /api/household': () => householdPayload(),

    'POST /api/household/people': async body => {
      await sleep(400);
      // Reconcile like db.save_household_people: omitted rows are removed.
      state.people = sortPeople((body.people || []).map(p => ({
        contact_id: p.contact_id || nextId(),
        name: p.name,
        role: p.role,
        birth_date: p.birth_date,
      })));
      const kept = new Set(state.people.map(p => p.contact_id));
      state.work = state.work.filter(a => kept.has(a.contact_id));
      Object.values(state.dinner).forEach(d => {
        if (d.cook_id && !kept.has(d.cook_id)) d.cook_id = null;
      });
      return householdPayload();
    },

    'POST /api/household/pets': async body => {
      await sleep(400);
      state.pets = (body.pets || []).map(p => ({
        id: p.id || nextId(),
        name: p.name,
        species: p.species,
        breed: p.breed,
        walks_per_day: p.walks_per_day === '' ? null : Number(p.walks_per_day),
        notes: p.notes,
      }));
      return householdPayload();
    },

    'POST /api/household/dinner': async body => {
      await sleep(400);
      (body.dinner || []).forEach(d => {
        state.dinner[d.day] = { cook_id: d.cook_id, dish_notes: d.dish_notes };
      });
      return householdPayload();
    },

    'GET /api/history': () => historyPayload(parseWeek(document.querySelector('#week').value)),
  };

  /* ---------- install ---------- */

  const realFetch = window.fetch.bind(window);

  window.fetch = async function (url, opts = {}) {
    const href = String(url);
    if (!href.startsWith('/api/')) return realFetch(url, opts);

    const method = (opts.method || 'GET').toUpperCase();
    const [path, query] = href.split('?');
    const params = new URLSearchParams(query || '');
    const handler = routes[`${method} ${path}`];

    if (!handler) {
      return new Response(JSON.stringify({ error: `No demo route for ${method} ${path}` }),
        { status: 404, headers: { 'Content-Type': 'application/json' } });
    }

    let body = {};
    if (opts.body) { try { body = JSON.parse(opts.body); } catch { body = {}; } }

    try {
      const data = await handler(body, params);
      return new Response(JSON.stringify(data),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err && err.message || err) }),
        { status: 500, headers: { 'Content-Type': 'application/json' } });
    }
  };

  // Keep the week picker on the upcoming Monday so the demo never looks stale.
  // This script is injected after the topbar, so the input already exists.
  const picker = document.querySelector('#week');
  if (picker) picker.value = iso(nextMonday());
})();
