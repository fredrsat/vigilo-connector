"""OAuth2 mot Vigilos auth-server.

Flyten er authorization code + PKCE mot appens registrerte client. Redirecten
går til et custom app-scheme som nettlesere ikke kan følge, så koden må
copy-pastes fra den feilede adressen (se README og `login.py`).

Refresh-tokens roterer ved bruk og utløper etter 30-90 dager; da må
`vigilo-login` kjøres på nytt.
"""

import base64
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .config import AUTH_BASE, REDIRECT_URI, SCOPE, TOKEN_FILE, load_client_credentials, write_json_atomic

# Forny access-token når det er mindre enn dette igjen av levetiden.
EXPIRY_MARGIN = 60


class AuthError(RuntimeError):
    pass


def _basic_auth() -> str:
    client_id, client_secret = load_client_credentials()
    if not client_id or not client_secret:
        raise AuthError(
            "Mangler client-credentials. Sett VIGILO_CLIENT_ID/VIGILO_CLIENT_SECRET "
            "eller legg dem i ~/.config/vigilo-connector/config.json (se README)."
        )
    return base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


def authorize_url(state: str) -> str:
    # Appen bruker en konfidensiell client (Basic-auth med secret) UTEN PKCE —
    # bekreftet i APK-en (AuthApi.requestTokens sender kun code/redirect_uri/
    # grant_type). Sender vi code_challenge/code_verifier her, avviser serveren
    # kodebyttet med invalid_grant.
    client_id, _ = load_client_credentials()
    if not client_id:
        raise AuthError(
            "Mangler client_id. Sett VIGILO_CLIENT_ID/VIGILO_CLIENT_SECRET "
            "eller legg dem i ~/.config/vigilo-connector/config.json (se README)."
        )
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTH_BASE}/connect/authorize?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    r = httpx.post(
        f"{AUTH_BASE}/connect/token",
        headers={"Authorization": f"Basic {_basic_auth()}"},
        data=data,
        timeout=30,
    )
    if r.status_code in (400, 401):
        raise AuthError(f"Token-kall avvist ({r.status_code}): {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def exchange_code(code: str) -> dict:
    # Kun code/redirect_uri/grant_type — client-auth ligger i Basic-headeren.
    return _token_request(
        {"code": code, "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"}
    )


def code_from_cookies(cookie_header: str) -> str:
    """Hent en fersk authorization-code ved å gjøre authorize-kallet selv med en
    aktiv ID-porten-sesjon (cookies fra en innlogget nettleser).

    Dette er headless-veien: nettleserens redirect til `app://` er usynlig, men
    med sesjonscookiene kan vi be om authorize og lese `code` rett ut av
    302-redirectens Location-header. Krever ingen DevTools-jakt på koden.
    """
    state = secrets.token_urlsafe(16)
    r = httpx.get(
        authorize_url(state),
        headers={"cookie": cookie_header, "user-agent": "Mozilla/5.0"},
        follow_redirects=False,
        timeout=30,
    )
    loc = r.headers.get("location", "")
    if not loc:
        raise AuthError(
            f"Authorize ga ingen redirect (HTTP {r.status_code}). Er cookiene "
            "gyldige/ferske? Logg inn i nettleseren på nytt og kopier cURL igjen."
        )
    params = parse_qs(urlsplit(loc).query)
    if params.get("state", [None])[0] not in (None, state):
        raise AuthError("state i redirecten matcher ikke — prøv på nytt.")
    code = params.get("code", [None])[0]
    if not code:
        raise AuthError(f"Fant ingen code i redirecten. Location: {loc[:200]}")
    return code


def refresh(refresh_token: str) -> dict:
    return _token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"})


def user_id_from_jwt(access_token: str) -> str:
    payload = access_token.split(".")[1]
    payload += "==" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


class TokenStore:
    """Persistert tokenpar med automatisk fornyelse."""

    def __init__(self, path=TOKEN_FILE):
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            raise AuthError(f"Ingen tokens i {self.path} — kjør `vigilo-login` først.")
        return json.loads(self.path.read_text())

    def save(self, tokens: dict) -> None:
        tokens = dict(tokens)
        tokens["obtained_at"] = time.time()
        write_json_atomic(self.path, tokens)

    def access_token(self, force_refresh: bool = False) -> str:
        tokens = self.load()
        expires_at = tokens.get("obtained_at", 0) + tokens.get("expires_in", 0)
        if force_refresh or time.time() > expires_at - EXPIRY_MARGIN:
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise AuthError("Mangler refresh-token — kjør `vigilo-login` på nytt.")
            new_tokens = refresh(refresh_token)
            tokens.update(new_tokens)
            self.save(tokens)
        return tokens["access_token"]
