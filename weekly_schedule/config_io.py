"""Round-trip read/write of the app-behavior settings in config.yaml.

Only the ``schedule_output`` block is editable from the UI (emoji map, default
output format, group name, excluded-event regexes). Household / recurring /
dinner data lives in Supabase and is not touched here. Uses ruamel.yaml so the
file's comments and formatting survive a save.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't re-wrap long unrelated lines (e.g. household notes)
_yaml.allow_unicode = True  # keep emoji as literal glyphs, not \U escapes
_yaml.indent(mapping=2, sequence=4, offset=2)

VALID_FORMATS = ("bullets", "person", "grid")


def read_settings() -> dict:
    """Return the editable schedule_output settings as plain Python types."""
    with open(CONFIG_PATH) as f:
        cfg = _yaml.load(f) or {}
    out = cfg.get("schedule_output", {}) or {}
    return {
        "format": out.get("format", "bullets"),
        "group_name": out.get("group_name", ""),
        "pin": bool(out.get("pin", False)),
        "excluded_events": list(out.get("excluded_events", []) or []),
        "emoji_map": dict(out.get("emoji_map", {}) or {}),
    }


def read_calendars() -> dict:
    """Return the editable calendar IDs (currently just the work calendar)."""
    with open(CONFIG_PATH) as f:
        cfg = _yaml.load(f) or {}
    cals = cfg.get("calendars", {}) or {}
    return {"work": str(cals.get("work", "") or "")}


def update_work_calendar(work: str) -> dict:
    """Set the work-calendar Google Calendar ID (empty string = none). Returns calendars."""
    with open(CONFIG_PATH) as f:
        cfg = _yaml.load(f) or {}
    cals = cfg.setdefault("calendars", {})
    cals["work"] = (work or "").strip()

    with open(CONFIG_PATH, "w") as f:
        _yaml.dump(cfg, f)

    return read_calendars()


def update_settings(
    *,
    format: str | None = None,
    group_name: str | None = None,
    emoji_map: dict | None = None,
    excluded_events: list[str] | None = None,
) -> dict:
    """Patch the schedule_output block in place and write it back.

    Raises ValueError on an invalid format. Returns the new settings.
    """
    if format is not None and format not in VALID_FORMATS:
        raise ValueError(f"format must be one of {VALID_FORMATS}, got {format!r}")

    with open(CONFIG_PATH) as f:
        cfg = _yaml.load(f) or {}
    out = cfg.setdefault("schedule_output", {})

    if format is not None:
        out["format"] = format
    if group_name is not None:
        out["group_name"] = group_name
    if excluded_events is not None:
        out["excluded_events"] = [p for p in excluded_events if p.strip()]
    if emoji_map is not None:
        out["emoji_map"] = {k: v for k, v in emoji_map.items() if k.strip() and v.strip()}

    with open(CONFIG_PATH, "w") as f:
        _yaml.dump(cfg, f)

    return read_settings()
