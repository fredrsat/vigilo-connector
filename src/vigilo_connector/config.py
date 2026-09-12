"""Konfigurasjon og filplasseringer.

Client-ID/secret er Vigilos egne Android-app-credentials og må hentes ut av
APK-en (se README). De leses fra miljøvariabler eller fra config-fila, og skal
aldri sjekkes inn.
"""

import json
import os
from pathlib import Path

AUTH_BASE = "https://auth.prod.vigilo-oas.no"
API_BASE = "https://api-gw-parent-app.prod.vigilo-oas.no"
# Web-foreldreportalen har eget API-domene. Samme OAuth-issuer som app-en, og
# API-et er Bearer-basert (ikke cookie-sesjon) — så app-tokenet *kan* fungere
# her; må bekreftes mot et ekte token. Dekker timeplan/fravær/samtykke/vurdering
# som ikke finnes i app-gatewayen.
WEB_API_BASE = "https://web-parent.prod.vigilo-oas.no"
APP_VERSION = "Android 3.1.4-15"
REDIRECT_URI = os.environ.get("VIGILO_REDIRECT_URI", "app://ch-parent-android.vigilo.no")
SCOPE = "openid vigiloprofile offline_access"

CONFIG_DIR = Path(
    os.environ.get("VIGILO_CONFIG_DIR", Path.home() / ".config" / "vigilo-connector")
)
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = CONFIG_DIR / "tokens.json"


def load_client_credentials() -> tuple[str, str]:
    """Miljøvariabler vinner; ellers config.json med {"client_id", "client_secret"}."""
    client_id = os.environ.get("VIGILO_CLIENT_ID", "")
    client_secret = os.environ.get("VIGILO_CLIENT_SECRET", "")
    if client_id and client_secret:
        return client_id, client_secret
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        return cfg.get("client_id", ""), cfg.get("client_secret", "")
    return client_id, client_secret


def write_json_atomic(path: Path, payload) -> None:
    """Skriv via tempfil + rename, så en avbrutt skriving aldri korrumperer tokens."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
    path.chmod(0o600)
