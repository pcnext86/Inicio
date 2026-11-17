"""Bolso: bot do Telegram por long-poll (sem túnel). Texto + nota de voz, uma vez por cartão."""
import json
import secrets
import urllib.error
import urllib.request

from . import config as C
from .pairing import Pairing

API = "https://api.telegram.org"
REFUSAL = "Lamento, este canal é privado."


def _http(url, data=None, headers=None, timeout=65):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def multipart(fields, files):
    b = "----holo" + secrets.token_hex(8)
    out = b""
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, data, ctype) in files.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n"
    return out + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


class Pocket:
    def __init__(self, cfg, desk, brain_fn, pairing=None):
        t = (cfg or {}).get("telegram") or {}
        self.token = t.get("bot_token")
        self.base = (t.get("api_base") or API).rstrip("/")
        self.speech = (cfg or {}).get("speech") or {}          # {"provider": "openai"|"elevenlabs", "api_key": "..."}
        self.desk, self.brain = desk, brain_fn
        self.pair = pairing or Pairing()
        self.offset = 0
        self.refused = set()
        self._load_pair()

    def enabled(self):
        return C.is_real(self.token)

    def _url(self, m):
        return f"{self.base}/bot{self.token}/{m}"

    def _call(self, method, payload):
        return json.loads(_http(self._url(method), json.dumps(payload).encode(), {"content-type": "application/json"}) or b"{}")

    # emparelhamento persistente (chat_id) em ficheiro 600
    def _pair_file(self):
        return C.state_dir() / "telegram.json"

    def _load_pair(self):
        try:
            self.pair.chat_id = json.loads(self._pair_file().read_text("utf-8")).get("chat_id")
        except Exception:
            pass

    def _save_pair(self):
        C.write_json_atomic(self._pair_file(), {"chat_id": self.pair.chat_id})

    # ----------------------------------------------------------- saída
    def send_text(self, text):
        if self.pair.chat_id is None:
            return False
        self._call("sendMessage", {"chat_id": self.pair.chat_id, "text": text})
        return True

    def tts(self, text):
        """Nota de voz com a chave de fala que o utilizador fornece. Sem chave: None (só texto)."""
        k = self.speech.get("api_key")
        if not C.is_real(k):
            return None
        try:
            if self.speech.get("provider") == "elevenlabs":
                vid = self.speech.get("voice_id", "JBFqnCBsd6RMkjVDRZzb")
                return _http(f"{self.speech.get('base', 'https://api.elevenlabs.io')}/v1/text-to-speech/{vid}", json.dumps({"text": text}).encode(), {"xi-api-key": k, "content-type": "application/json"})
            return _http(f"{self.speech.get('base', 'https://api.openai.com')}/v1/audio/speech", json.dumps({"model": "gpt-4o-mini-tts", "voice": "onyx", "input": text, "response_format": "mp3"}).encode(),
                         {"Authorization": "Bearer " + k, "content-type": "application/json"})
        except Exception:
            return None

    def stt(self, audio):
        k = self.speech.get("api_key")
        if self.speech.get("provider") == "elevenlabs" or not C.is_real(k):
            return None
        body, ct = multipart({"model": "gpt-4o-mini-transcribe"}, {"file": ("voice.ogg", audio, "audio/ogg")})
        try:
            return json.loads(_http(f"{self.speech.get('base', 'https://api.openai.com')}/v1/audio/transcriptions", body, {"Authorization": "Bearer " + k, "content-type": ct})).get("text")
        except Exception:
            return None

    def report(self, card):
        """Um cartão -> um texto + uma nota de voz, nunca duas vezes. Cartões silenciosos (da própria chamada) nunca vão."""
        if card.get("silent") or not self.desk.mark_pushed(card["id"]):
            return False
        if not self.send_text(card["text"]):
            return False
        audio = self.tts(card["text"])
        if audio:
            body, ct = multipart({"chat_id": str(self.pair.chat_id)}, {"voice": ("note.mp3", audio, "audio/mpeg")})
            try:
                _http(self._url("sendVoice"), body, {"content-type": ct})
            except Exception:
                pass
        return True

    # ----------------------------------------------------------- entrada
    def handle(self, upd):
        msg = upd.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id is None:
            return
        text = msg.get("text")
        if not self.pair.is_me(chat_id):
            if text and self.pair.try_pair(chat_id, text):
                self._save_pair(); self.send_text("Emparelhado, senhor. Daqui em diante, este chat sou eu.")
                return
            if chat_id not in self.refused:                # uma recusa educada e mais nada; nunca transcreve estranhos
                self.refused.add(chat_id); self._call("sendMessage", {"chat_id": chat_id, "text": REFUSAL})
            return
        if not text and msg.get("voice"):
            text = self._voice_to_text(msg["voice"].get("file_id"))
            if not text:
                self.send_text("Não consegui transcrever essa nota de voz, senhor."); return
        if text:
            answer = self.brain(text)
            card = self.desk.card(answer, priority="normal", source="telegram")
            if not self.report(card):
                self.send_text(answer)

    def _voice_to_text(self, file_id):
        try:
            info = json.loads(_http(self._url("getFile"), json.dumps({"file_id": file_id}).encode(), {"content-type": "application/json"}))
            audio = _http(f"{self.base}/file/bot{self.token}/{info['result']['file_path']}")
        except Exception:
            return None
        return self.stt(audio)

    def poll_once(self, timeout=25):
        r = json.loads(_http(self._url("getUpdates") + f"?timeout={timeout}&offset={self.offset}", timeout=timeout + 15) or b"{}")
        for u in r.get("result", []):
            self.offset = u["update_id"] + 1
            try:
                self.handle(u)
            except Exception:
                pass
        return len(r.get("result", []))
