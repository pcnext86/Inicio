/* Bateria de testes do HOLO: mãos sintéticas, relógio virtual, sem câmara.
   Abre http://localhost:4890/?probe=1  → o título do separador mostra "passou/total". */
const H=window.HOLO,S=H.S;
const VT={t:1000};
const spec=(s)=>({lm:H.synth(s)});
function tick(specs,n=1){for(let i=0;i<n;i++){VT.t+=1000/30;H.frame(specs.map(spec),VT.t);}}
function glide(a,b,frames){ // interpola x,y entre duas listas de mãos (pose = a nova)
  for(let i=1;i<=frames;i++){const u=i/frames;
    tick(b.map((q,k)=>({...q,x:a[k].x+(q.x-a[k].x)*u,y:a[k].y+(q.y-a[k].y)*u,size:q.size??a[k].size})));}
}
const none=()=>tick([],12);
const N=(wx,wy)=>{const p=H.toScreen(wx,wy);return {x:p.x/H.W,y:p.y/H.H};};
const orbN=i=>N(S.orbs[i].x,S.orbs[i].y);
const outCards=()=>S.cards.filter(c=>c.state==='out'||c.state==='held');
const hand=(p,pose,extra={})=>({x:p.x,y:p.y,pose,...extra});
function reset(){H.hardReset();none();}
function tapAt(p){tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);tick([hand(p,'open')],4);}
function fanFirst(){tapAt(orbN(0));tick([],40);}
function grabCard(c){const p=N(c.x,c.y);tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);return p;}

const results=[];
async function T(name,fn){reset();let ok=false,info='';
  try{const r=fn();ok=r===true||r===undefined?true:!!r;if(r&&r!==true)info=String(r);}catch(e){ok=false;info=e.message||String(e);}
  results.push({name,ok,info});}

/* ---- carregamento ---- */
T('notas carregadas (orbes e cartas)',()=>S.orbs.length>0&&S.cards.length>0);
T('modelos 3D carregados',()=>S.props.length>0&&S.props.every(p=>p.shards.length>1));
/* ---- poses ---- */
const poseOf=(p,extra)=>H.metrics(H.synth({x:.5,y:.5,pose:p,...extra})).pose;
T('reconhece mão aberta',()=>poseOf('open')==='open');
T('reconhece punho',()=>poseOf('fist')==='fist');
T('reconhece apontar',()=>poseOf('point')==='point');
T('reconhece sinal de paz',()=>poseOf('peace')==='peace');
T('quase-pinça (0,45) é ignorada',()=>{const p=orbN(0);tick([hand(p,'open')],4);tick([hand(p,'near')],12);return !S.hands[0].pinching;});
T('tremor de um fotograma não conta como pinça',()=>{const p=orbN(0);tick([hand(p,'open')],4);tick([hand(p,'pinch')],1);tick([hand(p,'open')],4);return !S.hands[0].pinching&&S.hands[0].earn===0;});
T('pinça a sério é aceite',()=>{const p=orbN(0);tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);return S.hands[0].pinching;});
/* ---- orbes e cartas ---- */
T('pinça rápida no orbe abre o leque',()=>{fanFirst();return outCards().length===S.orbs[0].cards.length;});
T('segunda pinça rápida fecha o leque',()=>{fanFirst();tapAt(orbN(0));tick([],60);return S.orbs[0].cards.every(c=>c.state==='stored');});
T('pinça agarra e arrasta uma carta',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);const x0=c.x;
  glide([hand(p,'pinch')],[hand({x:p.x+.1,y:p.y+.05},'pinch')],12);return c.state==='held'&&c.x>x0+60;});
T('largar em movimento dá momento',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);
  glide([hand(p,'pinch')],[hand({x:p.x+.12,y:p.y},'pinch')],5);tick([hand({x:p.x+.12,y:p.y},'open')],2);const x1=c.x;tick([],6);return c.x>x1+15;});
