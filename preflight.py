#!/usr/bin/env python3
"""Verificação antes de usar: python3 preflight.py [--live]
Sem --live não gasta nada nem liga a ninguém. Com --live faz UMA chamada mínima ao modelo e confirma o id em /v1/models.
Nunca imprime chaves."""
import http.client
import json
import os
import stat
import sys
import threading

from jarvis import config as C, llm as LLM
from jarvis.router import TABLE, route

LIVE = "--live" in sys.argv
rows = []


def check(name, ok, hint=""):
    rows.append(ok); print(("OK    " if ok else "FALHA ") + name + ("" if ok else f"   -> {hint}"))


def warn(name, hint):
    print("AVISO " + name + "   -> " + hint)


cfg = C.load()
print("== Configuração")
check("config.json lido", "_error" not in cfg and bool(cfg), "cria config.json a partir de config.example.json")
has_key = C.anthropic_key(cfg) is not None
(check if has_key else (lambda n, o, h="": warn(n, h)))("chave Anthropic escrita", has_key, "edita config.json e escreve a tua chave (nunca no chat)")
model = cfg.get("model", "claude-opus-5-5")
check("modelo conhecido", model in LLM.KNOWN_MODELS or "/" in model, f"'{model}' não está na lista; usa um dos ids conhecidos")
if LIVE and has_key:
    print("== Modelo (chamada real, mínima)")
    check(f"{model} existe para a tua chave (GET /v1/models)", LLM.models_api_check(cfg, model), "o id não existe para esta chave")
    try:
        d = LLM.call_claude(cfg, model, "Responde só: ok", [{"role": "user", "content": "ping"}], effort="low")
        check("chamada real devolve texto (pensamento + resposta cabem)", bool(LLM.text_of(d.get("content", [])).strip()), "texto vazio: sobe max_tokens")
    except Exception as e:
        check("chamada real", False, str(e))

print("== Encaminhamento de chamadas")
bad = [(s, l, route(s)) for s, l in TABLE if route(s) != l]
check(f"tabela de {len(TABLE)} frases", not bad, str(bad))

print("== Serviços opcionais")
t = cfg.get("telephony") or {}
for label, ok in [("telefone (Retell) configurado", C.is_real(t.get("api_key")) and bool(t.get("agent_id"))), ("Google ligado", C.is_real((cfg.get("google") or {}).get("client_id"))),
                  ("Telegram", C.is_real((cfg.get("telegram") or {}).get("bot_token"))), ("hotline (token + código)", len(str(t.get("hotline_token", ""))) >= 24 and C.is_real(t.get("passcode")))]:
    if not ok:
        warn(label, "opcional; ver README")
    else:
        print("OK    " + label)

print("== Segurança (servidor real, porta temporária)")
os.environ.setdefault("HOLO_STATE", str(C.ROOT / "state"))
import server  # noqa: E402
srv = server.make_server(0); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def hit(method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=body, headers={"Host": host or f"localhost:{port}", **(headers or {})})
    r = c.getresponse(); r.read(); return r.status


check("Host estranho recusado", hit("GET", "/api/graph", host="evil.example") == 403)
check("<script src> de outro site recusado", hit("GET", "/galaxy.js", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors"}) == 403)
check("POST com Origin estranha recusado", hit("POST", "/chat", b"{}", {"Origin": "http://evil.example", "Content-Type": "application/json"}) == 403)
check("corpo gigante recusado", hit("POST", "/chat", b"x" * 30000, {"Content-Type": "application/json"}) == 413)
check("config.json nunca é servido", hit("GET", "/config.json") == 404 and hit("GET", "/%2e%2e/config.json") == 404 and hit("GET", "/vendor/%2e%2e/config.json") == 404)
srv.shutdown()
C.secure_all()
secret = [C.config_path()] + (list(C.state_dir().iterdir()) if C.state_dir().exists() else [])
check("ficheiros secretos a 600", all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in secret if p.exists() and p.is_file()), "chmod 600 falhou (no Windows não se aplica)")
gi = (C.ROOT / ".gitignore").read_text() if (C.ROOT / ".gitignore").exists() else ""
check(".gitignore cobre config.json*", "config.json*" in gi)

print("\n" + ("Tudo certo, senhor." if all(rows) else f"{rows.count(False)} verificação(ões) falharam."))
sys.exit(0 if all(rows) else 1)
