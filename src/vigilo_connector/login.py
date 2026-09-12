"""Interaktiv OAuth-innlogging: `vigilo-login`.

To moduser:

* Standard (`vigilo-login`): skriver ut en autoriserings-URL du åpner i en
  nettleser. Redirect-URI-en er appens custom scheme, så nettleseren ender på en
  «ukjent protokoll»-feil med koden i adresselinjen — det er suksess-tilfellet.
  Lim hele den feilede URL-en (eller bare code-verdien) inn her.

* cURL (`vigilo-login --from-curl`): for headless-maskiner. Logg inn i en
  desktop-nettleser, åpne DevTools → Network, naviger til autoriserings-URL-en,
  høyreklikk `authorize`-requesten → «Copy as cURL», og lim inn her. Verktøyet
  henter sesjonscookiene ut av cURL-en, gjør authorize-kallet selv og fanger
  koden fra redirecten — ingen jakt på `app://`-adressen.

NB: Har du Vigilo-appen installert på maskinen du logger inn fra, kan OS-et gi
redirecten til den, som da bruker opp engangskoden. Logg inn fra en maskin uten
appen.
"""

import re
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

from . import auth
from .client import VigiloClient


def parse_code_input(raw: str, expected_state: str) -> str:
    """Godta enten en hel redirect-URL eller en bar code-verdi."""
    raw = raw.strip()
    if "code=" not in raw:
        return raw
    # app://host?code=... — urlsplit takler custom schemes fint.
    query = urlsplit(raw).query or raw.split("?", 1)[-1]
    params = parse_qs(query)
    state = params.get("state", [None])[0]
    if state and state != expected_state:
        sys.exit("state i redirecten matcher ikke denne innloggingen — start på nytt.")
    code = params.get("code", [None])[0]
    if not code:
        sys.exit("Fant ingen code i det du limte inn.")
    return code


def cookies_from_curl(text: str) -> str:
    """Trekk cookie-strengen ut av en «Copy as cURL»-tekst.

    Chrome bruker `-b '...'` / `--cookie '...'`; Firefox legger cookies i en
    `-H 'Cookie: ...'`-header. Vi støtter begge.
    """
    # -b '...' eller --cookie '...'/"..."
    m = re.search(r"(?:-b|--cookie)\s+(['\"])(.*?)\1", text, re.DOTALL)
    if m:
        return m.group(2).strip()
    # -H 'cookie: ...'
    m = re.search(r"-H\s+(['\"])\s*cookie:\s*(.*?)\1", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(2).strip()
    sys.exit(
        "Fant ingen cookies i cURL-en (verken -b/--cookie eller en Cookie-header). "
        "Kopierte du hele 'Copy as cURL' for authorize-requesten?"
    )


def _finish(code: str) -> None:
    """Bytt code mot tokens, lagre, og røyktest."""
    try:
        tokens = auth.exchange_code(code)
    except auth.AuthError as e:
        sys.exit(str(e))
    store = auth.TokenStore()
    store.save(tokens)
    print(f"\nTokens lagret i {store.path}")

    client = VigiloClient(store)
    try:
        children = client.get_children()
    except Exception as e:
        print(f"Innlogget, men røyktesten mot /api/children feilet: {e}")
        return
    finally:
        client.close()
    names = [
        f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or str(c.get("childId"))
        for c in children
    ]
    print(f"Innlogging OK — fant {len(children)} barn: {', '.join(names)}")


def _from_curl() -> None:
    try:
        auth.authorize_url("probe")  # tidlig feil hvis client_id mangler
    except auth.AuthError as e:
        sys.exit(str(e))
    print(
        "Logg inn hos Vigilo i en desktop-nettleser, åpne DevTools → Network,\n"
        "naviger til denne URL-en, høyreklikk 'authorize'-requesten → Copy as cURL:\n"
    )
    print(f"  {auth.authorize_url(secrets.token_urlsafe(16))}\n")
    print("Lim inn hele cURL-en under og avslutt med Ctrl-D:\n")
    curl = sys.stdin.read()
    cookie_header = cookies_from_curl(curl)
    code = auth.code_from_cookies(cookie_header)
    _finish(code)


def _interactive() -> None:
    state = secrets.token_urlsafe(16)
    try:
        url = auth.authorize_url(state)
    except auth.AuthError as e:
        sys.exit(str(e))

    print("Åpne denne URL-en i en nettleser og logg inn:\n")
    print(f"  {url}\n")
    print(
        "Når nettleseren feiler på en app://-adresse: kopier hele adressen\n"
        "(eller bare code-verdien) og lim inn her.\n"
    )
    raw = input("Redirect-URL eller code: ")
    code = parse_code_input(raw, state)
    _finish(code)


def main() -> None:
    if "--from-curl" in sys.argv[1:]:
        _from_curl()
    else:
        _interactive()


if __name__ == "__main__":
    main()
