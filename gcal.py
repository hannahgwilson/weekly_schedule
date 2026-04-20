"""Google Calendar integration for the weekly schedule generator."""

from __future__ import annotations

import os
import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = Path(__file__).parent / "token.json"


def _run_oauth_flow():
    """Run the full OAuth browser flow to get new credentials."""
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if not Path(creds_path).exists():
        raise FileNotFoundError(
            f"Google credentials file not found at '{creds_path}'.\n"
            "Download it from Google Cloud Console > APIs & Services > Credentials.\n"
            "See README.md for setup instructions."
        )
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    return flow.run_local_server(port=0)


def get_credentials():
    """Get or refresh Google OAuth credentials.

    Handles expired tokens by refreshing automatically. If the refresh token
    itself is revoked or invalid, deletes the stale token and re-authenticates
    via browser.
    """
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                print(f"  Token refresh failed ({exc}). Re-authenticating...")
                TOKEN_PATH.unlink(missing_ok=True)
                creds = _run_oauth_flow()
        else:
            creds = _run_oauth_flow()

        TOKEN_PATH.write_text(creds.to_json())

    return creds


def fetch_events(calendar_id: str, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
    """Fetch events from a single calendar for the given time range."""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for event in events_result.get("items", []):
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        end_raw = event["end"].get("dateTime", event["end"].get("date"))
        events.append({
            "summary": event.get("summary", "(no title)"),
            "start": start_raw,
            "end": end_raw,
            "all_day": "date" in event["start"],
            "calendar": calendar_id,
        })

    return events


def fetch_week_events(calendar_ids: dict[str, str], week_start: datetime.date) -> dict[str, list[dict]]:
    """Fetch events for a Mon-Sun week from all configured calendars.

    Args:
        calendar_ids: Mapping of label to calendar ID, e.g. {"personal": "...", "family": "...", "work": "..."}
        week_start: The Monday of the target week.

    Returns:
        Dict mapping day name (e.g. "monday") to list of events on that day.
    """
    start_dt = datetime.datetime.combine(week_start, datetime.time.min)
    end_dt = datetime.datetime.combine(week_start + datetime.timedelta(days=7), datetime.time.min)

    all_events = []
    for label, cal_id in calendar_ids.items():
        if not cal_id:
            continue
        try:
            events = fetch_events(cal_id, start_dt, end_dt)
            for e in events:
                e["calendar_label"] = label
            all_events.extend(events)
        except Exception as exc:
            print(f"  Warning: Could not fetch '{label}' calendar ({cal_id}): {exc}")

    # Group by day of week
    by_day = {d: [] for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]}
    for event in all_events:
        raw = event["start"]
        if "T" in raw:
            dt = datetime.datetime.fromisoformat(raw)
        else:
            dt = datetime.datetime.strptime(raw, "%Y-%m-%d")
        day_name = dt.strftime("%A").lower()
        if day_name in by_day:
            by_day[day_name].append(event)

    return by_day
