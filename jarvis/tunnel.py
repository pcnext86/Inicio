"""Túnel rápido do cloudflared + religação automática do agente de entrada. NÃO foi testado contra o Retell real."""
import re
import subprocess
import threading

from . import config as C
from .telephony import INBOUND_PROMPT


def tool_defs(base_url, token):
    u = f"{base_url}/hl/{token}"
    obj = lambda props, req: {"type": "object", "properties": props, "required": req}
    return [
        {"type": "end_call", "name": "end_call", "description": "End the call after the goodbye."},
        {"type": "custom", "name": "verify_code", "url": f"{u}/verify_code", "description": "Send the digits the caller spoke as their passcode.", "speak_during_execution": False, "parameters": obj({"code": {"type": "string"}}, ["code"])},
        {"type": "custom", "name": "fetch_brain", "url": f"{u}/fetch_brain", "description": "Ask the desk about notes, calendar or mail. Works only after verify_code succeeded.", "parameters": obj({"question": {"type": "string"}}, ["question"])},
        {"type": "custom", "name": "take_message", "url": f"{u}/take_message", "description": "Record a message from an unverified caller.", "parameters": obj({"message": {"type": "string"}}, ["message"])},
    ]


def repoint(retell, inbound_llm_id, url, token):
    """Só os URLs das ferramentas mudam quando o endereço do túnel muda. O endereço nunca entra no prompt."""
    return retell._req("PATCH", f"/update-retell-llm/{inbound_llm_id}", {"general_prompt": INBOUND_PROMPT, "general_tools": tool_defs(url, token)})


def run_cloudflared(port, on_url):
    """cloudflared tunnel --url http://localhost:PORT ; chama on_url(url) sempre que aparece um endereço."""
    p = subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://localhost:{port}"], stderr=subprocess.PIPE, text=True)
    def reader():
        for line in p.stderr:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m:
                on_url(m.group(0))
    threading.Thread(target=reader, daemon=True).start()
    return p
