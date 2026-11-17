/* Galáxia JARVIS: as tuas notas como um universo 3D, com cérebro, voz, fly-to-source e "lembra-te que...".
   Carregado ao carregar na tecla G. Usa o mesmo three do HOLO e o 3d-force-graph local (sem CDN). */
import * as THREE from 'three';
import ForceGraph3D from './vendor/force-graph3d.js';

const $ = id => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const SID = Math.random().toString(36).slice(2);

const G = {active: false, ready: false, graph: null, data: null, sel: null, hi: new Set(), busy: false, greeted: false,
  lastTouch: performance.now(), adj: new Map(), spoken: []};
window.GALAXY = G;

/* ---------- interface ---------- */
let root, bar, input, micBtn, statusEl, answerEl, panel;
function buildUI() {
  root = document.createElement('div');
  root.id = 'galaxy';
  root.innerHTML = `
    <div id="gx-graph"></div>
    <div id="gx-panel"><button id="gx-x" title="fechar">×</button><h3 id="gx-t"></h3><div id="gx-g"></div><p id="gx-e"></p></div>
    <div id="gx-answer"></div>
    <div id="gx-bar">
      <div id="gx-status"></div>
      <form id="gx-form" autocomplete="off">
        <button type="button" id="gx-mic" title="Falar (microfone)">🎙</button>
        <input id="gx-in" type="text" placeholder="Pergunte às suas notas, senhor…   ou:  lembra-te que…" maxlength="500">
        <button type="button" id="gx-eye" title="Ver o meu ecrã (partilha de ecrã, só quando clicas)">👁</button>
        <button type="submit" id="gx-go">↵</button>
      </form>
    </div>`;
  document.body.appendChild(root);
  input = $('gx-in'); micBtn = $('gx-mic'); statusEl = $('gx-status'); answerEl = $('gx-answer'); panel = $('gx-panel');
  $('gx-form').addEventListener('submit', e => { e.preventDefault(); const q = input.value.trim(); input.value = ''; ask(q); });
  micBtn.addEventListener('click', toggleMic);
  $('gx-eye').addEventListener('click', () => see(input.value.trim() || 'O que estás a ver no meu ecrã?'));
  $('gx-x').addEventListener('click', () => { clearSelection(); });
  for (const ev of ['pointerdown', 'wheel', 'keydown']) root.addEventListener(ev, () => { G.lastTouch = performance.now(); unlockAudio(); }, {passive: true});
}
const status = t => { if (statusEl) statusEl.textContent = t || ''; };