T('pinça rápida numa carta abre o leitor',()=>{fanFirst();const c=outCards()[0],p=N(c.x,c.y);tapAt(p);return S.reader===c;});
T('pinça rápida fecha o leitor',()=>{fanFirst();const c=outCards()[0];tapAt(N(c.x,c.y));tapAt({x:.5,y:.5});return S.reader===null;});
T('atirar para fora do ecrã evapora',()=>{fanFirst();const c=outCards().slice(-1)[0],p=grabCard(c);
  glide([hand(p,'pinch')],[hand({x:p.x,y:.02},'pinch')],4);tick([hand({x:p.x,y:.02},'open')],3);tick([],25);return c.state==='stored';});
T('reabrir o orbe traz de volta a nota evaporada',()=>{fanFirst();const c=outCards().slice(-1)[0],p=grabCard(c);
  glide([hand(p,'pinch')],[hand({x:p.x,y:.02},'pinch')],4);tick([hand({x:p.x,y:.02},'open')],3);tick([],25);
  const o=S.orbs[0];while(o.cards.some(k=>k.state==='out'))tapAt(orbN(0)),tick([],40);tapAt(orbN(0));tick([],40);return o.cards.every(k=>k.state==='out');});
T('arrastar para a margem direita arquiva',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);
  glide([hand(p,'pinch')],[hand({x:.97,y:.5},'pinch')],20);tick([hand({x:.97,y:.5},'open')],2);return c.state==='docked'&&S.docked.includes(c);});
T('tocar na prateleira devolve a carta',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);
  glide([hand(p,'pinch')],[hand({x:.97,y:.5},'pinch')],20);tick([hand({x:.97,y:.5},'open')],2);tick([],15);
  const W=H.W,Hh=H.H,pt={x:(W-150+68)/W,y:(96+18)/Hh};tapAt(pt);return c.state==='out'&&S.docked.length===0;});
T('arrasto curto (50 px) não é toque',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);glide([hand(p,'pinch')],[hand({x:p.x+.05,y:p.y},'pinch')],6);tick([hand({x:p.x+.05,y:p.y},'open')],3);return S.reader===null;});
T('toque com tremor de 6 px continua a ser toque',()=>{fanFirst();const c=outCards()[0],p=grabCard(c);tick([hand({x:p.x+.005,y:p.y},'pinch')],2);tick([hand({x:p.x+.005,y:p.y},'open')],3);return S.reader===c;});
/* ---- duas mãos ---- */
T('duas pinças afastadas fazem zoom',()=>{const a={x:.4,y:.5},b={x:.6,y:.5};tick([hand(a,'open'),hand(b,'open')],4);tick([hand(a,'pinch'),hand(b,'pinch')],6);
  glide([hand(a,'pinch'),hand(b,'pinch')],[hand({x:.3,y:.5},'pinch'),hand({x:.7,y:.5},'pinch')],14);return S.view.s>1.6;});
T('duas pinças aproximadas reduzem',()=>{const a={x:.3,y:.5},b={x:.7,y:.5};tick([hand(a,'open'),hand(b,'open')],4);tick([hand(a,'pinch'),hand(b,'pinch')],6);
  glide([hand(a,'pinch'),hand(b,'pinch')],[hand({x:.42,y:.5},'pinch'),hand({x:.58,y:.5},'pinch')],14);return S.view.s<.6;});
T('rodar as mãos roda a cena',()=>{const a={x:.4,y:.5},b={x:.6,y:.5};tick([hand(a,'open'),hand(b,'open')],4);tick([hand(a,'pinch'),hand(b,'pinch')],6);
  glide([hand(a,'pinch'),hand(b,'pinch')],[hand({x:.4,y:.4},'pinch'),hand({x:.6,y:.6},'pinch')],14);return Math.abs(S.view.a)>.3;});
