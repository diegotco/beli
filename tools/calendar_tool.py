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


def delete_calendar_event(
    credentials_json: str,
    event_title: str,
    start_date: str = "",
) -> str:
    """
    Deletes a calendar event by title (and optionally by date to disambiguate).

    Args:
        credentials_json: JSON string with OAuth credentials
        event_title:      Title of the event to delete (case-insensitive partial match)
        start_date:       Optional date filter 'YYYY-MM-DD' to narrow search
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google Calendar."

    try:
        service = _get_service(credentials_json)

        # Search within a wide window (next 90 days + past 7 days)
        from datetime import timezone as _tz
        now     = datetime.now(tz=_tz.utc)
        time_min = (now - timedelta(days=7)).isoformat()
        time_max = (now + timedelta(days=90)).isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        title_lower = event_title.lower()

        matches = [
            ev for ev in events
            if title_lower in ev.get("summary", "").lower()
            and (not start_date or ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")).startswith(start_date))
        ]

        if not matches:
            return f"No encontré ningún evento que contenga '{event_title}'" + (f" el {start_date}" if start_date else "") + "."

        if len(matches) > 1:
            lines = [f"- {ev.get('summary')} ({ev.get('start',{}).get('dateTime', ev.get('start',{}).get('date',''))[:16]})" for ev in matches]
            return "Encontré varios eventos con ese nombre:\n" + "\n".join(lines) + "\nIndica la fecha exacta para eliminar el correcto."

        ev = matches[0]
        event_id = ev["id"]
        ev_title = ev.get("summary", event_title)
        ev_start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))[:16]

        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"[Calendar] Event deleted: {ev_title} ({ev_start})")
        return f"Evento '{ev_title}' del {ev_start} eliminado correctamente."

    except Exception as e:
        logger.exception(f"[Calendar] Error deleting event: {e}")
        return f"Error al eliminar el evento: {e}"


def update_calendar_event(
    credentials_json: str,
    event_title: str,
    new_start_datetime: str = "",
    new_end_datetime: str = "",
    new_title: str = "",
    new_description: str = "",
    start_date: str = "",
    timezone: str = "America/Mexico_City",
) -> str:
    """
    Updates an existing calendar event (reschedule, rename, or change description).

    Args:
        credentials_json:   JSON string with OAuth credentials
        event_title:        Current title to find the event (partial, case-insensitive)
        new_start_datetime: New start in ISO 8601 format (optional)
        new_end_datetime:   New end in ISO 8601 format (optional)
        new_title:          New title if renaming (optional)
        new_description:    New description (optional)
        start_date:         'YYYY-MM-DD' filter to disambiguate when multiple events match
        timezone:           IANA timezone for the event times
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google Calendar."

    try:
        service = _get_service(credentials_json)

        from datetime import timezone as _tz
        now      = datetime.now(tz=_tz.utc)
        time_min = (now - timedelta(days=7)).isoformat()
        time_max = (now + timedelta(days=90)).isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        title_lower = event_title.lower()

        matches = [
            ev for ev in events
            if title_lower in ev.get("summary", "").lower()
            and (not start_date or ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")).startswith(start_date))
        ]

        if not matches:
            return f"No encontré ningún evento que contenga '{event_title}'" + (f" el {start_date}" if start_date else "") + "."

        if len(matches) > 1:
            lines = [f"- {ev.get('summary')} ({ev.get('start',{}).get('dateTime', ev.get('start',{}).get('date',''))[:16]})" for ev in matches]
            return "Encontré varios eventos con ese nombre:\n" + "\n".join(lines) + "\nIndica la fecha exacta para actualizar el correcto."

        ev = matches[0]
        event_id = ev["id"]

        if new_title:
            ev["summary"] = new_title
        if new_description:
            ev["description"] = new_description
        if new_start_datetime:
            ev["start"] = {"dateTime": new_start_datetime, "timeZone": timezone}
        if new_end_datetime:
            ev["end"] = {"dateTime": new_end_datetime, "timeZone": timezone}

        updated = service.events().update(calendarId="primary", eventId=event_id, body=ev).execute()
        new_start = updated.get("start", {}).get("dateTime", updated.get("start", {}).get("date", ""))[:16]
        logger.info(f"[Calendar] Event updated: {updated.get('summary')} → {new_start}")
        return f"Evento '{updated.get('summary')}' actualizado. Nueva fecha/hora: {new_start}."

    except Exception as e:
        logger.exception(f"[Calendar] Error updating event: {e}")
        return f"Error al actualizar el evento: {e}"
