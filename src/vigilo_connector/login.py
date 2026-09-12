"""Interaktiv OAuth-innlogging: `vigilo-login`.

Redirect-URI-en er appens custom scheme, så nettleseren ender på en
«ukjent protokoll»-feil med koden i adresselinjen — det er suksess-tilfellet.
Lim hele den feilede URL-en (eller bare code-verdien) inn her.

NB: Har du Vigilo-appen installert på maskinen du logger inn fra, kan OS-et
gi redirecten til den, som da bruker opp engangskoden. Logg inn fra en maskin
uten appen, eller bruk DevTools → Network med «Preserve log» for å se den
feilede app://-requesten.
"""

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


def main() -> None:
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

    tokens = auth.exchange_code(code)
    store = auth.TokenStore()
    store.save(tokens)
    print(f"\nTokens lagret i {store.path}")

    # Røyktest: verifiser at tokenet virker mot API-et.
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


if __name__ == "__main__":
    main()
