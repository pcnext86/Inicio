"""Testes do servidor HOLO (sem rede real: a API da Anthropic é simulada).  python3 -m unittest -v tests.test_server"""
import http.client, json, os, pathlib, shutil, sys, tempfile, threading, unittest, http.server

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NOTES = {
    "Clientes/Joana Silva.md": "# Joana Silva\n\nCliente desde 2021. Prefere reuniões à terça-feira. Ver também [[Proposta Alfa]].",
    "Clientes/Proposta Alfa.md": "# Proposta Alfa\n\nOrçamento de 12 mil euros para a Joana Silva. Entrega em março.",
    "Operacoes/Fornecedores.md": "# Fornecedores\n\nPapel reciclado vem da Gráfica Norte. Prazo de pagamento: 30 dias.",
    "Operacoes/Horario da loja.md": "# Horario da loja\n\nAberto das 9h às 19h, fechado ao domingo.",
    "Ideias.md": "# Ideias\n\nLançar uma linha de cadernos reciclados.",
}

class Mock(http.server.BaseHTTPRequestHandler):
    seen = []
    reply = '{"answer": "Uma resposta seca, senhor: a Joana prefere terças.", "used": [1, 2]}'
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.seen.append({"headers": dict(self.headers), "body": body})
        out = json.dumps({"content": [{"type": "text", "text": Mock.reply}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        for rel, txt in NOTES.items():
            p = cls.tmp / "notas" / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt, "utf-8")
        os.environ["HOLO_NOTES"] = str(cls.tmp / "notas")
        cls.cfg = cls.tmp / "cfg.json"; os.environ["HOLO_CONFIG"] = str(cls.cfg)
        import server; cls.server = server
        cls.mock = http.server.HTTPServer(("127.0.0.1", 0), Mock); threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cls.srv = server.make_server(0); cls.port = cls.srv.server_address[1]; threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.mock.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)
    def setUp(self):
        Mock.seen.clear(); self.server.BRAIN.sessions.clear()
        self.cfg.write_text(json.dumps({"api_key": "sk-test-SECRET123", "model": "m-test", "api_url": f"http://127.0.0.1:{self.mock.server_address[1]}/v1/messages"}))

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port); h = {"Host": host or f"localhost:{self.port}"}; h.update(headers or {})
        data = None
        if body is not None: data = json.dumps(body); h.setdefault("Content-Type", "application/json")
        c.request(method, path, data, h); r = c.getresponse(); raw = r.read(); c.close()
        try: return r.status, json.loads(raw)
        except Exception: return r.status, raw

    # ---- segurança
    def test_config_e_codigo_nao_sao_servidos(self):
        for p in ("/config.json", "/config.example.json", "/server.py", "/holo.json", "/notes/Ideias/Painel%20por%20gestos.md", "/tests/test_server.py", "/..%2fconfig.json", "/vendor/../config.json", "/vendor/%2e%2e/config.json", "/vendor/%2e%2e%2fconfig.json", "/props/..%5cconfig.json", "/vendor/./../config.json", "//config.json", "/vendor/three/../../config.json", "/vendor/config.json"):
            self.assertIn(self.req("GET", p)[0], (403, 404), p)
    def test_pagina_principal_e_servida(self):
        s, b = self.req("GET", "/"); self.assertEqual(s, 200); self.assertIn(b"HOLO", b)
    def test_host_estranho_recusado(self):
        self.assertEqual(self.req("GET", "/api/graph", host="evil.example.com")[0], 403)
        self.assertEqual(self.req("POST", "/chat", {"q": "x"}, host="evil.example.com")[0], 403)
    def test_origin_estranha_recusada(self):
        self.assertEqual(self.req("POST", "/remember", {"text": "x"}, headers={"Origin": "https://evil.example.com"})[0], 403)
    def test_post_exige_json(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.request("POST", "/chat", "q=1", {"Host": f"localhost:{self.port}", "Content-Type": "text/plain"}); self.assertEqual(c.getresponse().status, 415)
    def test_chave_nunca_aparece_em_nada_servido(self):
        for p in ("/", "/api/graph", "/api/notes", "/api/props", "/galaxy.js"):
            s, b = self.req("GET", p); raw = b if isinstance(b, bytes) else json.dumps(b).encode(); self.assertNotIn(b"SECRET123", raw, p)
        s, b = self.req("POST", "/chat", {"sid": "k", "q": "joana"}); self.assertNotIn("SECRET123", json.dumps(b))

    # ---- grafo
    def test_grafo_ids_sao_posicoes(self):
        s, g = self.req("GET", "/api/graph"); self.assertEqual(s, 200)
        self.assertEqual(len(g["nodes"]), 5); self.assertEqual([n["id"] for n in g["nodes"]], list(range(5)))
        self.assertTrue(all(len(n["excerpt"]) <= 700 for n in g["nodes"]))
        self.assertEqual({n["group"] for n in g["nodes"]}, {"Clientes", "Operacoes", "raiz"})
    def test_grafo_liga_mencoes_e_wikilinks(self):
        g = self.req("GET", "/api/graph")[1]; by = {n["label"]: n["id"] for n in g["nodes"]}
        pairs = {(l["source"], l["target"]) for l in g["links"]}
        self.assertIn(tuple(sorted((by["Joana Silva"], by["Proposta Alfa"]))), pairs)
        self.assertFalse(any(by["Ideias"] in p for p in pairs))

    # ---- chat
    def test_chat_sem_chave_da_503(self):
        self.cfg.write_text(json.dumps({"api_key": "PUT-YOUR-KEY-HERE"})); s, b = self.req("POST", "/chat", {"q": "joana"}); self.assertEqual(s, 503); self.assertIn("configurado", b["error"])
    def test_chat_devolve_resposta_e_indices_dos_nos(self):
        g = self.req("GET", "/api/graph")[1]; s, b = self.req("POST", "/chat", {"sid": "a", "q": "Quando prefere reunir a Joana Silva?"})
        self.assertEqual(s, 200); self.assertIn("Joana", b["answer"]); self.assertTrue(b["nodes"]); self.assertTrue(all(0 <= i < len(g["nodes"]) for i in b["nodes"]))
        top = g["nodes"][b["nodes"][0]]["label"]; self.assertIn(top, ("Joana Silva", "Proposta Alfa"))
    def test_chat_usa_so_notas_relevantes_e_titulo_pesa_mais(self):
        self.req("POST", "/chat", {"sid": "b", "q": "fornecedores"}); sent = Mock.seen[-1]["body"]["messages"][-1]["content"]
        self.assertIn("Fornecedores", sent); self.assertNotIn("Horario da loja", sent); self.assertIn("[1] Fornecedores", sent)
    def test_chat_cabecalhos_e_modelo(self):
        self.req("POST", "/chat", {"sid": "c", "q": "joana"}); m = Mock.seen[-1]
        self.assertEqual({k.lower(): v for k, v in m["headers"].items()}.get("x-api-key"), "sk-test-SECRET123"); self.assertEqual(m["body"]["model"], "m-test"); self.assertIn("JARVIS", m["body"]["system"]); self.assertIn("senhor", m["body"]["system"])
    def test_chat_historico_por_sessao(self):
        self.req("POST", "/chat", {"sid": "s1", "q": "joana"}); self.req("POST", "/chat", {"sid": "s1", "q": "e o orçamento?"})
        msgs = Mock.seen[-1]["body"]["messages"]; self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"]); self.assertEqual(msgs[0]["content"], "joana")
        self.req("POST", "/chat", {"sid": "s2", "q": "joana"}); self.assertEqual(len(Mock.seen[-1]["body"]["messages"]), 1)
    def test_conversa_fiada_nao_move_a_camara(self):
        Mock.reply = '{"answer": "Muito bem, senhor. E o senhor?", "used": []}'
        try: s, b = self.req("POST", "/chat", {"sid": "t", "q": "bom dia, conta-me uma piada"}); self.assertEqual(b["nodes"], [])
        finally: Mock.reply = '{"answer": "Uma resposta seca, senhor: a Joana prefere terças.", "used": [1, 2]}'
    def test_resposta_do_modelo_fora_de_json_nao_rebenta(self):
        Mock.reply = "Apenas texto simples, senhor."
        try: s, b = self.req("POST", "/chat", {"sid": "u", "q": "joana"}); self.assertEqual(s, 200); self.assertEqual(b["answer"], "Apenas texto simples, senhor."); self.assertEqual(b["nodes"], [])
        finally: Mock.reply = '{"answer": "Uma resposta seca, senhor: a Joana prefere terças.", "used": [1, 2]}'
    def test_indice_inventado_pelo_modelo_e_ignorado(self):
        Mock.reply = '{"answer": "ok", "used": [99, 1, 1, 0]}'
        try: s, b = self.req("POST", "/chat", {"sid": "v", "q": "joana"}); self.assertEqual(len(b["nodes"]), 1)
        finally: Mock.reply = '{"answer": "Uma resposta seca, senhor: a Joana prefere terças.", "used": [1, 2]}'
    def test_erro_da_api_vira_mensagem(self):
        self.cfg.write_text(json.dumps({"api_key": "k", "api_url": "http://127.0.0.1:9/x"})); s, b = self.req("POST", "/chat", {"q": "joana"}); self.assertEqual(s, 502); self.assertNotIn("Traceback", b["error"])
    def test_cli_provider(self):
        fake = self.tmp / "fakeclaude"; fake.write_text('#!/bin/sh\necho \'{"answer":"via cli, senhor","used":[1]}\'\n'); fake.chmod(0o755)
        self.cfg.write_text(json.dumps({"provider": "claude-cli", "claude_cli": str(fake)})); s, b = self.req("POST", "/chat", {"q": "joana"}); self.assertEqual((s, b["answer"]), (200, "via cli, senhor"))

    # ---- remember
    def test_remember_escreve_nota_em_captures_e_devolve_no(self):
        n0 = len(self.req("GET", "/api/graph")[1]["nodes"])
        s, b = self.req("POST", "/remember", {"text": "lembra-te que a Joana Silva quer entrega em abril"}); self.assertEqual(s, 200)
        f = self.tmp / "notas" / "captures"; files = [p for p in f.glob("*.md") if "joana-silva" in p.name]; self.assertEqual(len(files), 1)
        txt = files[0].read_text("utf-8"); self.assertIn("quer entrega em abril", txt); self.assertNotIn("lembra-te", txt)
        self.assertEqual(b["node"]["id"], n0); self.assertEqual(b["node"]["group"], "captures"); self.assertIsNotNone(b["near"]); self.assertTrue(b["links"])
        g = self.req("GET", "/api/graph")[1]; self.assertEqual(len(g["nodes"]), n0 + 1)
    def test_remember_nao_sobrescreve_e_aceita_ingles(self):
        for _ in range(2): self.req("POST", "/remember", {"text": "remember that prompt packs make great gifts"})
        self.assertEqual(len(list((self.tmp / "notas" / "captures").glob("*prompt-packs*"))), 2)
    def test_remember_titulo_seguro_e_vazio_recusado(self):
        s, b = self.req("POST", "/remember", {"text": "lembra-te que ../../etc/passwd é um sítio"}); self.assertEqual(s, 200)
        for p in (self.tmp / "notas" / "captures").glob("*.md"): self.assertEqual(p.parent.resolve(), (self.tmp / "notas" / "captures").resolve()); self.assertNotIn("/", p.name)
        self.assertEqual(self.req("POST", "/remember", {"text": "lembra-te que"})[0], 400)
        self.assertEqual(self.req("POST", "/remember", {"text": "   "})[0], 400)
    def test_graph_e_chat_vem_do_mesmo_estado_apos_remember(self):
        self.req("GET", "/api/graph"); self.req("POST", "/remember", {"text": "lembra-te que os cadernos verdes esgotaram"})
        g = self.req("GET", "/api/graph")[1]; self.assertEqual([n["id"] for n in g["nodes"]], list(range(len(g["nodes"]))))

if __name__ == "__main__":
    unittest.main(verbosity=2)
