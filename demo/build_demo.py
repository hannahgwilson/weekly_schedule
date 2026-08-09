#!/usr/bin/env python
"""Build the static, backend-free demo of the weekly-schedule web app.

Renders the *live* app template (weekly_schedule/templates/index.html) with
Jinja, then splices in a fetch shim that answers every /api/* call from the
fictional fixtures in demo_data.py. The result is a single self-contained HTML
file that can be served from GitHub Pages.

The app template is never forked — this reads whatever is currently in
templates/ — so the demo cannot silently drift from the real UI. If an
injection anchor disappears because the template changed, the build fails
loudly rather than shipping a half-wired page.

    python demo/build_demo.py

Outputs:
    demo/dist/index.html   case study (the page a reader lands on)
    demo/dist/app.html     the interactive demo
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
DIST = DEMO / "dist"

sys.path.insert(0, str(DEMO))
import demo_data as D  # noqa: E402

APP_TEMPLATE = ROOT / "weekly_schedule" / "templates" / "index.html"
SHIM = DEMO / "demo_shim.js"
CASE_STUDY = DEMO / "templates" / "case_study.html"

# Served as <portfolio>/weekly-schedule/{index,app}.html, so from app.html the
# case study is "./" (this directory's index) and the portfolio root is "../".
CASE_STUDY_URL = "./"
PORTFOLIO_HOME = "../"
REPO_URL = "https://github.com/hannahgwilson/weekly_schedule"


def _replace_once(html: str, anchor: str, replacement: str, what: str) -> str:
    """Splice `replacement` in for `anchor`, asserting the anchor is unique."""
    count = html.count(anchor)
    if count != 1:
        raise SystemExit(
            f"Demo build failed: expected exactly 1 occurrence of the {what} anchor "
            f"in {APP_TEMPLATE.relative_to(ROOT)}, found {count}.\n"
            f"  anchor: {anchor[:90]}\n"
            f"The app template changed — update demo/build_demo.py to match."
        )
    return html.replace(anchor, replacement)


# --------------------------------------------------------------------------
# Injected chrome: styles, the demo banner, the sidebar footer.
# --------------------------------------------------------------------------
DEMO_STYLES = """
    /* ---- Demo-only chrome (injected by demo/build_demo.py) ---- */
    .demo-note {
      background: linear-gradient(180deg, #f4f7f1, #fbfaf6);
      border: 1px solid #cfd9c8;
    }
    .demo-note h2 { display: flex; align-items: center; gap: .5rem; }
    .demo-note .badge {
      font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
      background: var(--sage); color: #fff; padding: .15rem .45rem; border-radius: 4px;
    }
    .demo-note ul { margin: .6rem 0 0; padding-left: 1.15rem; color: var(--muted); font-size: .86rem; }
    .demo-note li { margin: .25rem 0; }
    .demo-note li strong { color: var(--ink); font-weight: 600; }
    .demo-note .backlink { display: inline-block; margin-top: .9rem; font-size: .86rem; }
    .brand .tag.demo { color: var(--clay); font-weight: 600; }
    .sidebar .foot a { color: var(--sage-deep); }
"""

DEMO_TAG = '<p class="tag demo">Demo · fictional data</p>'

DEMO_FOOT = f"""<div class="foot">
        <a href="{PORTFOLIO_HOME}">← Back to portfolio</a><br>
        <a href="{REPO_URL}">Source on GitHub</a>
      </div>"""

DEMO_NOTE = f"""
          <div class="panel demo-note">
            <h2><span class="badge">Demo</span> This is the real app, on an invented household</h2>
            <p class="desc">
              Same front-end and the same code paths as the version that runs at home — but with no
              backend behind it, so it can live on a static site.
            </p>
            <ul>
              <li><strong>The household is fictional.</strong> Priya, Dan, Inês and the kids do not
                  exist. No real calendar, no real family data.</li>
              <li><strong>Run schedule</strong> plays back a schedule the live pipeline produced for
                  this fictional week, instead of calling Claude. The warning chips above it are
                  scraped from that text by the same flag-extraction code the real app uses.</li>
              <li><strong>Everything else is live.</strong> Edit the config, work schedules, people,
                  pets and dinner rota and the UI behaves exactly as it does against Supabase —
                  changes are held in the browser and reset on reload.</li>
            </ul>
            <a class="backlink" href="{CASE_STUDY_URL}">← How it works, and why it is built this way</a>
          </div>"""


def build_app() -> str:
    """Render the live app template and wire it to the demo fixtures."""
    raw = APP_TEMPLATE.read_text()

    html = Template(raw).render(
        week="",                       # the shim sets this to the upcoming Monday
        formats=["bullets", "person", "grid"],
        history_enabled=True,
    )

    fixtures = {
        "settings": D.SETTINGS,
        "calendars": D.CALENDARS,
        "work_schedules": D.WORK_SCHEDULES,
        "people": D.PEOPLE,
        "pets": D.PETS,
        "dinner": D.DINNER,
        "events": D.EVENTS,
        "schedules": D.SCHEDULES,
        "history": D.HISTORY,
    }

    html = _replace_once(html, "<title>Weekly Schedule</title>",
                         "<title>Weekly Schedule — demo</title>\n"
                         '  <meta name="robots" content="noindex, nofollow">',
                         "title")
    html = _replace_once(html, "  </style>", DEMO_STYLES + "  </style>", "stylesheet close")
    html = _replace_once(html, '<p class="tag">Household schedule</p>', DEMO_TAG, "brand tag")
    html = _replace_once(html, '<div class="foot">Family chat<br>Mon–Sun planning</div>',
                         DEMO_FOOT, "sidebar footer")
    html = _replace_once(html, '<section class="view active" id="view-run">',
                         '<section class="view active" id="view-run">' + DEMO_NOTE,
                         "run view opening")

    shim = (
        "<script>\n"
        "  const DEMO = " + json.dumps(fixtures, ensure_ascii=False) + ";\n"
        "</script>\n"
        "  <script>\n" + SHIM.read_text() + "  </script>\n\n  "
    )
    html = _replace_once(html, "<script>\n    const $ = (s, r=document)",
                         shim + "<script>\n    const $ = (s, r=document)",
                         "app script opening")
    return html


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    (DIST / "app.html").write_text(build_app())
    shutil.copyfile(CASE_STUDY, DIST / "index.html")

    for f in sorted(DIST.iterdir()):
        print(f"  {f.relative_to(ROOT)}  {f.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
