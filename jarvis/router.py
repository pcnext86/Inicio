"""Encaminhamento de frases sobre chamadas. A ordem importa: ordem permanente ANTES de ligar.
Rótulos: standing | call_me | stage | business | nothing"""
import re
import unicodedata


def n(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("’", "'"))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


# "só me ligues se...", "don't call me unless", "only call me if", "bug me only if it's on fire"
STANDING = re.compile(
    r"(only (call|ring|phone|bug) me (if|for|when)|(call|ring|phone|bug) me only|(don'?t|do not|nao) (call|ring|phone|me ligues|me chames)( me)? (unless|a nao ser|se nao|exceto)"
    r"|(call|ring|phone) me (if|unless|when|in case)|(so|apenas) (me )?(liga|chama|telefona)\w* (se|para|quando|em caso)|(liga|chama|telefona)-?(me)? (so|apenas) (se|para|quando)"
    r"|nao (me )?(ligues|chames|telefones) (a nao ser|exceto|se nao)|bug me (only )?if)")
# a rota que liga recusa condicionais, negações e o substantivo "call"
CALL_REFUSE = re.compile(r"(call|ring|phone|liga|chama|telefona)\w*[- ]?(me)? (if|unless|when|in case|only|se |quando|a nao ser)|(don'?t|do not|nao) (call|ring|phone|ligues|chames)|(a|the|my|an|on a|have a|um|uma|na|numa|tenho uma?) (phone )?(call|chamada|ligacao)|(on|in) a call|chamada (as|a)")
CALL_ME = re.compile(r"^(?:(?:hey |ola |ok )?jarvis[, ]+)?(?:please |por favor )?(?:(?:can you |could you |podes |consegues )?(?:call|ring|phone|liga|chama|telefona)(?:[- ]me| a mim| ao? senhor)?(?: now| right now| agora)?|(?:call|ring) me up)(?: please| por favor)?[.!?]*$")
BRIEFING_NOW = re.compile(r"(call|ring|liga|chama)\w*[- ]?(me)? (with|com) (the |o )?(briefing|resumo)( now| agora)?")
BUSINESS = re.compile(r"\b(call|ring|phone|liga|telefona) (to |para )?(the |a |o )?(?!me\b)(?:[a-z0-9]+ ){0,3}(restaurant|restaurante|dentist|dentista|hotel|clinic|clinica|barber|barbeiro|office|escritorio|shop|loja|plumber|canalizador|bank|banco)")
STAGE = re.compile(r"\b(stage|estagia|encena|simula|georgia state)\b.*\b(urgent|urgente)?\s*(call|chamada|ligacao)")


def route(sentence):
    t = n(sentence)
    if STANDING.search(t):
        return "standing"          # PRIMEIRO: nunca liga
    if STAGE.search(t) or t.startswith(("stage an urgent", "jarvis stage", "georgia state")):
        return "stage"
    if BRIEFING_NOW.search(t):
        return "call_me"
    if BUSINESS.search(t) and not CALL_REFUSE.search(t):
        return "business"
    if CALL_REFUSE.search(t):
        return "nothing"           # recusa explícita da rota de ligar
    if CALL_ME.match(t):
        return "call_me"
    return "nothing"


def standing_ack(sentence):
    t = n(sentence)
    if re.search(r"meeting|reuniao|reunioes|emergenc|emergencia", t):
        return "Very good, sir. Have a good meeting, I'll only ring you if it can't wait."
    if re.search(r"sleep|bed|dormir|deitar|good night|boa noite", t):
        return "Sleep well, sir. I'll only ring you if it can't wait."
    if re.search(r"leav|going out|heading out|saio|vou sair|vou embora|a sair", t):
        return "I'll hold the fort, sir."
    return "Very good, sir. I'll only ring you if it can't wait."


def stage_delay(sentence, default=90):
    """'in ten seconds' / 'in three minutes' / 'em dois minutos'. Devolve segundos (10..900)."""
    t = n(sentence)
    words = {"a": 1, "one": 1, "um": 1, "uma": 1, "two": 2, "dois": 2, "duas": 2, "three": 3, "tres": 3, "four": 4, "quatro": 4, "five": 5, "cinco": 5,
             "ten": 10, "dez": 10, "fifteen": 15, "quinze": 15, "twenty": 20, "vinte": 20, "thirty": 30, "trinta": 30}
    m = re.search(r"(?:in|em) (\d+|[a-z]+) (second|segundo|minute|minuto)", t)
    if not m:
        return default
    v = int(m.group(1)) if m.group(1).isdigit() else words.get(m.group(1))
    if v is None:
        return default
    secs = v * (60 if m.group(2).startswith("min") else 1)
    return max(10, min(secs, 900))


TABLE = [
    ("I'm leaving, only call me if anything urgent comes up", "standing"),
    ("Okay Jarvis, I'm going into a meeting, call me only for emergencies", "standing"),
    ("Don't call me unless it's urgent", "standing"),
    ("I'm off to bed, only ring me if the house is on fire", "standing"),
    ("Only bug me if it's on fire", "standing"),
    ("Call me if anything comes up", "standing"),
    ("Call me when the build finishes", "standing"),
    ("Jarvis, call me", "call_me"),
    ("Call me now", "call_me"),
    ("Ring me up", "call_me"),
    ("Call me with the briefing now", "call_me"),
    ("Liga-me agora", "call_me"),
    ("Call the dentist", "business"),
    ("Please call the restaurant and book a table", "business"),
    ("Stage an urgent call in two minutes", "stage"),
    ("Georgia State, an urgent call in ten seconds", "stage"),
    ("I have a call at 3", "nothing"),
    ("I'm on a call for an hour", "nothing"),
    ("Don't call me", "nothing"),
    ("What's the weather today?", "nothing"),
    ("The call went well", "nothing"),
]
