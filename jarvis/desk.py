"""Estado da secretária: cartões (sem duplicados), linha urgente, lembretes e briefing (sobrevivem a reinícios), hotline."""
import hmac
import json
import secrets
import threading
import time

from . import config as C

URGENT_COOLDOWN = 600
LOCKOUT_SECONDS = 900
MAX_MISSES = 3


class Desk:
    def __init__(self, path=None, clock=time.time):
        self.path = path or (C.state_dir() / "desk.json")
        self.clock = clock
        self.lock = threading.RLock()
        self.s = {"cards": [], "reminders": [], "briefing": None, "urgent_armed": False, "last_urgent": 0, "pushed": [], "lockouts": {}, "misses": {}, "messages": [], "done": []}
        try:
            self.s.update(json.loads(open(self.path, encoding="utf-8").read()))
        except Exception:
            pass

    def _save(self):
        C.write_json_atomic(self.path, self.s)

    # ---------------------------------------------------------- cartões
    def card(self, text, priority="normal", silent=False, source=None):
        with self.lock:
            c = {"id": secrets.token_hex(6), "text": text, "priority": priority, "silent": silent, "source": source, "t": self.clock()}
            self.s["cards"].append(c); self.s["cards"] = self.s["cards"][-200:]; self._save(); return c

    def mark_pushed(self, card_id):
        """UMA mensagem, não três: cada cartão só chega ao telemóvel uma vez. True = podes enviar."""
        with self.lock:
            if card_id in self.s["pushed"]:
                return False
            self.s["pushed"].append(card_id); self.s["pushed"] = self.s["pushed"][-500:]; self._save(); return True

    def inert_message(self, who, text):
        """Palavras de um desconhecido: um cartão inerte. Nunca vão para notas, lembretes ou contactos."""
        with self.lock:
            m = {"id": secrets.token_hex(6), "from": str(who)[:80], "text": str(text)[:500], "t": self.clock(), "inert": True}
            self.s["messages"].append(m); self.s["messages"] = self.s["messages"][-100:]; self._save(); return m

    # ---------------------------------------------------------- linha urgente
    def arm_urgent(self, on=True):
        with self.lock:
            self.s["urgent_armed"] = bool(on); self._save()

    def should_ring_urgent(self, priority, about_own_call=False):
        """Uma vez, com 10 min de intervalo; nunca por causa das minhas próprias chamadas."""
        with self.lock:
            if about_own_call or priority != "high" or not self.s["urgent_armed"]:
                return False
            now = self.clock()
            if now - self.s["last_urgent"] < URGENT_COOLDOWN:
                return False
            self.s["last_urgent"] = now; self._save(); return True

    # ---------------------------------------------------------- lembretes e briefing
    def add_reminder(self, at, text, channel="call"):
        with self.lock:
            r = {"id": secrets.token_hex(6), "at": at, "text": text, "channel": channel, "fired": False}
            self.s["reminders"].append(r); self._save(); return r

    def due_reminders(self):
        """Os que venceram (mesmo durante um reinício) disparam já — e nunca duas vezes."""
        with self.lock:
            now, out = self.clock(), []
            for r in self.s["reminders"]:
                if not r["fired"] and r["at"] <= now:
                    r["fired"] = True; out.append(dict(r))
            if out:
                self.s["reminders"] = [r for r in self.s["reminders"] if not r["fired"]][-100:]; self._save()
            return out

    def set_briefing(self, hour, minute=0):
        with self.lock:
            self.s["briefing"] = {"hour": hour, "minute": minute, "last_day": None}; self._save()

    def cancel_briefing(self):
        with self.lock:
            self.s["briefing"] = None; self._save()

    def briefing_due(self, local_struct):
        with self.lock:
            b = self.s["briefing"]
            if not b:
                return False
            day = (local_struct.tm_year, local_struct.tm_yday)
            if list(day) == b.get("last_day"):
                return False
            if (local_struct.tm_hour, local_struct.tm_min) >= (b["hour"], b["minute"]):
                b["last_day"] = list(day); self._save(); return True
            return False

    # ---------------------------------------------------------- hotline: código verificado NO servidor
    def verify_code(self, caller, spoken_digits, real_code):
        """Tempo constante; 3 falhas => 15 min de bloqueio. O código nunca sai daqui."""
        with self.lock:
            now = self.clock()
            if self.s["lockouts"].get(caller, 0) > now:
                return {"verified": False, "locked": True}
            digits = "".join(ch for ch in str(spoken_digits) if ch.isdigit())
            if real_code and hmac.compare_digest(digits.encode(), str(real_code).encode()):
                self.s["misses"].pop(caller, None); self._save()
                return {"verified": True}
            n = self.s["misses"].get(caller, 0) + 1
            self.s["misses"][caller] = n
            if n >= MAX_MISSES:
                self.s["lockouts"][caller] = now + LOCKOUT_SECONDS; self.s["misses"].pop(caller, None)
            self._save()
            return {"verified": False, "locked": n >= MAX_MISSES}

    def context_pack(self):
        with self.lock:
            open_items = [c["text"] for c in self.s["cards"][-5:] if not c.get("silent")]
            return {"date": time.strftime("%A, %d %B %Y", time.localtime(self.clock())), "open_items": open_items}
