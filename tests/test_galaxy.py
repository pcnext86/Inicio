# Teste de ponta a ponta da galáxia no browser (precisa de: pip install playwright && playwright install chromium).
# Usa uma API da Anthropic simulada e uma cópia das notas; não toca nas tuas.  python3 tests/test_galaxy.py
import http.server, json, os, pathlib, shutil, subprocess, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright
SRC = pathlib.Path(__file__).resolve().parent.parent
tmp = pathlib.Path(tempfile.mkdtemp()); notes = tmp/"notas"; shutil.copytree(SRC/"notes", notes)
REPLY = {"v": '{"answer":"Uma resposta seca, senhor.","used":[1]}'}
class Mock(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        out=json.dumps({"content":[{"type":"text","text":REPLY["v"]}]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self,*a): pass
mock = http.server.HTTPServer(("127.0.0.1",0),Mock); threading.Thread(target=mock.serve_forever,daemon=True).start()
cfg = tmp/"cfg.json"; cfg.write_text(json.dumps({"api_key":"sk-x","api_url":f"http://127.0.0.1:{mock.server_address[1]}/v1/messages"}))
env = dict(os.environ, HOLO_PORT="4891", HOLO_CONFIG=str(cfg), HOLO_NOTES=str(notes))
srv = subprocess.Popen([sys.executable, str(SRC/"server.py")], env=env, cwd=SRC, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)
results=[]
def check(name, ok, info=""): results.append((name, bool(ok), info)); print(("OK   " if ok else "FALHA"), name, info if not ok else "")
try:
  with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader","--ignore-gpu-blocklist"])
    pg=b.new_page(viewport={"width":1280,"height":720}); logs=[]
    pg.on("console",lambda m: logs.append(m.type+": "+m.text) if m.type in ("error",) else None)
    pg.on("pageerror",lambda e: logs.append("PAGEERROR: "+str(e)))
    pg.goto("http://localhost:4891/?probe=1"); pg.wait_for_function("window.PROBE_RESULTS",timeout=60000)
    pg.evaluate("document.getElementById('probe').style.display='none'")
    pg.evaluate("window.HOLO.toggleGalaxy()")
    pg.wait_for_function("window.GALAXY && window.GALAXY.ready", timeout=30000); pg.wait_for_timeout(2500)
    n = pg.evaluate("GALAXY.data.nodes.length"); check("galáxia carregou as notas", n==11, n)
    check("grafo tem ligações", pg.evaluate("GALAXY.data.links.length")>0)
    greet = pg.inner_text("#gx-answer"); check("saudação com a contagem real", "11 notas na galáxia" in greet, greet)
    check("saudação curta foi falada", any(s.endswith(", senhor.") and len(s) < 30 for s in pg.evaluate("GALAXY.spoken")))
    pg.screenshot(path="/tmp/gx_open.png")
    # tecla G dentro da caixa de texto não fecha nada nem liga efeitos
    pg.click("#gx-in"); pg.keyboard.type("gfjlr"); 
    check("teclas dentro da caixa não disparam atalhos", pg.evaluate("GALAXY.active && !HOLO.S.fx && !HOLO.S.jarvis"))
    pg.fill("#gx-in","")
    cam0 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    # pergunta -> fly-to-source
    pg.fill("#gx-in","O que é o Hub de áudio?"); pg.keyboard.press("Enter")
    pg.wait_for_function("GALAXY.sel!==null", timeout=15000); pg.wait_for_timeout(2200)
    lab = pg.evaluate("GALAXY.data.nodes[GALAXY.sel].label"); check("fly-to-source escolhe a nota principal", lab=="Hub de Audio", lab)
    check("painel lateral mostra o excerto", "Raspberry" in pg.inner_text("#gx-e"))
    check("nota e vizinhas acesas", pg.evaluate("GALAXY.hi.size")>=1)
    check("resposta curta falada", any("seca" in s for s in pg.evaluate("GALAXY.spoken")))
    cam1 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    check("a câmara mexeu", sum(abs(a-b) for a,b in zip(cam0,cam1))>5)
    pg.screenshot(path="/tmp/gx_fly.png")
    # 4+ notas -> aglomerado
    REPLY["v"]='{"answer":"Um panorama vasto, senhor.","used":[1,2,3,4,5]}'
    pg.fill("#gx-in","casa iluminação energia rede rotinas dashboards"); pg.keyboard.press("Enter")
    pg.wait_for_function("GALAXY.sel===null && GALAXY.hi.size>=4", timeout=15000); pg.wait_for_timeout(1800)
    check("4+ notas acendem o aglomerado todo", pg.evaluate("GALAXY.hi.size")>=4)
    pg.screenshot(path="/tmp/gx_cluster.png")
    # conversa fiada não mexe na câmara
    pg.evaluate("GALAXY.reset()"); pg.wait_for_timeout(1200)
    REPLY["v"]='{"answer":"Muito bem, senhor. E o senhor?","used":[]}'
    pg.evaluate("GALAXY.lastTouch=performance.now()+1e9")  # impede a deriva durante a medição
    c0 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    pg.fill("#gx-in","bom dia, conta-me uma piada"); pg.keyboard.press("Enter"); pg.wait_for_timeout(1500)
    c1 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    check("conversa fiada não arrasta a câmara", sum(abs(a-b) for a,b in zip(c0,c1))<1, (c0,c1)); check("conversa fiada não acende nós", pg.evaluate("GALAXY.hi.size")==0)
    check("resposta de conversa fiada é mostrada", "E o senhor" in pg.inner_text("#gx-answer"))
    # lembra-te que
    pg.fill("#gx-in","lembra-te que os cadernos verdes esgotaram"); pg.keyboard.press("Enter")
    pg.wait_for_function("GALAXY.graph.graphData().nodes.length===12", timeout=15000); pg.wait_for_timeout(1800)
    files=list((notes/"captures").glob("*.md")); check("nota real escrita em captures/", len(files)==1 and "cadernos verdes" in files[0].read_text(), files)
    check("nova estrela tem posição (nasce junto de uma relacionada)", pg.evaluate("(()=>{const n=GALAXY.graph.graphData().nodes[11];return Number.isFinite(n.x)&&n.group==='captures'})()"))
    check("nova estrela ficou selecionada (câmara voa até ela)", pg.evaluate("GALAXY.sel===11"))
    check("confirmação em voz alta", any("Anotado" in s for s in pg.evaluate("GALAXY.spoken")))
    pg.screenshot(path="/tmp/gx_remember.png")
    # chave nunca no browser
    html = pg.content(); check("a chave não está no HTML", "sk-x" not in html)
    # mãos: orbitar, zoom, escolher
    pg.evaluate("""()=>{const H=window.HOLO;window.__t=2e5;window.tk=(sp,n=1)=>{for(let i=0;i<n;i++){window.__t+=33.3;H.frame(sp.map(s=>({lm:H.synth(s)})),window.__t);}};GALAXY.lastTouch=performance.now()+1e9;}""")
    d0 = pg.evaluate("GALAXY.graph.camera().position.length()")
    cc0 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    pg.evaluate("""()=>{tk([{x:.4,y:.5,pose:'open'}],4);tk([{x:.4,y:.5,pose:'pinch'}],6);for(let i=1;i<=12;i++)tk([{x:.4+.2*i/12,y:.5,pose:'pinch'}],1);tk([{x:.6,y:.5,pose:'open'}],4);tk([],12);}""")
    cc1 = pg.evaluate("(()=>{const c=GALAXY.graph.camera().position;return [c.x,c.y,c.z]})()")
    check("pinça a arrastar roda a câmara", sum(abs(a-b) for a,b in zip(cc0,cc1))>20, (cc0,cc1))
    d1 = pg.evaluate("GALAXY.graph.camera().position.length()")
    pg.evaluate("""()=>{const a={x:.4,y:.5},b={x:.6,y:.5};tk([{...a,pose:'open'},{...b,pose:'open'}],4);tk([{...a,pose:'pinch'},{...b,pose:'pinch'}],6);for(let i=1;i<=14;i++)tk([{x:.4-.15*i/14,y:.5,pose:'pinch'},{x:.6+.15*i/14,y:.5,pose:'pinch'}],1);tk([{x:.25,y:.5,pose:'open'},{x:.75,y:.5,pose:'open'}],4);tk([],12);}""")
    d2 = pg.evaluate("GALAXY.graph.camera().position.length()")
    check("duas mãos afastadas aproximam (zoom)", d2 < d1-10, (d1,d2))
    pg.evaluate("GALAXY.reset()"); pg.wait_for_timeout(1300)
    sx,sy = pg.evaluate("(()=>{const n=GALAXY.graph.graphData().nodes[3];const p=GALAXY.graph.graph2ScreenCoords(n.x,n.y,n.z);return [p.x/innerWidth,p.y/innerHeight]})()")
    pg.evaluate(f"""()=>{{const p={{x:{sx},y:{sy}}};tk([{{...p,pose:'open'}}],4);tk([{{...p,pose:'pinch'}}],6);tk([{{...p,pose:'open'}}],4);tk([],12);}}""")
    check("pinça rápida escolhe o nó sob o cursor", pg.evaluate("GALAXY.sel")==3, pg.evaluate("GALAXY.sel"))
    pg.evaluate("""()=>{tk([{x:.5,y:.5,pose:'open'}],4);tk([{x:.5,y:.5,pose:'peace'}],30);tk([],12);}"""); pg.wait_for_timeout(500)
    check("paz mantido na galáxia repõe a vista", pg.evaluate("GALAXY.sel===null"))
    # fechar
    pg.evaluate("GALAXY.close()"); check("fechar devolve o HOLO", pg.evaluate("!GALAXY.active && document.getElementById('c2').style.pointerEvents===''"))
    check("sem erros na consola", not logs, logs[:4])
    b.close()
finally:
  srv.terminate(); mock.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
ok=sum(1 for _,o,_ in results if o); print(f"\n{ok}/{len(results)}")
