#!/usr/bin/env python3
"""HOLO - servidor local. Só biblioteca standard do Python 3.

    python3 server.py                  # http://localhost:4890
    HOLO_PORT=4891 python3 server.py   # outra porta

Escuta apenas em 127.0.0.1 e só aceita pedidos cujo Host seja localhost/127.0.0.1
(protege contra páginas de outros sítios a falarem com o teu servidor).

Galáxia JARVIS (tecla G):
  GET  /api/graph     notas -> {nodes, links}   (cada nó tem id numérico = posição no array)
  POST /chat          pergunta -> {answer, nodes}   (config.json: API Anthropic ou `claude -p`)
  POST /remember      "lembra-te que..." -> nota nova em <notas>/captures/
O config.json (com a chave) NUNCA é servido ao browser.
"""
import http.server
import json
import os
import pathlib
import posixpath
import re
import socketserver
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
PORT = int(os.environ.get("HOLO_PORT", "4890"))
MAX_NOTE_CHARS = 40000
MAX_ORBS = 10
MAX_NOTES_PER_ORB = 12
MAX_GRAPH_NOTES = 800
EXCERPT_CHARS = 700
CONTEXT_NOTES = 6
CONTEXT_CHARS = 1400
HISTORY_MESSAGES = 8
PLACEHOLDER_KEY = "PUT-YOUR-KEY-HERE"

# Só estes caminhos são servidos ao browser. Tudo o resto (config.json, server.py, notes/, tests/...) dá 404.
PUBLIC_FILES = {"/holo.html", "/probe.js", "/galaxy.js"}
PUBLIC_PREFIXES = ("/vendor/", "/props/")


# ----------------------------------------------------------------- notas (modo cartas)
def notes_root():
    """Pasta de notas: HOLO_NOTES, ou 'folder' de holo.json, ou ./notes (exemplo)."""
    sample = ROOT / "notes"
    env = os.environ.get("HOLO_NOTES", "").strip()
    folder = env
    if not folder:
        try:
            cfg = json.loads((ROOT / "holo.json").read_text("utf-8"))
            folder = (cfg.get("folder") or "").strip()
        except Exception:
            folder = ""
    if folder:
        p = pathlib.Path(folder).expanduser()
        if p.is_dir():
            return p, False
    return sample, bool(folder)  # (pasta, caiu_para_exemplo)


def read_note(f):
    return {"name": f.stem, "text": f.read_text("utf-8", errors="replace")[:MAX_NOTE_CHARS]}


def visible(path, root):
    return not any(part.startswith(".") for part in path.relative_to(root).parts)


def read_tree():
    root, fallback = notes_root()
    orbs, loose = [], []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                files = []
                for f in sorted(entry.rglob("*.md"), key=lambda p: str(p).lower()):
                    if visible(f, root) and f.is_file():
                        files.append(read_note(f))
                        if len(files) >= MAX_NOTES_PER_ORB:
                            break
                if files:
                    orbs.append({"name": entry.name, "notes": files})
            elif entry.suffix.lower() == ".md" and entry.is_file():
                loose.append(read_note(entry))
        except OSError:
            continue
    if loose:
        orbs.insert(0, {"name": "Soltas", "notes": loose[:MAX_NOTES_PER_ORB]})
    return {"root": str(root), "fallback": fallback, "orbs": orbs[:MAX_ORBS]}


# ----------------------------------------------------------------- galáxia (grafo)
def strip_md(t):
    t = re.sub(r"^---[\s\S]*?---\s*", "", t)
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"!?\[\[([^\]|#]+)[^\]]*\]\]", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"[*_`>~]", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


STOP = set("""a o os as um uma uns umas de do da dos das em no na nos nas por para com sem sobre entre e ou mas que se
como qual quais quando onde quem foi sao ser tem ter ha eu tu me te lhe meu minha teu tua isto isso aquilo ao aos
the an and or of to in on for with is are was were be what which who how when where do does did i you my your it this that""".split())


