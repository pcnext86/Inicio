"""Depois da chamada: transcrição -> instruções (JSON estrito) -> executar -> UMA confirmação entregue uma só vez.
Também: call_me, 'chama-me se', palco, lembretes, briefing e hotline."""
import json
import re
import time

from . import llm as LLM, toolloop
from .router import route, standing_ack, stage_delay
from .telephony import transcript_text

SCENARIOS = [
    ("Your biggest client just replied", "They signed the proposal a few minutes ago. They want a kickoff call early next week."),
    ("A double-booking on your calendar", "Two meetings overlap tomorrow afternoon. One of them is with your accountant."),
    ("A payment just landed", "The invoice you sent last week was paid in full a few minutes ago."),
    ("A caller left a message", "Someone from the dental clinic phoned a few minutes ago and asked you to confirm your appointment."),
]
EXTRACT_SYSTEM = ("Extrais APENAS as instruções do senhor a partir da transcrição de uma chamada, como JSON estrito: {\"instructions\": [\"...\"]}. "
                  "Uma verificação e a ação que ela condiciona são UMA instrução ('vê o calendário e, se não houver conflito, marca o kickoff segunda às 10' é uma só). "
                  "Resolve referências para cada instrução se aguentar sozinha, com a data real (hoje é {today}). Agradecimentos e perguntas não são instruções; "
                  "as ofertas do próprio Jarvis só contam se o senhor as aceitou. Se não houver instruções: {\"instructions\": []}. Só JSON.")
CONFIRM_SYSTEM = ("Condensa os resultados em UMA ou DUAS frases faladas, em inglês de mordomo, que começam pelo resultado: "
                  "'Done, sir. Checked your calendar, Monday at ten was clear, so the kickoff is booked.' Nunca repitas as instruções nem listes passos. "
                  "Se algo falhou ou houve conflito, di-lo claramente e que nada foi marcado. Só afirmes o que tem recibo (id ou link).")


def parse_instructions(text):
    m = re.search(r"\{[\s\S]*\}", text or "")
    try:
        items = json.loads(m.group(0)).get("instructions", []) if m else []
    except ValueError:
        return []
    return [str(i).strip() for i in items if str(i).strip()][:5]


def extract_instructions(cfg, brain, transcript):
    data, _ = LLM.complete(cfg, brain, EXTRACT_SYSTEM.replace("{today}", time.strftime("%A %Y-%m-%d")), [{"role": "user", "content": transcript}], effort="low")
    return parse_instructions(LLM.text_of(data.get("content", [])))


def after_call(cfg, brain, google, desk, pocket, call, now=None):
    """Chamada terminou -> ações -> uma confirmação. O cartão da própria chamada fica mudo e nunca vai ao telemóvel."""
    tr = transcript_text(call)
    desk.card("Chamada terminada.", silent=True, source="call")
    instr = extract_instructions(cfg, brain, tr) if tr else []
    if not instr:
        return {"instructions": [], "confirmation": None}
    outcomes = []
    for i in instr:
        r = toolloop.run(cfg, brain, google, i, pre_approved=True)
        outcomes.append({"instruction": i, "result": r["answer"], "receipts": r["receipts"]})
    data, _ = LLM.complete(cfg, brain, CONFIRM_SYSTEM, [{"role": "user", "content": json.dumps(outcomes, ensure_ascii=False)}], effort="low")
    line = LLM.text_of(data.get("content", [])).strip() or "Done, sir."
    card = desk.card(line, priority="normal", source="after-call")        # primeiro o cartão da secretária...
    if pocket is not None:
        pocket.report(card)                                                 # ...e só depois o Telegram, com o id dele
    return {"instructions": instr, "confirmation": line, "card": card["id"], "outcomes": outcomes}


def standing_brief(desk):
    p = desk.context_pack()
    return ("Standing brief", [f"Today is {p['date']}.", ("Open on the desk: " + "; ".join(p["open_items"])) if p["open_items"] else "Nothing is open on the desk."])


def handle_sentence(sentence, desk, call_fn):
    """Decide o que fazer com uma frase ACABADA sobre chamadas. Devolve (label, resposta) ou None."""
    label = route(sentence)
    if label == "standing":
        desk.arm_urgent(True)
        return "standing", standing_ack(sentence)            # nunca liga
    if label == "call_me":
        h, n = standing_brief(desk)
        call_fn(h, n)
        return "call_me", "A ligar-lhe agora, senhor."
    if label == "stage":
        return "stage", stage_delay(sentence)
    return None


# ------------------------------------------------------------ lembretes e briefing por voz
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "um": 1, "dois": 2, "tres": 3, "cinco": 5, "dez": 10, "vinte": 20, "trinta": 30}


def desk_command(sentence, desk, now=None):
    """'in twenty minutes give me a reminder call about X', 'text me instead', 'call me with the briefing every morning at 8',
    'stop the morning calls', 'pocket code'. Devolve resposta ou None."""
    from .router import n
    t = n(sentence); now = now or desk.clock()
    if re.search(r"(stop|cancel|para|cancela) (the )?(morning|as chamadas da manha|chamadas da manha)", t):
        desk.cancel_briefing(); return "Very good, sir. The morning calls are cancelled."
    m = re.search(r"(?:every morning|every day|todas as manhas|todos os dias).{0,40}?(?:at|as|às) (\d{1,2})(?::(\d{2}))?", t) or re.search(r"(?:at|as) (\d{1,2})(?::(\d{2}))? (?:every morning|every day|todas as manhas)", t)
    if m and re.search(r"call|ring|liga|chama", t) and 0 <= int(m.group(1)) <= 23:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        desk.set_briefing(h, mi); return f"Scheduled, sir: the briefing call every morning at {h:02d}:{mi:02d}."
    m = re.search(r"(?:in|em) (\d+|[a-z]+) (minute|minuto|hour|hora)s? .*?(reminder|lembrete|remind)(?: call)?(?: about| sobre| de)? ?(.*)", t)
    if m and re.search(r"reminder|lembrete|remind", t):
        v = int(m.group(1)) if m.group(1).isdigit() else _NUM.get(m.group(1))
        if v:
            secs = v * (3600 if m.group(2).startswith(("hour", "hora")) else 60)
            channel = "text" if re.search(r"text me|manda.me mensagem|telegram", t) else "call"
            desk.add_reminder(now + secs, (m.group(4) or "a reminder").strip(" .") or "a reminder", channel)
            return f"Very good, sir. I'll {'text' if channel == 'text' else 'ring'} you in {v} {m.group(2)}{'s' if v != 1 else ''}."
    return None