T('esticar uma carta com duas mãos abre o leitor',()=>{fanFirst();const c=outCards()[0],p=N(c.x,c.y);tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);
  const q={x:Math.min(.95,p.x+.1),y:p.y};tick([hand(p,'pinch'),hand(q,'open')],3);tick([hand(p,'pinch'),hand(q,'pinch')],6);
  glide([hand(p,'pinch'),hand(q,'pinch')],[hand(p,'pinch'),hand({x:Math.min(.98,p.x+.5),y:p.y},'pinch')],16);return S.reader===c;});
T('esmagar uma carta lê o resumo (Jarvis)',()=>{S.jarvis=true;fanFirst();const c=outCards()[0],p={x:.3,y:.5};{const w=H.toWorld(p.x*H.W,p.y*H.H);c.x=w.x;c.y=w.y;c.target=null;c.vx=c.vy=0;}
  const q={x:.55,y:.5};tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);tick([hand(p,'pinch'),hand(q,'open')],3);tick([hand(p,'pinch'),hand(q,'pinch')],6);
  glide([hand(p,'pinch'),hand(q,'pinch')],[hand(p,'pinch'),hand({x:.31,y:.5},'pinch')],14);return S.spoken.some(s=>s.key==='gist'&&s.text.includes('Em resumo'));});
T('resumo extrai a primeira frase útil',()=>H.gistOf('# T\n\nPrimeira frase completa aqui. Segunda frase.')==='Primeira frase completa aqui.');
/* ---- repor ---- */
T('paz mantido repõe tudo',()=>{fanFirst();const p={x:.5,y:.5};tick([hand(p,'open')],4);tick([hand(p,'peace')],30);tick([],40);return outCards().length===0;});
T('paz curto (0,3 s) não repõe',()=>{fanFirst();const p={x:.5,y:.5};tick([hand(p,'peace')],9);tick([],20);return outCards().length>0;});
T('repor desfaz o zoom',()=>{S.view.s=2;S.view.a=.8;const p={x:.5,y:.5};tick([hand(p,'peace')],30);tick([],60);return Math.abs(S.view.s-1)<.02&&Math.abs(S.view.a)<.02;});
/* ---- efeitos ---- */
T('efeitos desligados: palma parada não dispara',()=>{fanFirst();const c=outCards()[0],x0=c.x;tick([hand({x:N(c.x,c.y).x-.05,y:N(c.x,c.y).y},'open')],40);tick([],10);return Math.abs(c.x-x0)<3&&S.blasts.length===0;});
T('efeitos ligados: palma parada = repulsor',()=>{fanFirst();S.fx=true;const c=outCards()[0],q=N(c.x,c.y),x0=c.x,y0=c.y;
  tick([hand({x:q.x-.04,y:q.y},'open')],40);tick([],8);return Math.hypot(c.x-x0,c.y-y0)>25||S.blasts.length>0;});
T('efeitos ligados: apontar desenha tinta',()=>{S.fx=true;const a={x:.3,y:.4};tick([hand(a,'point')],6);glide([hand(a,'point')],[hand({x:.6,y:.5},'point')],20);return S.ink.length>0&&S.ink[0].pts.length>5;});
T('efeitos ligados: palmas repõem',()=>{fanFirst();S.fx=true;const a={x:.2,y:.5},b={x:.8,y:.5};tick([hand(a,'open',{}),hand(b,'open')],6);
  glide([hand(a,'open'),hand(b,'open')],[hand({x:.47,y:.5},'open'),hand({x:.53,y:.5},'open')],5);tick([],40);return outCards().length===0;});
T('efeitos ligados: duas palmas a descer arrumam em grelha',()=>{fanFirst();S.fx=true;const a={x:.35,y:.25},b={x:.65,y:.25};tick([hand(a,'open'),hand(b,'open')],8);
  glide([hand(a,'open'),hand(b,'open')],[hand({x:.35,y:.7},'open'),hand({x:.65,y:.7},'open')],10);tick([],30);
  const out=outCards();const ys=new Set(out.map(c=>Math.round(c.y/10)));return out.length>1&&ys.size<out.length;});
