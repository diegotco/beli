"""
setup_google_calendar.py - One-time OAuth flow to get Google Calendar credentials.

Run this ONCE locally:
  python setup_google_calendar.py

It will open a browser, ask you to log in with your Google account,
and then print a JSON string. Copy that string into the Railway env var:
  GOOGLE_CALENDAR_CREDENTIALS=<paste here>

Requirements:
  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""
import json
import os
from pathlib import Path


CLIENT_SECRETS_FILE = "google_client_secret.json"


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/calendar"]

    if not Path(CLIENT_SECRETS_FILE).exists():
        print(f"""
ERROR: No se encontró '{CLIENT_SECRETS_FILE}'.

Pasos para obtenerlo:
  1. Ve a https://console.cloud.google.com
  2. Selecciona tu proyecto y ve a APIs & Services → Credentials
  3. En tu OAuth 2.0 Client ID, haz clic en el ícono de descarga
  4. Guarda el archivo como '{CLIENT_SECRETS_FILE}' en esta carpeta
  5. Vuelve a ejecutar este script
""")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes)
    creds = flow.run_local_server(port=0)

    creds_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes),
    }

    creds_json = json.dumps(creds_data)

    print("\n" + "=" * 60)
    print("✅ Autenticación exitosa.")
    print("=" * 60)
    print("\nCopia el siguiente valor en Railway como variable de entorno:")
    print("  Nombre:  GOOGLE_CALENDAR_CREDENTIALS")
    print("  Valor:   (ver abajo)")
    print("\n" + creds_json)
    print("\n" + "=" * 60)

    # Also save locally for testing
    out = Path("data/google_calendar_credentials.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(creds_json, encoding="utf-8")
    print(f"\nTambién guardado en: {out}")


if __name__ == "__main__":
    main()
