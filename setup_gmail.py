"""
setup_gmail.py - One-time OAuth flow to get Gmail credentials for Beli.

Run this ONCE locally:
  python setup_gmail.py

It will open a browser, ask you to log in with your Google account,
and then print a JSON string. Copy that string into the Railway env var:
  GMAIL_CREDENTIALS=<paste here>

Also save it locally in your .env file for testing:
  GMAIL_CREDENTIALS=<paste here>

Requirements:
  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client

Note: The same google_client_secret.json used for Calendar also works here.
"""
import json
from pathlib import Path

CLIENT_SECRETS_FILE = "google_client_secret.json"


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    if not Path(CLIENT_SECRETS_FILE).exists():
        print(f"""
ERROR: No se encontró '{CLIENT_SECRETS_FILE}'.

Es el mismo archivo que usaste para Calendar. Pasos:
  1. Ve a https://console.cloud.google.com
  2. Selecciona tu proyecto → APIs & Services → Credentials
  3. En tu OAuth 2.0 Client ID, haz clic en el ícono de descarga
  4. Guarda el archivo como '{CLIENT_SECRETS_FILE}' en esta carpeta
  5. Vuelve a ejecutar este script
""")
        return

    # Verify Gmail API is enabled in the Google Cloud project
    print("\nAsegúrate de haber habilitado la Gmail API en tu proyecto de Google Cloud.")
    print("  https://console.cloud.google.com/apis/library/gmail.googleapis.com\n")

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
    print("✅ Autenticación de Gmail exitosa.")
    print("=" * 60)
    print("\nCopia el siguiente valor en Railway como variable de entorno:")
    print("  Nombre:  GMAIL_CREDENTIALS")
    print("  Valor:   (ver abajo)\n")
    print(creds_json)
    print("\n" + "=" * 60)

    # Save locally for testing
    out = Path("data/gmail_credentials.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(creds_json, encoding="utf-8")
    print(f"\nTambién guardado en: {out}")
    print("\nAhora añade esta línea a tu archivo .env:")
    print(f"GMAIL_CREDENTIALS={creds_json}")


if __name__ == "__main__":
    main()
