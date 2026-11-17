"""Google direto por REST: Gmail (ler, procurar, RASCUNHOS) e Calendar. Não existe função de enviar e nunca existirá."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config as C

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary"
SCOPES = ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]
REDIRECT_PATH = "/oauth/callback"


class GoogleError(Exception):
    pass


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Google:
    def __init__(self, cfg, port=4890, urls=None):
        g = (cfg or {}).get("google") or {}
        self.client_id, self.secret = g.get("client_id"), g.get("client_secret")
        self.port = port
        self.u = {"auth": AUTH, "token": TOKEN, "gmail": GMAIL, "cal": CAL, **(urls or g.get("urls") or {})}
        self.pending = {}
        self.access = None
        self.exp = 0
        self.lock = threading.Lock()

    def configured(self):
        return C.is_real(self.client_id) and C.is_real(self.secret)

    def _tok_path(self):
        return C.state_dir() / "google_token.json"

    def refresh_token(self):
        try:
            return json.loads(self._tok_path().read_text("utf-8")).get("refresh_token")
        except Exception:
            return None

    def connected(self):
        return bool(self.refresh_token())

    @property
    def redirect(self):
        return f"http://localhost:{self.port}{REDIRECT_PATH}"

    # ---- consentimento: código de autorização + PKCE + state aleatório verificado no callback
    def start(self):
        if not self.configured():
            raise GoogleError("Falta o client_id/client_secret do Google em config.json (ver README), senhor.")
        verifier = b64url(secrets.token_bytes(48)); state = secrets.token_urlsafe(24)
        self.pending[state] = {"v": verifier, "t": time.time()}
        for s in [k for k, v in self.pending.items() if time.time() - v["t"] > 600]:
            self.pending.pop(s, None)
        q = {"client_id": self.client_id, "redirect_uri": self.redirect, "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
             "state": state, "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
        return self.u["auth"] + "?" + urllib.parse.urlencode(q)

    def callback(self, code, state):
        p = self.pending.pop(state or "", None)
        if not p or time.time() - p["t"] > 600:
            raise GoogleError("Pedido de autorização inválido ou expirado.")
        j = self._form(self.u["token"], {"client_id": self.client_id, "client_secret": self.secret, "code": code, "code_verifier": p["v"], "grant_type": "authorization_code", "redirect_uri": self.redirect})
        if not j.get("refresh_token"):
            raise GoogleError("O Google não devolveu refresh token; tenta outra vez.")
        C.write_json_atomic(self._tok_path(), {"refresh_token": j["refresh_token"]})   # chmod 600, nunca no browser
        self.access, self.exp = j.get("access_token"), time.time() + j.get("expires_in", 3000)

    def _form(self, url, data):
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST", headers={"content-type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise GoogleError(f"Google respondeu {e.code} na autorização.")
        except Exception as e:
            raise GoogleError(f"Não consegui falar com o Google ({type(e).__name__}).")

    def _bearer(self):
        with self.lock:
            if self.access and time.time() < self.exp - 60:
                return self.access
            rt = self.refresh_token()
            if not rt:
                raise GoogleError("Google não está ligado: usa o botão Ligar Google, senhor.")
            j = self._form(self.u["token"], {"client_id": self.client_id, "client_secret": self.secret, "refresh_token": rt, "grant_type": "refresh_token"})
            self.access, self.exp = j["access_token"], time.time() + j.get("expires_in", 3000)
            return self.access

    def _api(self, method, url, body=None):
        req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(), headers={"Authorization": "Bearer " + self._bearer(), "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise GoogleError(f"Google respondeu {e.code}.")
        except Exception as e:
            raise GoogleError(f"Não consegui falar com o Google ({type(e).__name__}).")

    # ---- ferramentas: uma função pequena cada
    @staticmethod
    def _hdr(m, name):
        return next((h["value"] for h in m.get("payload", {}).get("headers", []) if h["name"].lower() == name), "")

    def gmail_search(self, query, max_results=5):
        ids = self._api("GET", f"{self.u['gmail']}/messages?" + urllib.parse.urlencode({"q": query, "maxResults": max_results})).get("messages", [])
        out = []
        for m in ids:
            d = self._api("GET", f"{self.u['gmail']}/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject")
            out.append({"id": m["id"], "from": self._hdr(d, "from"), "subject": self._hdr(d, "subject"), "snippet": d.get("snippet", "")})
        return out

    def gmail_unread(self, max_results=5):
        return self.gmail_search("is:unread category:primary", max_results)

    def gmail_read(self, msg_id):
        d = self._api("GET", f"{self.u['gmail']}/messages/{urllib.parse.quote(msg_id)}?format=full")
        def walk(p):
            if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace")
            for q in p.get("parts", []) or []:
                r = walk(q)
                if r:
                    return r
            return ""
        return {"id": msg_id, "from": self._hdr(d, "from"), "subject": self._hdr(d, "subject"), "body": (walk(d.get("payload", {})) or d.get("snippet", ""))[:4000]}

    def gmail_draft(self, to, subject, body):
        raw = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        r = self._api("POST", f"{self.u['gmail']}/drafts", {"message": {"raw": b64url(raw.encode())}})
        return {"draft_id": r.get("id"), "note": "Rascunho criado. Nada foi enviado."}

    def gcal_events(self, time_min, time_max):
        q = urllib.parse.urlencode({"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "orderBy": "startTime"})
        return [{"id": e["id"], "summary": e.get("summary", "(sem título)"), "start": e.get("start"), "end": e.get("end"), "link": e.get("htmlLink")} for e in self._api("GET", f"{self.u['cal']}/events?{q}").get("items", [])]

    def gcal_add(self, summary, start, end):
        r = self._api("POST", f"{self.u['cal']}/events", {"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}})
        return {"id": r.get("id"), "link": r.get("htmlLink")}

    def gcal_move(self, event_id, start, end):
        r = self._api("PATCH", f"{self.u['cal']}/events/{urllib.parse.quote(event_id)}", {"start": {"dateTime": start}, "end": {"dateTime": end}})
        return {"id": r.get("id"), "link": r.get("htmlLink")}


READ_TOOLS = {"gmail_unread", "gmail_search", "gmail_read", "gcal_events"}
MUTATING = {"gcal_move"}              # alterar/mover/apagar. (gmail_draft e gcal_add acrescentam, são permitidos)
TOOL_DEFS = [
    {"name": "gmail_unread", "description": "Lista emails por ler da caixa principal.", "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}}},
    {"name": "gmail_search", "description": "Procura emails (sintaxe do Gmail).", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
    {"name": "gmail_read", "description": "Lê um email pelo id.", "input_schema": {"type": "object", "properties": {"msg_id": {"type": "string"}}, "required": ["msg_id"]}},
    {"name": "gmail_draft", "description": "Cria um RASCUNHO (nunca envia).", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}},
    {"name": "gcal_events", "description": "Eventos entre duas datas ISO 8601 com fuso.", "input_schema": {"type": "object", "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"}}, "required": ["time_min", "time_max"]}},
    {"name": "gcal_add", "description": "Cria um evento (datas ISO 8601 com fuso).", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}, "required": ["summary", "start", "end"]}},
    {"name": "gcal_move", "description": "Muda a hora de um evento existente.", "input_schema": {"type": "object", "properties": {"event_id": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}, "required": ["event_id", "start", "end"]}},
]