/* ---------- cores e brilho ---------- */
const colorOf = (g) => { let h = 0; for (const c of g) h = (h * 31 + c.charCodeAt(0)) % 360; return new THREE.Color().setHSL(h / 360, 0.85, 0.62); };
let glowTex = null;
function glow() {
  if (glowTex) return glowTex;
  const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d');
  const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(.25, 'rgba(255,255,255,.65)'); g.addColorStop(.6, 'rgba(255,255,255,.12)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c); return glowTex;
}
const BASE = 26;
function makeNode(n) {
  const m = new THREE.SpriteMaterial({map: glow(), color: colorOf(n.group), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false});
  const s = new THREE.Sprite(m); s.scale.setScalar(BASE); n.__s = s; return s;
}
function applyHighlight() {
  const data = G.graph.graphData(), any = G.hi.size > 0, now = performance.now();
  for (const n of data.nodes) {
    const s = n.__s; if (!s) continue;
    const on = G.hi.has(n.id), top = G.sel === n.id;
    const pulse = n.__born ? Math.max(0, 1 - (now - n.__born) / 3000) : 0;
    s.scale.setScalar((top ? BASE * 2.6 : on ? BASE * 1.7 : BASE) * (1 + pulse * 2.2));
    s.material.opacity = any && !on ? .28 : 1;
  }
  G.graph.linkColor(G.graph.linkColor()); // força o refresco das cores das ligações
}

/* ---------- carregar ---------- */
async function load() {
  const r = await fetch('/api/graph'); const d = await r.json();
  G.data = d; G.adj = new Map(d.nodes.map(n => [n.id, new Set()]));
  for (const l of d.links) { G.adj.get(l.source)?.add(l.target); G.adj.get(l.target)?.add(l.source); }
  const el = $('gx-graph');
  if (G.graph) { G.graph.graphData({nodes: d.nodes.map(n => ({...n})), links: d.links.map(l => ({...l}))}); return; }
  G.graph = ForceGraph3D()(el)
    .backgroundColor('#000004')
    .showNavInfo(false)
    .nodeThreeObject(makeNode)
    .nodeLabel(n => `<b>${esc(n.label)}</b><br><small>${esc(n.group)}</small>`)
    .linkColor(l => { const a = srcId(l), b = tgtId(l); return G.hi.size && !(G.hi.has(a) && G.hi.has(b)) ? 'rgba(80,110,160,.08)' : G.hi.has(a) && G.hi.has(b) ? 'rgba(255,255,255,.85)' : 'rgba(120,160,230,.28)'; })
    .linkWidth(l => G.hi.has(srcId(l)) && G.hi.has(tgtId(l)) ? 1.6 : .4)
    .linkOpacity(.5)
    .onNodeClick(n => select(n.id, true))
    .onBackgroundClick(() => clearSelection())
    .graphData({nodes: d.nodes.map(n => ({...n})), links: d.links.map(l => ({...l}))});
  G.graph.d3Force('charge').strength(-60);
  starfield();
  resize();
  addEventListener('resize', resize);
  (function loop() { requestAnimationFrame(loop); if (!G.active || !G.graph) return; idle(); if (G.pulsing) applyHighlight(); })();
  G.ready = true;
}
const srcId = l => typeof l.source === 'object' ? l.source.id : l.source;
const tgtId = l => typeof l.target === 'object' ? l.target.id : l.target;
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
function resize() { if (G.graph) G.graph.width(innerWidth).height(innerHeight); }
function starfield() {
  const n = 1800, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { const r = 1500 + Math.random() * 2500, a = Math.random() * 6.283, b = Math.acos(2 * Math.random() - 1);
    pos[3 * i] = r * Math.sin(b) * Math.cos(a); pos[3 * i + 1] = r * Math.cos(b); pos[3 * i + 2] = r * Math.sin(b) * Math.sin(a); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  G.graph.scene().add(new THREE.Points(g, new THREE.PointsMaterial({color: 0xaec6ff, size: 2.2, sizeAttenuation: false, transparent: true, opacity: .75})));
}

/* ---------- câmara ---------- */
function camTarget() { const c = G.graph.controls(); return c && c.target ? c.target.clone() : new THREE.Vector3(); }
function setCam(p) { const t = camTarget(); G.graph.cameraPosition({x: p.x, y: p.y, z: p.z}, t, 0); }
G.orbit = (dx, dy) => { // rotação manual (mãos): dx, dy em radianos
  if (!G.graph) return; G.lastTouch = performance.now();
  const cam = G.graph.camera(), t = camTarget(), p = cam.position.clone().sub(t);
  p.applyAxisAngle(new THREE.Vector3(0, 1, 0), -dx);
  const right = new THREE.Vector3().crossVectors(p, cam.up).normalize();
  if (right.lengthSq() > 1e-6) { const q = p.clone().applyAxisAngle(right, -dy); if (Math.abs(q.clone().normalize().y) < .985) p.copy(q); }
  setCam(p.add(t));
};
G.zoom = k => { // k > 1 aproxima
  if (!G.graph) return; G.lastTouch = performance.now();
  const cam = G.graph.camera(), t = camTarget(), p = cam.position.clone().sub(t);
  const d = clamp(p.length() / clamp(k, .8, 1.25), 40, 2500); setCam(p.setLength(d).add(t));
};
G.reset = () => { clearSelection(); G.graph && G.graph.zoomToFit(900, 60); };
function idle() { // deriva lenta enquanto ninguém mexe
  if (performance.now() - G.lastTouch < 4000 || G.hi.size) return;
  const cam = G.graph.camera(), t = camTarget(), p = cam.position.clone().sub(t);
  p.applyAxisAngle(new THREE.Vector3(0, 1, 0), .0012); setCam(p.add(t));
}
function nodeObj(id) { return G.graph.graphData().nodes.find(n => n.id === id); }
function flyTo(n) {
  const d = 140, r = 1 + d / Math.max(1, Math.hypot(n.x, n.y, n.z));
  G.graph.cameraPosition({x: n.x * r, y: n.y * r, z: n.z * r}, n, 1500); G.lastTouch = performance.now();
}
G.pickAt = (sx, sy) => { // escolher o nó mais próximo do cursor (mãos)
  if (!G.graph) return; let best = null, bd = 60;
  for (const n of G.graph.graphData().nodes) { if (n.x === undefined) continue; const p = G.graph.graph2ScreenCoords(n.x, n.y, n.z); const d = Math.hypot(p.x - sx, p.y - sy); if (d < bd) { bd = d; best = n; } }
  if (best) select(best.id, true);
};

/* ---------- seleção ---------- */
function select(id, fly) {
  const n = nodeObj(id); if (!n) return;
  G.sel = id; G.hi = new Set([id, ...(G.adj.get(id) || [])]);
  $('gx-t').textContent = n.label; $('gx-g').textContent = n.group; $('gx-e').textContent = n.excerpt; panel.classList.add('on');
  if (fly) flyTo(n); applyHighlight();
}
function clearSelection() { G.sel = null; G.hi = new Set(); panel.classList.remove('on'); if (G.graph) applyHighlight(); }

/* ---------- voz ---------- */
let voice = null;
function pickVoice() { const v = speechSynthesis.getVoices(); voice = v.find(x => /pt[-_]PT/i.test(x.lang)) || v.find(x => /^pt/i.test(x.lang)) || null; }
if ('speechSynthesis' in window) { speechSynthesis.onvoiceschanged = pickVoice; pickVoice(); }
let unlocked = false;
function unlockAudio() { if (unlocked || !('speechSynthesis' in window)) return; unlocked = true; try { const u = new SpeechSynthesisUtterance(' '); u.volume = 0; speechSynthesis.speak(u); } catch (e) {} }
const MUTE = /[?&]mute=1\b/.test(location.search);
const FINISH_MS = 900;           // silêncio antes de enviar o que disseste (não corta frases a meio)
const STOP_WORDS = /^\s*(p[aá]ra|stop|cala[- ]?te|silêncio|chega)[.!\s]*$/i;
function speak(text) {
  G.spoken.push(text);
  if (MUTE || !('speechSynthesis' in window)) return;
  try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = 'pt-PT'; if (voice) u.voice = voice; u.rate = 1.02; u.onstart = () => status('● a falar…'); u.onend = () => status(''); speechSynthesis.speak(u); } catch (e) {}
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false;
function toggleMic() {
  unlockAudio();
  if (!SR) { showAnswer('O reconhecimento de voz precisa do Chrome ou do Edge, senhor.'); return; }
  if (listening) { rec && rec.stop(); return; }
  rec = new SR(); rec.lang = 'pt-PT'; rec.continuous = true; rec.interimResults = true; rec.maxAlternatives = 1;
  let buf = '', timer = null;
  const flush = () => { const t = buf.trim(); buf = ''; if (!t) return; if (STOP_WORDS.test(t)) { try { speechSynthesis.cancel(); } catch (e) {} status(''); return; } input.value = ''; ask(t); };
  rec.onstart = () => { listening = true; micBtn.classList.add('on'); status('● a ouvir…'); };
  rec.onend = () => { clearTimeout(timer); flush(); listening = false; micBtn.classList.remove('on'); if (!G.busy) status(''); };
  rec.onerror = e => { status(''); showAnswer(e.error === 'not-allowed' ? 'Microfone bloqueado: clique no cadeado da barra de endereço e permita-o, senhor.' : 'Não consegui ouvir (' + e.error + ').'); };
  rec.onresult = e => { // junta os pedaços e só envia depois de FINISH_MS de silêncio
    try { speechSynthesis.cancel(); } catch (_) {}
    let fin = '', interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) (e.results[i].isFinal ? (fin += e.results[i][0].transcript + ' ') : (interim += e.results[i][0].transcript));
    buf += fin; showAnswer('“' + (buf + interim).trim() + '”'); clearTimeout(timer); timer = setTimeout(() => { flush(); }, FINISH_MS);
  };
  try { rec.start(); } catch (e) {}
}
function showAnswer(t) { answerEl.textContent = t; answerEl.classList.add('on'); }

/* ---------- cérebro ---------- */
const REMEMBER = /^\s*(lembra[- ]?te que|lembra que|recorda[- ]?te que|recorda que|n[aã]o te esque[cç]as que|remember that)\b/i;
async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: 'Resposta ilegível.'})); return {ok: r.ok, j};
}
async function ask(q) {
  q = (q || '').trim(); if (!q || G.busy) return; unlockAudio();
  G.busy = true; status('● a pensar…'); showAnswer('“' + q + '”');
  try {
    if (SEE.test(q)) { G.busy = false; await see(q.replace(/^\s*\/see\s*/i, '') || 'O que estás a ver no meu ecrã?'); G.busy = true; return; }
    if (REMEMBER.test(q)) { await remember(q); return; }
    const {ok, j} = await post('/chat', {sid: SID, q});
    if (!ok) { showAnswer(j.error || 'Algo correu mal, senhor.'); speak(j.error || 'Algo correu mal, senhor.'); return; }
    showAnswer(j.answer); speak(j.answer); focus(j.nodes || []);
  } catch (e) { showAnswer('Perdi a ligação ao servidor, senhor.'); }
  finally { G.busy = false; if (!listening) status(''); }
}
function focus(ids) { // fly-to-source
  if (!ids.length) return;
  if (ids.length >= 4) { G.sel = null; G.hi = new Set(ids); panel.classList.remove('on'); applyHighlight(); G.graph.zoomToFit(1400, 80, n => G.hi.has(n.id)); }
  else select(ids[0], true);
}
async function remember(q) {
  const {ok, j} = await post('/remember', {text: q});
  if (!ok) { showAnswer(j.error || 'Não consegui guardar.'); speak(j.error || 'Não consegui guardar, senhor.'); return; }
  const d = G.graph.graphData(), near = j.near != null ? d.nodes.find(n => n.id === j.near) : null;
  const n = {...j.node, __born: performance.now()};
  if (near) { n.x = near.x + (Math.random() - .5) * 8; n.y = near.y + (Math.random() - .5) * 8; n.z = near.z + (Math.random() - .5) * 8; }
  G.adj.set(n.id, new Set());
  for (const l of j.links) { G.adj.get(l.source)?.add(l.target); G.adj.get(l.target)?.add(l.source); }
  G.graph.graphData({nodes: [...d.nodes, n], links: [...d.links, ...j.links.map(l => ({...l}))]});
  G.pulsing = true; setTimeout(() => { G.pulsing = false; applyHighlight(); }, 3200);
  setTimeout(() => select(n.id, true), 350);
  const line = `Anotado, senhor: “${j.title}”. A memória do senhor acaba de ganhar uma estrela.`;
  showAnswer(line); speak(line);
}
/* ---------- olhos: um único fotograma do ecrã, só quando o senhor pede ---------- */
const SEE = /^\s*(\/see\b|v[eê] o (meu )?ecr[aã]|olha para o (meu )?ecr[aã]|what do you see)/i;
async function grabScreen() {
  const stream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: false});
  try {
    const v = document.createElement('video'); v.srcObject = stream; v.muted = true; await v.play();
    await new Promise(r => setTimeout(r, 250));
    const sc = Math.min(1, 1568 / Math.max(v.videoWidth, v.videoHeight)), c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * sc); c.height = Math.round(v.videoHeight * sc);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.8).split(',')[1];
  } finally { stream.getTracks().forEach(t => t.stop()); }   // a partilha acaba logo a seguir
}
async function see(q) {
  if (G.busy) return; unlockAudio(); G.busy = true; status('● a olhar…');
  try {
    let image; try { image = await grabScreen(); } catch (e) { showAnswer('Sem partilha de ecrã não vejo nada, senhor.'); return; }
    status('● a pensar…');
    const {ok, j} = await post('/see', {sid: SID, q, image});
    showAnswer(ok ? j.answer : (j.error || 'Não consegui ver, senhor.')); speak(ok ? j.answer : (j.error || 'Não consegui ver, senhor.'));
  } catch (e) { showAnswer('Perdi a ligação ao servidor, senhor.'); }
  finally { G.busy = false; if (!listening) status(''); }
}
G.see = see;
G.ask = ask;

