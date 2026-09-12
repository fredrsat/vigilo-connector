"""MCP-server: `vigilo-mcp`.

Eksponerer Vigilos foreldre-API som verktøy for agenten. `api_get` er
kartleggingsverktøyet: rått GET mot vilkårlig sti bak gatewayen, så nye
endepunkter kan utforskes rett fra agenten før de blir egne verktøy.
"""

import json

from mcp.server.mcpserver import MCPServer

from .client import VigiloClient

mcp = MCPServer("vigilo")
_client: VigiloClient | None = None


def client() -> VigiloClient:
    global _client
    if _client is None:
        _client = VigiloClient()
    return _client


@mcp.tool()
def list_children() -> str:
    """List barna knyttet til den innloggede foresatte, med childId."""
    return json.dumps(client().get_children(), ensure_ascii=False, indent=2)


@mcp.tool()
def list_message_threads(child_id: str, page_size: int = 50) -> str:
    """List beskjedtråder for et barn (bruk childId fra list_children).

    Returnerer tråder med threadUid, tittel, avsender og tidspunkt.
    """
    return json.dumps(
        client().get_message_threads(child_id, page_size), ensure_ascii=False, indent=2
    )


@mcp.tool()
def get_message_thread(thread_uid: str) -> str:
    """Hent alle meldingene i en tråd, inkl. vedleggs-URL-er."""
    return json.dumps(client().get_thread(thread_uid), ensure_ascii=False, indent=2)


@mcp.tool()
def read_message_attachments(thread_uid: str) -> str:
    """Last ned og les vedleggene i en meldingstråd (f.eks. ukeplan-PDF).

    Returnerer utdratt tekst per vedlegg. Bruk dette når en melding har vedlegg
    (hasAttachments/attachments) og du trenger innholdet — typisk ukeplanen med
    lekser, turer og «ta med»-beskjeder som ofte legges ved som PDF.
    """
    return json.dumps(
        client().read_thread_attachments(thread_uid), ensure_ascii=False, indent=2
    )


@mcp.tool()
def api_get(path: str, params_json: str = "{}") -> str:
    """Rått GET mot foreldre-API-et — for kartlegging av nye endepunkter.

    path: f.eks. "/api/children". params_json: query-parametre som JSON-objekt;
    userId legges til automatisk om den ikke er satt. Returnerer status og body
    uansett utfall, så 404/400 også gir informasjon.
    """
    params = json.loads(params_json)
    params.setdefault("userId", client().user_id)
    r = client().get(path, params=params)
    body = r.text
    try:
        body = json.dumps(r.json(), ensure_ascii=False, indent=2)
    except ValueError:
        pass
    return f"HTTP {r.status_code}\n{body[:20000]}"


# --- Web-foreldreportal -------------------------------------------------
# Timeplan, fravær, samtykke, nyheter m.m. som ikke finnes i app-gatewayen.
# childId og organizationalUnitId hentes fra web_list_children.


@mcp.tool()
def web_list_children() -> str:
    """List barna med childId og organizationalUnitId (flatet ut).

    organizationalUnitId (skole/klasse) trengs til timeplan, samtykke og
    vurdering; childId brukes overalt. Gir også skole- og gruppenavn.
    """
    return json.dumps(client().children(), ensure_ascii=False, indent=2)


@mcp.tool()
def news_feed(child_id: str, from_date: str = "", to_date: str = "") -> str:
    """Oppslag/«Siste nytt» for et barn. Datoer YYYY-MM-DD (default: siste 30 dager)."""
    return json.dumps(
        client().news_feed(child_id, from_date or None, to_date or None),
        ensure_ascii=False, indent=2,
    )


@mcp.tool()
def absences(child_id: str) -> str:
    """Fravær for et barn."""
    return json.dumps(client().absences(child_id), ensure_ascii=False, indent=2)


@mcp.tool()
def consent_forms(child_id: str, organizational_unit_id: str) -> str:
    """Samtykkeskjemaer for et barn (krever organizationalUnitId)."""
    return json.dumps(
        client().consent_forms(child_id, organizational_unit_id), ensure_ascii=False, indent=2
    )


@mcp.tool()
def timetable(child_id: str, organizational_unit_id: str, week: str = "") -> str:
    """Timeplan/ukesplan for en ISO-uke ("YYYY-WW", default inneværende uke)."""
    return json.dumps(
        client().lessons(child_id, organizational_unit_id, week or None),
        ensure_ascii=False, indent=2,
    )


@mcp.tool()
def scheduling_events(child_id: str, organizational_unit_id: str, week: str = "") -> str:
    """Timeplan-hendelser (prøver, aktiviteter) for en ISO-uke ("YYYY-WW")."""
    return json.dumps(
        client().scheduling_events(child_id, organizational_unit_id, week or None),
        ensure_ascii=False, indent=2,
    )


@mcp.tool()
def web_api_get(path: str, params_json: str = "{}") -> str:
    """Rått GET mot web-foreldreportalen — for kartlegging av nye web-endepunkter.

    path: f.eks. "/api/absences". params_json: query-parametre som JSON-objekt.
    Ingen userId legges til (web-API-et bruker childIds/organizationalUnitId).
    Returnerer status og body uansett utfall.
    """
    r = client().web_get(path, params=json.loads(params_json))
    body = r.text
    try:
        body = json.dumps(r.json(), ensure_ascii=False, indent=2)
    except ValueError:
        pass
    return f"HTTP {r.status_code}\n{body[:20000]}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
