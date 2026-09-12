"""HTTP-klient mot Vigilos foreldre-API.

Endepunktene under `# Kjente endepunkter` er verifisert via
https://github.com/brujoand/vigilo2smtp. Nye endepunkter (ukesplan, nyheter,
fravær) legges til her etter hvert som de kartlegges — bruk `get()` /
MCP-verktøyet `api_get` til å utforske.
"""

import io
from datetime import date, timedelta

import httpx

from .auth import AuthError, TokenStore, user_id_from_jwt
from .config import API_BASE, APP_VERSION, WEB_API_BASE


def iso_week(d: date | None = None) -> str:
    """ISO-uke på formatet Vigilo bruker, f.eks. "2026-38"."""
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-{w:02d}"


def _pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(p for p in parts if p).strip()


class VigiloClient:
    def __init__(self, store: TokenStore | None = None):
        self._store = store or TokenStore()
        self._http = httpx.Client(base_url=API_BASE, timeout=30)
        self._web = httpx.Client(base_url=WEB_API_BASE, timeout=30)

    def _headers(self, force_refresh: bool = False) -> dict:
        return {
            "Authorization": f"Bearer {self._store.access_token(force_refresh)}",
            "appVersion": APP_VERSION,
        }

    def _web_headers(self, force_refresh: bool = False) -> dict:
        # Web-API-et fester bare Authorization-header; ingen appVersion/userId.
        return {"Authorization": f"Bearer {self._store.access_token(force_refresh)}"}

    @property
    def user_id(self) -> str:
        return user_id_from_jwt(self._store.access_token())

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Rått GET-kall med auth og retry ved 401. Brukes også til kartlegging."""
        r = self._http.get(path, params=params, headers=self._headers())
        if r.status_code == 401:
            r = self._http.get(path, params=params, headers=self._headers(force_refresh=True))
        return r

    def get_json(self, path: str, params: dict | None = None):
        r = self.get(path, params=params)
        if r.status_code == 401:
            raise AuthError("Fortsatt 401 etter token-fornyelse — kjør `vigilo-login` på nytt.")
        r.raise_for_status()
        return r.json()

    def web_get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Rått GET mot web-foreldreportalen med auth og retry ved 401."""
        r = self._web.get(path, params=params, headers=self._web_headers())
        if r.status_code == 401:
            r = self._web.get(path, params=params, headers=self._web_headers(force_refresh=True))
        return r

    def web_get_json(self, path: str, params: dict | None = None):
        r = self.web_get(path, params=params)
        if r.status_code == 401:
            raise AuthError(
                "401 fra web-API-et. Enten er tokenet utløpt (kjør `vigilo-login`), "
                "eller så aksepterer ikke web-API-et app-tokenet — se README."
            )
        r.raise_for_status()
        return r.json()

    # --- Kjente endepunkter ---------------------------------------------

    def get_children(self) -> list:
        data = self.get_json("/api/children", params={"userId": self.user_id})
        return data if isinstance(data, list) else data.get("items", [])

    def get_message_threads(
        self, child_id: str, page_size: int = 50, include_after_school: bool = True
    ) -> list:
        data = self.get_json(
            "/api/message-threads",
            params={
                "userId": self.user_id,
                "childIds": child_id,
                "pageSize": page_size,
                "unreadMessageThreadsCountOnly": "false",
                "includeAfterSchoolMessages": str(include_after_school).lower(),
            },
        )
        return data.get("messageThreads", [])

    def get_thread(self, thread_uid: str, page_size: int = 50) -> dict:
        return self.get_json(
            f"/api/messages/threads/{thread_uid}",
            params={"userId": self.user_id, "pageSize": page_size},
        )

    # --- Web-foreldreportal ---------------------------------------------
    # Endepunkter kartlagt fra web-portalen (web-parent.prod.vigilo-oas.no),
    # 2026-09-12. Dekker det app-gatewayen mangler: timeplan, fravær,
    # samtykke, vurdering, nyheter. Alle bruker childId (=personId) og de
    # fleste også organizationalUnitId (skole/klasse) — begge kommer fra
    # web_children(). `week` er ISO-format "YYYY-WW" (se iso_week()).

    def web_children(self) -> list:
        """Barn fra web-portalen (rå). Hvert barn har `id` + `organizationalUnits`."""
        data = self.web_get_json("/api/children/my")
        return data if isinstance(data, list) else data.get("items", data.get("children", []))

    def children(self) -> list:
        """Barn flatet ut til det verktøyene trenger: childId + organizationalUnitId.

        Web-API-et gir childId som `id` og skolen/klassen i `organizationalUnits`.
        Returnerer f.eks. {childId, firstName, lastName, organizationalUnitId,
        school, group}. Bruk denne som inngang til timeplan/fravær/samtykke.
        """
        out = []
        for c in self.web_children():
            units = c.get("organizationalUnits") or []
            unit = units[0] if units else {}
            groups = unit.get("groups") or []
            out.append(
                {
                    "childId": c.get("id") or c.get("childId"),
                    "firstName": c.get("firstName"),
                    "lastName": c.get("lastName"),
                    "organizationalUnitId": unit.get("id"),
                    "school": unit.get("name"),
                    "group": groups[0].get("name") if groups else None,
                }
            )
        return out

    def web_current_user(self) -> dict:
        return self.web_get_json("/api/current-user")

    def news_feed(self, child_id: str, from_date: str | None = None, to_date: str | None = None) -> list:
        """Oppslag/«Siste nytt» for et barn. Datoer på formatet YYYY-MM-DD."""
        from_date = from_date or (date.today() - timedelta(days=30)).isoformat()
        to_date = to_date or (date.today() + timedelta(days=1)).isoformat()
        data = self.web_get_json(
            "/api/news-feed",
            params={"childIds": child_id, "fromDate": from_date, "toDate": to_date},
        )
        return data if isinstance(data, list) else data.get("items", [])

    def web_message_threads(
        self, child_id: str, from_date: str | None = None, to_date: str | None = None
    ) -> list:
        """Beskjedtråder via web-portalen (parallell til app-ens get_message_threads)."""
        from_date = from_date or (date.today() - timedelta(days=30)).isoformat()
        to_date = to_date or (date.today() + timedelta(days=1)).isoformat()
        return self.web_get_json(
            "/api/message-threads",
            params={
                "childIds": child_id,
                "fromDate": from_date,
                "toDate": to_date,
                "includeAfterSchoolMessages": "false",
            },
        )

    def absences(self, child_id: str, include_after_school: bool = False) -> list:
        """Fravær for et barn."""
        return self.web_get_json(
            "/api/absences",
            params={
                "childIds": child_id,
                "includeAfterSchoolAbsences": str(include_after_school).lower(),
            },
        )

    def consent_forms(self, child_id: str, organizational_unit_id: str) -> list:
        """Samtykkeskjemaer for et barn."""
        return self.web_get_json(
            "/api/consent-forms",
            params={"childId": child_id, "organizationalUnitId": organizational_unit_id},
        )

    def lessons(self, child_id: str, organizational_unit_id: str, week: str | None = None) -> list:
        """Timeplan/ukesplan for en gitt ISO-uke (default inneværende uke)."""
        return self.web_get_json(
            f"/api/students/{child_id}/lessons",
            params={"organizationalUnitId": organizational_unit_id, "week": week or iso_week()},
        )

    def scheduling_events(
        self, child_id: str, organizational_unit_id: str, week: str | None = None
    ) -> list:
        """Timeplan-hendelser (prøver, aktiviteter o.l.) for en ISO-uke."""
        return self.web_get_json(
            f"/api/scheduling-events/{child_id}/student",
            params={"organizationalUnitId": organizational_unit_id, "week": week or iso_week()},
        )

    def school_years(self, organizational_unit_id: str) -> list:
        """Skoleår for en enhet — trengs bl.a. for å hente vurderinger per termin."""
        return self.web_get_json(
            "/api/school-years", params={"organizationalUnitId": organizational_unit_id}
        )

    # TODO(kartlegging): selve karakter-/vurderings-endepunktet laster først
    # etter valg av skoleår/termin i Vurdering-fanen — sniff det med web_api_get.

    # --- Vedlegg (f.eks. ukeplan-PDF i en melding) ----------------------
    # Meldinger fra app-gatewayen (get_thread) har vedlegg med en ferdig-signert
    # blob-URL (Azure SAS, gyldig ~6 t) — kan lastes ned direkte uten auth.
    # Hent tråden fersk rett før nedlasting, ellers kan URL-en være utløpt.

    def read_thread_attachments(self, thread_uid: str, max_chars: int = 40000) -> list:
        """Last ned og les vedleggene i en meldingstråd.

        Returnerer én post per vedlegg: {name, mimeType, text} for PDF/tekst, og
        {name, mimeType, note, url} for binærformater vi ikke leser. Brukes bl.a.
        til å lese ukeplan-PDF-er lagt ved i foreldremeldinger.
        """
        thread = self.get_thread(thread_uid)
        out = []
        for msg in thread.get("messages", []):
            for att in msg.get("attachments", []):
                name = att.get("name")
                mime = att.get("mimeType", "")
                url = att.get("url")
                if not url:
                    out.append({"name": name, "mimeType": mime, "note": "mangler URL"})
                    continue
                try:
                    resp = httpx.get(url, timeout=60, follow_redirects=True)
                    resp.raise_for_status()
                    if mime == "application/pdf" or (name or "").lower().endswith(".pdf"):
                        text = _pdf_to_text(resp.content)
                        out.append({"name": name, "mimeType": mime, "text": text[:max_chars]})
                    elif mime.startswith("text/"):
                        out.append(
                            {"name": name, "mimeType": mime, "text": resp.text[:max_chars]}
                        )
                    else:
                        out.append(
                            {
                                "name": name,
                                "mimeType": mime,
                                "note": "ikke-tekstlig format — ikke lest",
                                "url": url,
                            }
                        )
                except Exception as e:  # noqa: BLE001 — surface, ikke krasj
                    out.append(
                        {"name": name, "mimeType": mime, "note": f"nedlasting/lesing feilet: {e}"}
                    )
        return out

    def close(self) -> None:
        self._http.close()
        self._web.close()
