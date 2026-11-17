"""Emparelhamento do Telegram: código aleatório, 10 min, a mensagem INTEIRA, uso único, morre às 5 falhas."""
import hmac
import secrets
import time

TTL = 600
MAX_WRONG = 5


class Pairing:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.code = None
        self.expires = 0
        self.wrong = 0
        self.chat_id = None

    def mint(self):
        """Só quando eu peço à secretária ('Jarvis, pocket code')."""
        self.code = f"{secrets.randbelow(10**6):06d}"; self.expires = self.clock() + TTL; self.wrong = 0
        return self.code

    def try_pair(self, chat_id, message):
        """True = emparelhado agora. O código tem de ser a mensagem toda, nunca 'algures dentro'."""
        if not self.code or self.clock() > self.expires:
            self.code = None
            return False
        if hmac.compare_digest((message or "").strip().encode(), self.code.encode()):
            self.chat_id = chat_id; self.code = None
            return True
        self.wrong += 1
        if self.wrong >= MAX_WRONG:
            self.code = None            # morre depois de 5 palpites errados
        return False

    def is_me(self, chat_id):
        return self.chat_id is not None and chat_id == self.chat_id
