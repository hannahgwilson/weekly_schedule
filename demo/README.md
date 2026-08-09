# Public demo

A static, backend-free build of the web app for the portfolio Pages site, published at
<https://hannahgwilson.github.io/portfolio/weekly-schedule/>.

```bash
python demo/build_demo.py     # writes demo/dist/
open demo/dist/index.html
```

Two pages:

| File | What it is |
|---|---|
| `dist/index.html` | Case study — the problem, the pipeline, the three design decisions, the stack |
| `dist/app.html` | The app itself, running against fixtures instead of a backend |

## How the app demo works

`build_demo.py` renders the **live** app template — `weekly_schedule/templates/index.html`, not a
copy — through Jinja, then splices in `demo_shim.js`, which replaces `window.fetch` and answers
every `/api/*` call from `demo_data.py`.

That means the demo cannot silently drift from the real UI: it is built from whatever is currently
in `templates/`. The trade-off is that it depends on a handful of string anchors in that template
(the `<title>`, the brand tag, the sidebar footer, the run-view opening tag, the app `<script>`
tag). **If you edit those lines, the build fails loudly** with the anchor it could not find —
update `build_demo.py` to match rather than working around it.

Rebuild and commit `dist/` after any change to the app template, since the Pages workflow serves
the built files.

## Fidelity rules

The shim mirrors the real API rather than faking a happy path — it ports `_extract_flags` from
[`web.py`](../weekly_schedule/web.py) so the flag chips are derived the same way, sorts calendar
events and people with the same keys the backend uses, and reconciles people/pet saves (omitted
rows are deleted) like `db.save_household_*` does. When the backend's behaviour changes, change
the shim with it; a demo that behaves better than the app is a lie.

Two deliberate divergences, both stated on the page itself:

- **`POST /api/generate` replays a canned schedule** instead of calling Claude. A static page
  cannot hold an API key, and one that could would be a key any visitor could spend.
- **Calendar deep-links are `null`**, so events render without the `↗` affordance rather than
  linking to a Google Calendar entry that does not exist.

## The data is fictional

Everything in `demo_data.py` is invented: the household, the employer, the calendars, the
generated weeks. No real household data is published. Keep it that way — if you refresh the demo
week, write a new fictional one rather than scrubbing a real run.
