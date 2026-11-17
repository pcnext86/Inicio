"""Chamadas ao Claude (API Anthropic, claude -p ou OpenRouter) e troca de cérebro por voz.

Regras do Opus 5.5 respeitadas aqui:
  - o "thinking" está sempre ligado neste modelo: NUNCA se envia thinking desligado;
  - NUNCA se força tool_choice (é rejeitado);
  - o esforço vai em output_config.effort, por rota (Haiku não aceita esforço);
  - max_tokens cobre o pensamento E a resposta: mínimo 2000 no chat, e uma repetição com orçamento maior se vier texto vazio.
"""
import json
import re
import subprocess
import threading
import unicodedata
import urllib.error
import urllib.request

from . import config as C

ANTHROPIC_URL = "https://api.anthropic.com"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CHAT_MIN_TOKENS = 2000

# ---------------------------------------------------------------- nomes falados -> ids exatos
# UM só dicionário com as manias de cada modelo ao lado (sem esforço = Haiku).
KNOWN_MODELS = {
    "claude-opus-5-5": {"family": "opus", "version": "5.5", "effort": True},
    "claude-opus-5": {"family": "opus", "version": "5", "effort": True},
    "claude-fable-5-2": {"family": "fable", "version": "5.2", "effort": True},
    "claude-fable-5-1": {"family": "fable", "version": "5.1", "effort": True},
    "claude-sonnet-5-5": {"family": "sonnet", "version": "5.5", "effort": True},
    "claude-sonnet-5": {"family": "sonnet", "version": "5", "effort": True},
    "claude-haiku-5-5": {"family": "haiku", "version": "5.5", "effort": False},
    "claude-haiku-4-5": {"family": "haiku", "version": "4.5", "effort": False},
    "openai/gpt-6-astra": {"family": "astra", "version": "", "effort": False, "openrouter": True},
}
# Nomes que se dizem sem versão e que o pack mapeia de forma explícita (nada de "mais parecido").
BARE_NAMES = {"haiku": "claude-haiku-4-5", "astra": "openai/gpt-6-astra"}

_FAMILY = r"(opus|fable|sonnet|haiku|astra)"
_SWAP_VERB = r"(?:try on|try|switch to|swap to|change to|go to|use|experimenta|usa|muda para|mudar para|passa para|troca para|troca por)"
_BACK = r"(?:go back to (?:your )?(?:normal|default|usual) brain|back to (?:your )?(?:normal|default) brain|volta (?:ao|para o) (?:teu )?(?:cerebro )?(?:normal|habitual|por defeito)|volta ao normal)"


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def parse_model_request(text):
    """-> {"action": "swap", "id": ...} | {"action": "reset"} | {"action": "refuse", "wanted": ...} | None.
    Lê a versão logo a seguir à família (inclui formas coladas como 'opus5'), constrói o id candidato e
    confere-o com o conjunto conhecido. Se não existir: RECUSA. Nunca cai para o mais próximo."""
    t = norm(text)
    if re.search(_BACK, t):
        return {"action": "reset"}
    m = re.search(_SWAP_VERB + r"\s+(?:o |a |the |your |teu )?" + _FAMILY + r"(?![a-z])\s*-?\s*(\d+)?(?:\s*[.\-,]\s*(\d+)|\s+(\d)(?!\d))?", t)
    if not m:
        return None
    fam, major, minor1, minor2 = m.group(1), m.group(2), m.group(3), m.group(4)
    minor = minor1 or minor2
    if major is None:
        if fam in BARE_NAMES:
            return {"action": "swap", "id": BARE_NAMES[fam]}
        return {"action": "refuse", "wanted": fam, "why": "version"}
    version = major + ("." + minor if minor else "")
    if fam == "astra":
        return {"action": "swap", "id": BARE_NAMES["astra"]} if not major else {"action": "refuse", "wanted": f"astra {version}", "why": "unknown"}
    candidate = f"claude-{fam}-{version.replace('.', '-')}"
    if candidate in KNOWN_MODELS:
        return {"action": "swap", "id": candidate}
    return {"action": "refuse", "wanted": f"{fam} {version}", "why": "unknown"}


def pretty(model_id):
    """claude-opus-5-5 -> OPUS 5.5 (só um hífen entre dois dígitos é ponto de versão)."""
    s = model_id.replace("claude-", "").split("/")[-1]
    s = re.sub(r"(?<=\d)-(?=\d)", ".", s).replace("-", " ")
    return s.upper()