/* ---------- abrir / fechar ---------- */
const greeting = () => { const h = new Date().getHours(); return (h < 6 ? 'Boa noite' : h < 12 ? 'Bom dia' : h < 20 ? 'Boa tarde' : 'Boa noite') + ', senhor.'; };
const countLine = () => { const n = G.data.nodes.length; return `${n} ${n === 1 ? 'nota' : 'notas'} na galáxia`; };
G.open = async () => {
  if (!root) buildUI();
  root.classList.add('on'); G.active = true; document.body.classList.add('galaxy');
  $('gl').style.display = 'none'; $('c2').style.pointerEvents = 'none';
  unlockAudio(); status('● a carregar…');
  try { await load(); } catch (e) { showAnswer('Não consegui carregar as notas: ' + e.message); status(''); return; }
  status(''); resize(); if (G.data.nodes.length) G.graph.zoomToFit(0, 40);
  const hello = greeting(); showAnswer(hello + ' · ' + countLine());
  if (!G.greeted) { G.greeted = true; speak(hello); }
  setTimeout(() => input && input.focus(), 50);
};
G.close = () => { if (!root) return; root.classList.remove('on'); G.active = false; document.body.classList.remove('galaxy'); $('gl').style.display = ''; $('c2').style.pointerEvents = ''; try { speechSynthesis.cancel(); } catch (e) {} };