T('efeitos ligados: palma aberta e punho atrai',()=>{fanFirst();S.fx=true;const c=outCards()[0];const q={x:.5,y:.5};tick([hand(q,'open')],10);tick([hand(q,'fist')],6);tick([],12);
  const w=H.toWorld(.5*H.W,.5*H.H);return Math.hypot(c.x-w.x,c.y-w.y)<Math.hypot(H.fanTarget(S.orbs[0],0,S.orbs[0].cards.length).x-w.x,H.fanTarget(S.orbs[0],0,S.orbs[0].cards.length).y-w.y);});
/* ---- modelos 3D ---- */
T('pinça num modelo 3D agarra-o',()=>{const m=S.props[0],p=N(m.x,m.y);tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);return m.held;});
T('rodar o pulso a pinçar gira o modelo',()=>{const m=S.props[0],p=N(m.x,m.y),r0=m.ry;tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);
  for(let i=1;i<=10;i++)tick([hand(p,'pinch',{roll:i*.12})],1);return Math.abs(m.ry-r0)>.5;});
T('esticar com duas mãos desmonta o modelo',()=>{const m=S.props[0],p=N(m.x,m.y),q={x:p.x+.15,y:p.y};tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);tick([hand(p,'pinch'),hand(q,'open')],3);tick([hand(p,'pinch'),hand(q,'pinch')],6);
  glide([hand(p,'pinch'),hand(q,'pinch')],[hand(p,'pinch'),hand({x:p.x+.5,y:p.y},'pinch')],16);tick([hand(p,'pinch'),hand({x:p.x+.5,y:p.y},'pinch')],20);return m.pscale>1.8&&m.explode>.3;});
T('encolher funde o modelo de novo',()=>{const m=S.props[0];m.pscale=2.5;m.explode=1;const p=N(m.x,m.y),q={x:p.x+.4,y:p.y};tick([hand(p,'open')],4);tick([hand(p,'pinch')],6);tick([hand(p,'pinch'),hand(q,'open')],3);tick([hand(p,'pinch'),hand(q,'pinch')],6);
  glide([hand(p,'pinch'),hand(q,'pinch')],[hand(p,'pinch'),hand({x:p.x+.04,y:p.y},'pinch')],16);tick([hand(p,'pinch'),hand({x:p.x+.04,y:p.y},'pinch')],30);return m.pscale<1.1&&m.explode<.15;});
/* ---- Jarvis ---- */
T('tecla J liga o modo Jarvis (dourado) e fala',()=>{dispatchEvent(new KeyboardEvent('keydown',{key:'j'}));const ok=S.jarvis&&getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()==='#ffc400'&&S.spoken.some(s=>s.key==='on');dispatchEvent(new KeyboardEvent('keydown',{key:'j'}));return ok&&!S.jarvis;});
T('arquivar fala em modo Jarvis',()=>{S.jarvis=true;fanFirst();const c=outCards()[0],p=grabCard(c);glide([hand(p,'pinch')],[hand({x:.97,y:.5},'pinch')],20);tick([hand({x:.97,y:.5},'open')],2);return S.spoken.some(s=>s.key==='dock');});
T('fora do modo Jarvis fica em silêncio',()=>{fanFirst();return S.spoken.length===0;});
/* ---- robustez ---- */
T('perder a mão a meio da pinça larga a carta',()=>{fanFirst();const c=outCards()[0];grabCard(c);tick([],15);return c.state==='out'&&S.hands.length===0;});
T('sem mãos nada rebenta (60 fotogramas)',()=>{tick([],60);return true;});

reset();
const pass=results.filter(r=>r.ok).length;
document.title=`${pass}/${results.length}`;
const box=document.getElementById('probe');box.style.display='block';
box.innerHTML=`<b>${pass}/${results.length}</b> testes<br>`+results.map(r=>`<div class="${r.ok?'ok':'no'}">${r.ok?'✔':'✘'} ${r.name}${r.ok?'':' — '+r.info}</div>`).join('');
H.draw(performance.now());H.syncGL();
window.PROBE_RESULTS=results;
