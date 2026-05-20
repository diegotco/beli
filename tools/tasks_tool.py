"""
tools/tasks_tool.py - Google Tasks integration for Beli.

Uses the Google Tasks API with OAuth 2.0 credentials.
Credentials are shared with Google Calendar (GOOGLE_CALENDAR_CREDENTIALS env var).
The refresh token is obtained via setup_google_calendar.py (which includes the Tasks scope).
"""
import json
import logging

logger = logging.getLogger("beli.tools.tasks")

_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def _get_service(credentials_json: str):
    """Builds and returns an authenticated Google Tasks service."""
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

    return build("tasks", "v1", credentials=creds)


def list_task_lists(credentials_json: str) -> str:
    """
    Returns a formatted string listing all task lists with their IDs.

    Args:
        credentials_json: JSON string with OAuth credentials
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google."

    try:
        service = _get_service(credentials_json)
        result = service.tasklists().list().execute()
        items = result.get("items", [])

        if not items:
            return "No tienes listas de tareas."

        lines = ["Tus listas de tareas:"]
        for item in items:
            title = item.get("title", "(sin título)")
            list_id = item.get("id", "")
            lines.append(f"• {title} (id: {list_id})")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"[Tasks] Error listing task lists: {e}")
        return f"Error al obtener las listas de tareas: {e}"


def find_list_id_by_name(credentials_json: str, name_keyword: str) -> str | None:
    """
    Finds a task list ID by searching for a keyword in the list title.
    Returns the list ID or None if not found.
    """
    if not credentials_json:
        return None
    try:
        service = _get_service(credentials_json)
        result = service.tasklists().list().execute()
        items = result.get("items", [])
        keyword = name_keyword.lower()
        for item in items:
            if keyword in item.get("title", "").lower():
                return item.get("id")
        return None
    except Exception as e:
        logger.warning(f"[Tasks] Could not find list by name '{name_keyword}': {e}")
        return None


def list_tasks(
    credentials_json: str,
    list_id: str = "@default",
    show_completed: bool = False,
) -> str:
    """
    Returns tasks in a list.

    Args:
        credentials_json: JSON string with OAuth credentials
        list_id:          Task list ID or "@default"
        show_completed:   If True, also include completed tasks
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google."

    try:
        service = _get_service(credentials_json)

        # Get the list title
        if list_id == "@default":
            lists_result = service.tasklists().list().execute()
            lists = lists_result.get("items", [])
            list_title = lists[0].get("title", "Default") if lists else "Default"
        else:
            try:
                tl = service.tasklists().get(tasklist=list_id).execute()
                list_title = tl.get("title", list_id)
            except Exception:
                list_title = list_id

        # Fetch tasks
        kwargs = {
            "tasklist": list_id,
            "showHidden": show_completed,
            "showCompleted": show_completed,
        }
        result = service.tasks().list(**kwargs).execute()
        tasks = result.get("items", [])

        if not tasks:
            return f"No hay tareas en la lista '{list_title}'."

        lines = [f"Lista: {list_title}"]
        for task in tasks:
            status = task.get("status", "needsAction")
            title = task.get("title", "(sin título)")
            due = task.get("due", "")
            notes = task.get("notes", "")

            if status == "completed":
                checkbox = "☑"
            else:
                checkbox = "☐"

            line = f"{checkbox} {title}"
            if due:
                # due is RFC 3339 format; extract date portion
                due_date = due[:10]
                line += f" (vence: {due_date})"
            if notes:
                line += f"\n   ↳ {notes}"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"[Tasks] Error listing tasks: {e}")
        return f"Error al obtener las tareas: {e}"


def create_task(
    credentials_json: str,
    title: str,
    list_id: str = "@default",
    notes: str = "",
    due_date: str = "",
) -> str:
    """
    Creates a new task.

    Args:
        credentials_json: JSON string with OAuth credentials
        title:            Task title
        list_id:          Task list ID or "@default"
        notes:            Optional task notes
        due_date:         Optional due date in YYYY-MM-DD format
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google."

    try:
        service = _get_service(credentials_json)

        task_body = {"title": title, "status": "needsAction"}
        if notes:
            task_body["notes"] = notes
        if due_date:
            # Google Tasks API expects RFC 3339 format with time set to midnight UTC
            task_body["due"] = f"{due_date}T00:00:00.000Z"

        created = service.tasks().insert(tasklist=list_id, body=task_body).execute()
        created_title = created.get("title", title)
        logger.info(f"[Tasks] Task created: {created_title}")

        msg = f"Tarea '{created_title}' creada."
        if due_date:
            msg += f" Vence el {due_date}."
        return msg

    except Exception as e:
        logger.exception(f"[Tasks] Error creating task: {e}")
        return f"Error al crear la tarea: {e}"


def _find_task(service, list_id: str, task_title_or_id: str):
    """
    Finds a task by ID (exact) or title (case-insensitive substring match).
    Returns the task dict or None.
    """
    # Try by ID first
    try:
        task = service.tasks().get(tasklist=list_id, task=task_title_or_id).execute()
        return task
    except Exception:
        pass

    # Fall back to title search
    result = service.tasks().list(tasklist=list_id, showHidden=True, showCompleted=True).execute()
    tasks = result.get("items", [])
    query = task_title_or_id.lower()
    for task in tasks:
        if query in task.get("title", "").lower():
            return task

    return None


def complete_task(
    credentials_json: str,
    task_title_or_id: str,
    list_id: str = "@default",
) -> str:
    """
    Marks a task as completed, found by title (case-insensitive substring) or ID.

    Args:
        credentials_json:  JSON string with OAuth credentials
        task_title_or_id:  Task title substring or exact task ID
        list_id:           Task list ID or "@default"
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google."

    try:
        service = _get_service(credentials_json)
        task = _find_task(service, list_id, task_title_or_id)

        if task is None:
            return f"No se encontró la tarea '{task_title_or_id}'."

        task_id = task["id"]
        title = task.get("title", task_id)

        if task.get("status") == "completed":
            return f"La tarea '{title}' ya estaba completada."

        updated_body = {"id": task_id, "status": "completed"}
        service.tasks().update(tasklist=list_id, task=task_id, body=updated_body).execute()
        logger.info(f"[Tasks] Task completed: {title}")
        return f"Tarea '{title}' marcada como completada. ✓"

    except Exception as e:
        logger.exception(f"[Tasks] Error completing task: {e}")
        return f"Error al completar la tarea: {e}"


def delete_task(
    credentials_json: str,
    task_title_or_id: str,
    list_id: str = "@default",
) -> str:
    """
    Deletes a task, found by title (case-insensitive substring) or ID.

    Args:
        credentials_json:  JSON string with OAuth credentials
        task_title_or_id:  Task title substring or exact task ID
        list_id:           Task list ID or "@default"
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Google."

    try:
        service = _get_service(credentials_json)
        task = _find_task(service, list_id, task_title_or_id)

        if task is None:
            return f"No se encontró la tarea '{task_title_or_id}'."

        task_id = task["id"]
        title = task.get("title", task_id)

        service.tasks().delete(tasklist=list_id, task=task_id).execute()
        logger.info(f"[Tasks] Task deleted: {title}")
        return f"Tarea '{title}' eliminada."

    except Exception as e:
        logger.exception(f"[Tasks] Error deleting task: {e}")
        return f"Error al eliminar la tarea: {e}"
