import json, sys, threading, http.server, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from jarvis import llm

class Mock(http.server.BaseHTTPRequestHandler):
    bodies = []; replies = []
    def do_POST(self):
        n = int(self.headers["Content-Length"]); Mock.bodies.append(json.loads(self.rfile.read(n)))
        out = json.dumps(Mock.replies.pop(0) if Mock.replies else {"content": [{"type": "text", "text": "ok"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

@pytest.fixture
def api():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Mock); Mock.bodies = []; Mock.replies = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"anthropic_api_key": "sk-test", "api_base": f"http://127.0.0.1:{srv.server_address[1]}"}
    srv.shutdown()

def test_opus_rules(api):
    llm.call_claude(api, "claude-opus-5-5", "s", [{"role": "user", "content": "oi"}], effort="medium", max_tokens=300)
    b = Mock.bodies[0]
    assert "thinking" not in b and "tool_choice" not in b
    assert b["output_config"] == {"effort": "medium"}

def test_max_tokens_floor_in_chat(api):
    llm.complete(api, llm.Brain(), "s", [{"role": "user", "content": "oi"}])
    assert Mock.bodies[0]["max_tokens"] >= 2000

def test_haiku_no_effort(api):
    llm.call_claude(api, "claude-haiku-4-5", "s", [{"role": "user", "content": "oi"}])
    assert "output_config" not in Mock.bodies[0]

def test_tools_never_force_choice(api):
    llm.call_claude(api, "claude-opus-5-5", "s", [{"role": "user", "content": "oi"}], tools=[{"name": "x", "description": "d", "input_schema": {"type": "object"}}])
    assert "tool_choice" not in Mock.bodies[0]

def test_empty_text_retries_with_more_tokens(api):
    Mock.replies = [{"content": [{"type": "thinking", "thinking": "..."}], "stop_reason": "max_tokens"}]
    r = llm.call_claude(api, "claude-opus-5-5", "s", [{"role": "user", "content": "oi"}], max_tokens=2000)
    assert len(Mock.bodies) == 2 and Mock.bodies[1]["max_tokens"] == 4000 and llm.text_of(r["content"]) == "ok"

def test_placeholder_key_is_503():
    with pytest.raises(llm.LLMError) as e:
        llm.call_claude({"anthropic_api_key": "PUT-YOUR-KEY-HERE"}, "claude-opus-5-5", "s", [])
    assert e.value.status == 503

@pytest.mark.parametrize("said,expect", [
    ("try on Opus 5", ("swap", "claude-opus-5")), ("switch to Fable 5.1", ("swap", "claude-fable-5-1")),
    ("experimenta o opus5", ("swap", "claude-opus-5")), ("use haiku", ("swap", "claude-haiku-4-5")),
    ("try on opus 6", ("refuse", None)), ("try on opus", ("refuse", None)), ("go back to your normal brain", ("reset", None)),
])
def test_model_requests(said, expect):
    r = llm.parse_model_request(said)
    assert r["action"] == expect[0] and (expect[1] is None or r["id"] == expect[1])

def test_not_a_swap():
    assert llm.parse_model_request("bom dia") is None


def test_see_builds_image_block(api, monkeypatch, tmp_path):
    import server, json as j
    cfgp = tmp_path / "c.json"; cfgp.write_text(j.dumps(api)); monkeypatch.setenv("HOLO_CONFIG", str(cfgp))
    r = server.see("s", "o que vês?", "QUJD")
    img = Mock.bodies[-1]["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/jpeg" and r["answer"] == "ok"
    with pytest.raises(server.ChatError):
        server.see("s", "x", "<script>")
