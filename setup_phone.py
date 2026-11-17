#!/usr/bin/env python3
"""Cria o agente de chamadas no Retell (idempotente). --dry só mostra o que faria."""
import sys
from jarvis import config as C, telephony as T

dry = "--dry" in sys.argv
r = T.Retell(C.load())
if not C.is_real(r.key):
    sys.exit(T.FRIENDLY_NO_KEY)
try:
    plan = r.setup(dry=dry)
except T.TelephonyError as e:
    sys.exit(str(e))
print(("[dry] " if dry else "") + ("Nada a criar: o agente já existe (" + str(plan["agent_id"]) + ")." if not plan["created"] else "A criar: " + ", ".join(plan["created"])))
if not dry:
    print("Guardado em config.json (permissões 600).")
