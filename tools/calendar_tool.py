"""
tools/calendar_tool.py - Google Calendar integration for Beli.

Uses the Google Calendar API with OAuth 2.0 credentials.
Credentials are stored as a JSON string in the GOOGLE_CALENDAR_CREDENTIALS env var.
The refresh token is obtained once via setup_google_calendar.py.
"""
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("beli.tools.calendar")

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service(credentials_json: str):
    """Builds and returns an authenticated Google Calendar service."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds_data = json.loads(credentials_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        scopes=creds_data.get("scopes", _SCOPES),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("calendar", "v3", credentials=creds)


def read_calendar_events(
    credentials_json: str,
    days_ahead: int = 7,
    max_results: int = 20,
    timezone: str = "America/Mexico_City",
) -> str:
    """
    Returns upcoming calendar events for the next N days.

    Args:
        credentials_json: JSON string with OAuth credentials
        days_ahead:       How many days to look ahead (default: 7)
        max_results:      Max number of events to return (default: 20)
        timezone:         IANA timezone for display
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google Calendar (GOOGLE_CALENDAR_CREDENTIALS)."

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone)
    except Exception:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/Mexico_City")

    try:
        service = _get_service(credentials_json)

        now    = datetime.now(tz=tz)
        end    = now + timedelta(days=days_ahead)
        now_iso = now.isoformat()
        end_iso = end.isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=now_iso,
            timeMax=end_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])

        if not events:
            return f"No tienes eventos en los próximos {days_ahead} días."

        lines = []
        for ev in events:
            title    = ev.get("summary", "(sin título)")
            location = ev.get("location", "")
            start    = ev.get("start", {})
            end_ev   = ev.get("end", {})

            # All-day events use "date"; timed events use "dateTime"
            if "dateTime" in start:
                dt_start = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
                dt_end   = datetime.fromisoformat(end_ev["dateTime"]).astimezone(tz)
                time_str = f"{dt_start.strftime('%a %d %b, %H:%M')} – {dt_end.strftime('%H:%M')}"
            else:
                date_str = start.get("date", "")
                time_str = f"{date_str} (todo el día)"

            line = f"- {time_str}: {title}"
            if location:
                line += f" @ {location}"
            lines.append(line)

        return f"Tus próximos {len(lines)} eventos ({days_ahead} días):\n\n" + "\n".join(lines)

    except Exception as e:
        logger.exception(f"[Calendar] Error reading events: {e}")
        return f"Error al leer el calendario: {e}"


def create_calendar_event(
    credentials_json: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    timezone: str = "America/Mexico_City",
) -> str:
    """
    Creates a new event in the owner's primary Google Calendar.

    Args:
        credentials_json: JSON string with OAuth credentials
        title:            Event title
        start_datetime:   ISO 8601 string (e.g. '2026-05-20T10:00:00')
        end_datetime:     ISO 8601 string (e.g. '2026-05-20T11:00:00')
        description:      Optional event description
        location:         Optional location
        timezone:         IANA timezone for the event
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google Calendar."

    try:
        service = _get_service(credentials_json)

        event_body = {
            "summary": title,
            "start":   {"dateTime": start_datetime, "timeZone": timezone},
            "end":     {"dateTime": end_datetime,   "timeZone": timezone},
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location

        created = service.events().insert(calendarId="primary", body=event_body).execute()
        link = created.get("htmlLink", "")
        logger.info(f"[Calendar] Event created: {title} ({start_datetime})")
        return f"Evento '{title}' creado el {start_datetime[:10]} a las {start_datetime[11:16]}." + (f" Ver: {link}" if link else "")

    except Exception as e:
        logger.exception(f"[Calendar] Error creating event: {e}")
        return f"Error al crear el evento: {e}"