class Brain:
    """Qual é o modelo ativo. A troca é só em runtime: reiniciar volta sempre ao do config.json."""

    def __init__(self):
        self.override = None
        self.lock = threading.Lock()

    def current(self, cfg):
        return self.override or cfg.get("model") or "claude-opus-5-5"

    def swap(self, model_id):
        with self.lock:
            self.override = model_id

    def reset(self):
        with self.lock:
            self.override = None


class LLMError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg)
        self.status = status


def _post(url, headers, body, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            j = json.loads(e.read().decode())
            detail = (j.get("error") or {}).get("message", "") if isinstance(j.get("error"), dict) else str(j.get("error", ""))
        except Exception:
            pass
        raise LLMError(f"A API respondeu {e.code}. {detail}".strip(), 502)
    except Exception as e:
        raise LLMError(f"Não consegui falar com a API ({type(e).__name__}).", 502)


def api_base(cfg):
    base = cfg.get("api_base")
    if base:
        return base.rstrip("/")
    url = cfg.get("api_url")  # compatibilidade: URL completo do /v1/messages
    if url:
        return re.sub(r"/v1/messages/?$", "", url).rstrip("/")
    return ANTHROPIC_URL


def text_of(blocks):
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def call_claude(cfg, model, system, messages, effort="medium", max_tokens=CHAT_MIN_TOKENS, tools=None):
    """Devolve o dict da resposta (content = lista de blocos). Opus 5.5: ver as regras no topo do ficheiro."""
    key = C.anthropic_key(cfg)
    if not key:
        raise LLMError("Modelo não configurado: escreve a tua chave em config.json (ver README), senhor.", 503)
    meta = KNOWN_MODELS.get(model, {"effort": True})
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
    if meta.get("effort") and effort:
        body["output_config"] = {"effort": effort}
    if tools:
        body["tools"] = tools          # tool_choice fica SEMPRE em auto (nunca se envia)
    url = api_base(cfg) + "/v1/messages"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    data = _post(url, headers, body)
    if not tools and not text_of(data.get("content", [])).strip():   # pensamento comeu o orçamento: repetir uma vez com mais
        body["max_tokens"] = max_tokens * 2
        data = _post(url, headers, body)
    return data


def call_openrouter(cfg, model, system, messages, max_tokens=CHAT_MIN_TOKENS):
    key = cfg.get("openrouter_api_key")
    if not C.is_real(key):
        raise LLMError("Para esse cérebro preciso de uma chave OpenRouter em config.json, senhor.", 503)
    url = cfg.get("openrouter_url") or OPENROUTER_URL
    data = _post(url, {"Authorization": "Bearer " + key}, {"model": model, "max_tokens": max_tokens, "messages": [{"role": "system", "content": system}] + messages})
    try:
        return {"content": [{"type": "text", "text": data["choices"][0]["message"]["content"] or ""}]}
    except (KeyError, IndexError, TypeError):
        raise LLMError("Resposta inesperada do OpenRouter.")


def call_cli(cfg, system, messages):
    convo = "\n\n".join(("Utilizador: " if m["role"] == "user" else "JARVIS: ") + (m["content"] if isinstance(m["content"], str) else text_of(m["content"])) for m in messages)
    prompt = system + "\n\n" + convo + "\n\nResponde agora."
    try:
        r = subprocess.run([cfg.get("claude_cli", "claude"), "-p", prompt], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise LLMError("Não encontrei o comando `claude` (Claude Code).", 503)
    except subprocess.TimeoutExpired:
        raise LLMError("O `claude -p` demorou demasiado.")
    if r.returncode != 0:
        raise LLMError("O `claude -p` falhou: " + (r.stderr or "").strip()[:200])
    return {"content": [{"type": "text", "text": r.stdout}]}


def complete(cfg, brain, system, messages, effort="medium", max_tokens=CHAT_MIN_TOKENS, tools=None):
    """Ponto único de entrada: escolhe API Anthropic, OpenRouter ou claude -p conforme o modelo/config."""
    model = brain.current(cfg)
    if cfg.get("provider") == "claude-cli" and not brain.override:
        return call_cli(cfg, system, messages), model
    if KNOWN_MODELS.get(model, {}).get("openrouter") or "/" in model:
        return call_openrouter(cfg, model, system, messages, max_tokens), model
    return call_claude(cfg, model, system, messages, effort, max_tokens, tools), model


def models_api_check(cfg, model_id):
    """GET /v1/models/{id}: o modelo existe para ESTA chave? (usado no preflight)"""
    key = C.anthropic_key(cfg)
    req = urllib.request.Request(api_base(cfg) + "/v1/models/" + urllib.parse.quote(model_id, safe=""), headers={"x-api-key": key or "", "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


import urllib.parse  # noqa: E402  (usado acima em models_api_check)