def tokens(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", norm(s)) if w not in STOP}


class Brain:
    """Estado em memória da galáxia. O id de cada nó é a sua posição em `nodes` (o /chat devolve esses índices)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.nodes, self.links, self.text, self.tok_title, self.tok_body = [], [], [], [], []
        self.root = None
        self.sessions = {}

    # -- leitura das notas
    def scan(self):
        root, _ = notes_root()
        files = []
        for f in sorted(root.rglob("*.md"), key=lambda p: str(p).lower()):
            try:
                if f.is_file() and visible(f, root):
                    files.append(f)
            except (OSError, ValueError):
                continue
            if len(files) >= MAX_GRAPH_NOTES:
                break
        with self.lock:
            self.root = root
            self.nodes, self.text, self.tok_title, self.tok_body = [], [], [], []
            for f in files:
                try:
                    raw = f.read_text("utf-8", errors="replace")[:MAX_NOTE_CHARS]
                except OSError:
                    continue
                self._add(f, root, raw)
            self.links = self._compute_links()
            return self.snapshot()

    def _add(self, f, root, raw):
        rel = f.relative_to(root)
        body = strip_md(raw)
        node = {
            "id": len(self.nodes),
            "label": f.stem,
            "group": rel.parts[0] if len(rel.parts) > 1 else "raiz",
            "excerpt": body[:EXCERPT_CHARS],
            "path": rel.as_posix(),
        }
        self.nodes.append(node)
        self.text.append((raw, body))
        self.tok_title.append(tokens(f.stem))
        self.tok_body.append(tokens(body))
        return node

    @staticmethod
    def _wikilinks(raw):
        return {norm(m.split("|")[0].split("#")[0].strip()) for m in re.findall(r"\[\[([^\]]+)\]\]", raw)}

    def _links_for(self, i, upto=None):
        """Ligações do nó i com os restantes: menção do título ou [[wikilinks]] em comum."""
        out = set()
        raw_i = self.text[i][0]
        n_i = norm(raw_i)
        wl_i = self._wikilinks(raw_i)
        t_i = norm(self.nodes[i]["label"])
        for j in range(len(self.nodes) if upto is None else upto):
            if j == i:
                continue
            t_j = norm(self.nodes[j]["label"])
            raw_j = self.text[j][0]
            hit = (len(t_j) >= 4 and t_j in n_i) or (len(t_i) >= 4 and t_i in norm(raw_j))
            if not hit:
                wl_j = self._wikilinks(raw_j)
                hit = t_j in wl_i or t_i in wl_j or bool((wl_i & wl_j) - {""})
            if hit:
                out.add((min(i, j), max(i, j)))
        return out

    def _compute_links(self):
        out = set()
        for i in range(len(self.nodes)):
            out |= self._links_for(i, upto=i)
        return [{"source": a, "target": b} for a, b in sorted(out)]

    def snapshot(self):
        return {"nodes": [dict(n) for n in self.nodes], "links": list(self.links), "root": str(self.root)}

    # -- pesquisa por palavras-chave (título pesa a triplicar)
    def score(self, question):
        q = tokens(question)
        res = []
        for i in range(len(self.nodes)):
            s = 3 * len(q & self.tok_title[i]) + len(q & self.tok_body[i])
            if s > 0:
                res.append((s, i))
        res.sort(key=lambda x: (-x[0], x[1]))
        return [i for _, i in res[:CONTEXT_NOTES]]

    # -- /remember
    def remember(self, text):
        text = text.strip()
        m = re.match(r"^\s*(lembra[- ]?te que|lembra que|recorda[- ]?te que|recorda que|n[aã]o te esque[cç]as que|remember that)\s*[,:]?\s*(.*)$",
                     text, flags=re.I | re.S)
        body = (m.group(2) if m else text).strip()
        if not body:
            raise ValueError("nada para lembrar")
        body = body[:2000]
        words = re.findall(r"[\wÀ-ÿ'-]+", body)[:6]
        title = " ".join(words).strip().capitalize() or "Nota"
        slug = re.sub(r"[^a-z0-9]+", "-", norm(title)).strip("-")[:48] or "nota"
        with self.lock:
            if not self.nodes:
                self.scan()
            root = self.root
            cap = root / "captures"
            cap.mkdir(exist_ok=True)
            base = time.strftime("%Y-%m-%d") + "-" + slug
            path, k = cap / (base + ".md"), 2
            while path.exists():
                path = cap / f"{base}-{k}.md"
                k += 1
            assert path.resolve().parent == cap.resolve()
            raw = f"# {title}\n\n{body}\n"
            path.write_text(raw, "utf-8")
            node = self._add(path, root, raw)
            node["label"] = path.stem
            self.tok_title[-1] = tokens(path.stem)
            related = self.score(body)
            related = [i for i in related if i != node["id"]]
            near = related[0] if related else None
            new_links = {(min(node["id"], j), max(node["id"], j)) for j in related[:2]}
            new_links |= self._links_for(node["id"])
            self.links.extend({"source": a, "target": b} for a, b in sorted(new_links))
            return {"node": dict(node), "links": [{"source": a, "target": b} for a, b in sorted(new_links)], "near": near, "title": title}


BRAIN = Brain()

SYSTEM_PROMPT = (
    "És o JARVIS, mordomo digital do utilizador: educadíssimo, seco, com um humor refinado e afiado. "
    "Trata-o por \"senhor\" (de vez em quando, não em todas as frases). Uma frase verdadeiramente engraçada vale mais do que três sem graça. "
    "Responde sempre em português de Portugal.\n"
    "Recebes excertos de notas numeradas [1], [2]... Regras:\n"
    "- Perguntas sobre as notas: UMA frase espirituosa mais os factos, no máximo 3 frases. Responde APENAS com o que as notas dizem; "
    "se não cobrirem a pergunta, admite-o com elegância. Nunca recites a nota (está no ecrã).\n"
    "- Conversa de circunstância ou piadas: responde sem usar as notas e com \"used\": [].\n"
    "- Responde SÓ com JSON válido, sem mais texto: {\"answer\": \"...\", \"used\": [números das notas realmente usadas, a mais relevante primeiro]}"
)


from jarvis import config as JC, llm as LLM

BRAIN_MODEL = LLM.Brain()
SERVICES = None


def services():
    global SERVICES
    if SERVICES is None:
        from jarvis.services import Services
        SERVICES = Services(BRAIN_MODEL)
    return SERVICES


def load_config():
    return JC.load()


ChatError = LLM.LLMError


def parse_model_json(text):
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            ans = str(obj.get("answer", "")).strip()
            used = [int(x) for x in obj.get("used", []) if isinstance(x, (int, float))]
            if ans:
                return ans, used
        except (ValueError, TypeError):
            pass
    return text.strip(), []


def model_command(cfg, question):
    """'experimenta o Opus 5' / 'volta ao cérebro normal': troca por voz, só em runtime. Devolve resposta ou None."""
    req = LLM.parse_model_request(question)
    if not req:
        return None
    if req["action"] == "reset":
        BRAIN_MODEL.reset()
        return {"answer": f"Cérebro normal reposto: {LLM.pretty(BRAIN_MODEL.current(cfg))}, senhor.", "nodes": [], "model": BRAIN_MODEL.current(cfg)}
    if req["action"] == "refuse":
        return {"answer": f"Não reconheço esse modelo ({req['wanted']}), senhor. Fico com {LLM.pretty(BRAIN_MODEL.current(cfg))}.", "nodes": [], "model": BRAIN_MODEL.current(cfg)}
    BRAIN_MODEL.swap(req["id"])
    return {"answer": f"Agora a pensar com {LLM.pretty(req['id'])}, senhor.", "nodes": [], "model": req["id"]}


def see(sid, question, image_b64):
    cfg = load_config()
    if cfg.get("_error"):
        raise ChatError(cfg["_error"], 503)
    if not isinstance(image_b64, str) or not re.fullmatch(r"[A-Za-z0-9+/=]+", image_b64 or "") or len(image_b64) > 3_500_000:
        raise ChatError("Imagem inválida ou demasiado grande.", 400)
    system = "És o JARVIS, mordomo digital: seco, educado, com humor. Português de Portugal. Descreve o que vês no ecrã em 2 frases no máximo e responde à pergunta. Não leias dados sensíveis (palavras-passe, números de cartão) em voz alta."
    messages = [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}}, {"type": "text", "text": question}]}]
    data, model = LLM.complete(cfg, BRAIN_MODEL, system, messages, effort=cfg.get("effort", "medium"))
    return {"answer": LLM.text_of(data.get("content", [])).strip() or "Não consegui ver nada de útil, senhor.", "model": model}


def chat(sid, question):
    cfg = load_config()
    if cfg.get("_error"):
        raise ChatError(cfg["_error"], 503)
    cmd = model_command(cfg, question)
    if cmd:
        return cmd
    spoken = services().handle_voice(question)      # chamadas/lembretes/'chama-me se': ANTES do cérebro
    if spoken:
        return {"answer": spoken, "nodes": [], "model": BRAIN_MODEL.current(cfg)}
    with BRAIN.lock:
        if not BRAIN.nodes:
            BRAIN.scan()
        idx = BRAIN.score(question)
        ctx = "\n".join(f"[{k + 1}] {BRAIN.nodes[i]['label']}: {BRAIN.text[i][1][:CONTEXT_CHARS]}" for k, i in enumerate(idx)) or "(nenhuma nota relevante encontrada)"
        hist = list(BRAIN.sessions.get(sid, []))
    messages = hist + [{"role": "user", "content": f"Notas:\n{ctx}\n\nPergunta: {question}"}]
    data, model = LLM.complete(cfg, BRAIN_MODEL, SYSTEM_PROMPT, messages, effort=cfg.get("effort", "medium"))
    answer, used = parse_model_json(LLM.text_of(data.get("content", [])))
    nodes = []
    for u in used:
        if 1 <= u <= len(idx) and idx[u - 1] not in nodes:
            nodes.append(idx[u - 1])
    with BRAIN.lock:
        h = BRAIN.sessions.setdefault(sid, [])
        h += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        del h[:-HISTORY_MESSAGES]
        if len(BRAIN.sessions) > 50:
            BRAIN.sessions.pop(next(iter(BRAIN.sessions)))
    return {"answer": answer, "nodes": nodes, "model": model}


# ----------------------------------------------------------------- HTTP
class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".glb": "model/gltf-binary",
        ".data": "application/octet-stream", ".tflite": "application/octet-stream", ".binarypb": "application/octet-stream",
        "": "application/octet-stream",
    }

    timeout = 30          # tempo limite do socket (contra ligações penduradas)

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        super().end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Host/Origin: só localhost (contra DNS rebinding e páginas de outros sítios)
    def local_ok(self):
        port = self.server.server_address[1]
        ok_hosts = {f"localhost:{port}", f"127.0.0.1:{port}", "localhost", "127.0.0.1"}
        if (self.headers.get("Host") or "").lower() not in ok_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {f"http://{h}" for h in ok_hosts}:
            return False
        return True

    def do_GET(self):
        if not self.local_ok():
            return self.send_error(403)
        path = urllib.parse.urlparse(self.path).path
        # Outro site pode, no máximo, NAVEGAR até à app; nunca carregar ficheiros/dados (<script src>, fetch, etc.)
        site, dest = self.headers.get("Sec-Fetch-Site"), self.headers.get("Sec-Fetch-Dest")
        if site in ("cross-site", "same-site") and not (dest == "document" and self.headers.get("Sec-Fetch-Mode") == "navigate" and path in ("/", "/index.html", "/oauth/callback")):
            return self.send_error(403)
        if path == "/api/props":
            return self.send_json(sorted(p.name for p in (ROOT / "props").glob("*.glb")))
        if path == "/api/notes":
            try:
                return self.send_json(read_tree())
            except Exception as e:
                return self.send_json({"root": "", "fallback": True, "orbs": [], "error": str(e)})
        if path == "/api/graph":
            try:
                return self.send_json(BRAIN.scan())
            except Exception as e:
                return self.send_json({"nodes": [], "links": [], "error": str(e)}, 500)
        if path == "/oauth/start":
            try:
                url = services().google.start()
            except Exception as e:
                return self.send_json({"error": str(e)}, 503)
            self.send_response(302); self.send_header("Location", url); self.end_headers(); return
        if path == "/oauth/callback":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                services().google.callback((qs.get("code") or [""])[0], (qs.get("state") or [""])[0])
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
            self.send_response(302); self.send_header("Location", "/"); self.end_headers(); return
        if path in ("/", "/index.html"):
            q = urllib.parse.urlparse(self.path).query
            self.path = "/holo.html" + ("?" + q if q else "")
            return super().do_GET()
        # valida o caminho JÁ decodificado e normalizado (%2e%2e = ..) e nunca serve ficheiros config*
        dec = urllib.parse.unquote(path)
        norm_path = posixpath.normpath(dec)
        if ("\\" in dec or "\x00" in dec or ".." in dec.split("/") or norm_path != dec.rstrip("/") or
                posixpath.basename(norm_path).lower().startswith("config")):
            return self.send_error(404)
        if norm_path in PUBLIC_FILES or norm_path.startswith(PUBLIC_PREFIXES):
            self.path = urllib.parse.quote(norm_path)
            return super().do_GET()
        return self.send_error(404)

    def do_HEAD(self):
        return self.send_error(405)

    def hotline_post(self, path):
        """Chega pelo túnel (Host de fora). Só /hl/<token>/<ação>; token comparado em tempo constante; corpo limitado."""
        parts = path.split("/")
        if len(parts) != 4 or parts[1] != "hl" or not services().hotline_token_ok(parts[2]) or parts[3] not in ("verify_code", "fetch_brain", "take_message"):
            return self.send_error(404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 8000:
                return self.send_json({"error": "too large"}, 413)
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self.send_json({"error": "bad json"}, 400)
        return self.send_json(services().hotline(parts[3], body))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/hl/"):
            return self.hotline_post(path)
        if not self.local_ok():
            return self.send_error(403)
        if path not in ("/chat", "/remember", "/see", "/tool_chat", "/stage"):
            return self.send_error(404)
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self.send_json({"error": "Content-Type tem de ser application/json."}, 415)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > (4_000_000 if path == "/see" else 20000):
                return self.send_json({"error": "Pedido demasiado grande."}, 413)
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self.send_json({"error": "JSON inválido."}, 400)
        try:
            if path == "/chat":
                q = str(data.get("q", "")).strip()[:1000]
                if not q:
                    return self.send_json({"error": "Pergunta vazia."}, 400)
                return self.send_json(chat(str(data.get("sid", "default"))[:64], q))
            if path == "/tool_chat":
                from jarvis import toolloop
                cfg = load_config()
                return self.send_json(toolloop.run(cfg, BRAIN_MODEL, services().google, str(data.get("q", ""))[:1000]))
            if path == "/stage":
                from jarvis.router import stage_delay
                delay = int(data["delay"]) if str(data.get("delay", "")).isdigit() else stage_delay(str(data.get("sentence", "")))
                return self.send_json(services().stage(delay=max(10, min(delay, 900)), dry=bool(data.get("dry"))))
            if path == "/see":
                return self.send_json(see(str(data.get("sid", "default"))[:64], str(data.get("q", ""))[:500] or "O que vês?", data.get("image")))
            text = str(data.get("text", ""))
            return self.send_json(BRAIN.remember(text))
        except ChatError as e:
            return self.send_json({"error": str(e)}, e.status)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": f"Erro interno ({type(e).__name__})."}, 500)

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port):
    return Server(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    try:
        srv = make_server(PORT)
    except OSError as e:
        sys.exit(f"Não consegui abrir a porta {PORT} ({e}). Tenta: HOLO_PORT={PORT + 1} python3 server.py")
    print(f"HOLO a correr em  http://localhost:{PORT}   (Ctrl+C para parar)")
    JC.secure_all()                                   # config.json e ficheiros de estado a 600
    threading.Thread(target=lambda: services().run_forever(), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nAté já.")
