"""Liga tudo: um objeto por processo. Os módulos são independentes; aqui só se cola."""
import hmac
import threading
import time

from . import calls, config as C, llm as LLM, toolloop
from .desk import Desk
from .google import Google
from .telegram import Pocket
from .telephony import Retell, TelephonyError, transcript_text


class Services:
    def __init__(self, brain, port=4890):
        self.brain, self.port = brain, port
        self.desk = Desk()
        self.cfg = C.load()
        self.google = Google(self.cfg, port)
        self.retell = Retell(self.cfg)
        self.pocket = Pocket(self.cfg, self.desk, self._pocket_brain)
        self.in_call = False
        self.verified_calls = set()
        self.stop = threading.Event()

    # ---------- cérebro do bolso: o mesmo caminho do chat
    def _pocket_brain(self, text):
        cmd = self.handle_voice(text)
        if cmd:
            return cmd
        if self.google.connected():
            return toolloop.run(self.cfg, self.brain, self.google, text)["answer"]
        data, _ = LLM.complete(self.cfg, self.brain, toolloop.SYSTEM, [{"role": "user", "content": text}])
        return LLM.text_of(data.get("content", [])).strip()

    # ---------- frases sobre chamadas / lembretes (só frases ACABADAS)
    def handle_voice(self, sentence):
        r = calls.desk_command(sentence, self.desk)
        if r:
            return r
        if "pocket code" in sentence.lower() or "código do bolso" in sentence.lower():
            return f"O código do bolso é {self.pocket.pair.mint()}. Envie-o, sozinho, ao bot nos próximos dez minutos."
        out = calls.handle_sentence(sentence, self.desk, self.call_me_async)
        if not out:
            return None
        label, val = out
        if label == "stage":
            self.stage(delay=val)
            return f"Very well, sir. An urgent call, staged, in {val} seconds. I'm announcing it: this one is fiction."
        return val

    # ---------- ligar
    def call_me(self, headline, notes):
        self.in_call = True
        try:
            cid = self.retell.call_me(headline, notes)
        except Exception:
            self.in_call = False
            raise
        threading.Thread(target=self._watch, args=(cid,), daemon=True).start()
        return cid

    def call_me_async(self, headline, notes):
        try:
            self.call_me(headline, notes)
        except TelephonyError as e:
            self.desk.card(str(e), priority="normal")

    def _watch(self, cid):
        try:
            call = self.retell.wait_for_end(cid)
            calls.after_call(self.cfg, self.brain, self.google, self.desk, self.pocket if self.pocket.enabled() else None, call)
        except Exception as e:
            self.desk.card(f"Não consegui concluir a chamada: {e}", priority="normal")
        finally:
            self.in_call = False

    def stage(self, delay=90, dry=False, scenario=0):
        """Chamada encenada: SÓ toca ao telefone (sem cartão, sem voz na secretária, sem Telegram durante a chamada)."""
        h, n = calls.SCENARIOS[scenario % len(calls.SCENARIOS)]
        if dry:
            return {"ok": True, "dry": True, "delay": delay, "headline": h, "ready": self.retell.ready()}
        threading.Timer(delay, lambda: self.call_me_async(h, n)).start()
        return {"ok": True, "delay": delay}

    # ---------- urgente: uma vez, com intervalo
    def urgent_event(self, headline, notes, priority="high", about_own_call=False):
        if self.in_call or not self.desk.should_ring_urgent(priority, about_own_call):
            return False
        self.call_me_async(headline, notes); return True

    # ---------- tique (lembretes/briefing/telegram), chamado em ciclo
    def tick(self, now_struct=None):
        for r in self.desk.due_reminders():
            if r["channel"] == "text" and self.pocket.enabled():
                self.pocket.send_text("Reminder: " + r["text"])
            else:
                self.call_me_async("Reminder", [r["text"]])
        if self.desk.briefing_due(now_struct or time.localtime(self.desk.clock())):
            self.call_me_async("Your morning briefing", [self.briefing_text()])

    def briefing_text(self):
        parts = []
        if self.google.connected():
            try:
                t0 = time.strftime("%Y-%m-%dT00:00:00%z"); t1 = time.strftime("%Y-%m-%dT23:59:59%z")
                parts.append("Calendar: " + "; ".join(e["summary"] for e in self.google.gcal_events(t0[:-2] + ":" + t0[-2:], t1[:-2] + ":" + t1[-2:])) )
            except Exception:
                pass                                              # ferramenta falhada: saltada em silêncio
            try:
                parts.append("Unread: " + "; ".join(f"{m['from']}: {m['subject']}" for m in self.google.gmail_unread(3)))
            except Exception:
                pass
        parts.append("Open on the desk: " + "; ".join(c["text"] for c in self.desk.s["cards"][-3:] if not c.get("silent")))
        data, _ = LLM.complete(self.cfg, self.brain, "Compõe 3 a 5 frases faladas, em inglês de mordomo, só com estes factos. Nunca narres ferramentas falhadas.", [{"role": "user", "content": "\n".join(parts)}], effort="low")
        return LLM.text_of(data.get("content", [])).strip()

    def run_forever(self):
        last_poll = 0
        while not self.stop.is_set():
            try:
                self.tick()
                if self.pocket.enabled():
                    self.pocket.poll_once(timeout=20)
            except Exception:
                time.sleep(5)
            self.stop.wait(5)

    # ---------- hotline: o servidor verifica; o agente nunca vê o código
    def hotline_token_ok(self, token):
        want = str(((self.cfg.get("telephony") or {}).get("hotline_token")) or "")
        return len(want) >= 24 and hmac.compare_digest(str(token).encode(), want.encode())

    def hotline(self, action, body):
        call = (body.get("call") or {})
        cid, caller = str(call.get("call_id", ""))[:80], str(call.get("from_number", ""))[:30] or "?"
        args = body.get("args") or {}
        if action == "verify_code":
            real = (self.cfg.get("telephony") or {}).get("passcode")
            res = self.desk.verify_code(caller, args.get("code", ""), real if C.is_real(real) else None)   # o ID do chamador é só uma pista
            if res.get("verified"):
                self.verified_calls.add(cid)
                res["context"] = self.desk.context_pack()
            return res
        if action == "fetch_brain":
            if cid not in self.verified_calls:
                return {"error": "not verified"}
            return {"answer": self._pocket_brain(str(args.get("question", ""))[:500])}
        if action == "take_message":
            self.desk.inert_message(caller, args.get("message", ""))       # inerte: nunca vai para notas, lembretes ou contactos
            return {"ok": True}
        return {"error": "unknown"}
