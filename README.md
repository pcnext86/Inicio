# HOLO — controla as tuas notas com as mãos

Painel de notas controlado pela webcam: pinças cartas do ar, atiras-nas com momento, agarras modelos 3D
e desmontas-os com as duas mãos. Tecla **J** = modo Jarvis (tudo dourado, voz a narrar).
O modo cartas corre todo na tua máquina: sem nuvem, sem chaves, sem contas. A **galáxia JARVIS** (tecla G) é opcional
e usa um modelo da Anthropic: ver "O que sai da tua máquina" mais abaixo.

## Correr (2 minutos)

Precisas de Python 3 e do Google Chrome.

```
python3 server.py
```

Abre `http://localhost:4890`, permite a câmara e levanta uma mão.
Outra porta: `HOLO_PORT=4891 python3 server.py`. O servidor só escuta em 127.0.0.1.

Sem câmara: `?sim=1` mostra mãos sintéticas num ciclo de demonstração; o rato funciona sempre
(clicar = pinça). Se a câmara estiver bloqueada: ícone da câmara na barra do Chrome → Permitir → **RETRY CAMERA**.

## Gestos

| Gesto | O que faz |
|---|---|
| Pinça (polegar e indicador a tocar) | agarra uma carta ou um modelo; largar em movimento = voa |
| Pinça rápida | orbe abre/fecha o leque de notas; nota abre no leitor; no leitor fecha-o |
| Atirar para fora do ecrã | a nota evapora (reabre o orbe para a trazer de volta) |
| Duas pinças, afastar/juntar | zoom da cena; rodar as mãos roda a cena |
| Duas mãos numa carta | esticar = abre o leitor; esmagar = lê o resumo (modo Jarvis) |
| Pulso a rodar com um modelo agarrado | o modelo gira com inércia |
| Duas mãos num modelo | esticar desmonta em estilhaços; encolher volta a juntá-lo |
| Arrastar para a margem direita | arquiva na prateleira (pinça rápida no chip devolve-a) |
| Sinal de paz mantido (0,8 s) | repõe tudo |

**F** liga os efeitos (ouvem sempre, por isso são mais nervosos numa secretária): palma parada = repulsor ·
palma aberta e punho = atrair · apontar = tinta · palmas = repor · duas palmas a descer = grelha.
Outras teclas: **J** Jarvis · **L** legenda · **R** repor · **Esc** fecha o leitor.

## As tuas notas

Edita `holo.json`:

```json
{"folder": "/caminho/para/as/tuas/notas"}
```

Subpastas viram orbes (até 10, 12 notas cada); os ficheiros `.md` viram cartas. Sem `holo.json` preenchido,
usa a pasta `notes/` de exemplo.

## Galáxia JARVIS (tecla G)

As tuas notas como um universo 3D: nós coloridos por pasta, ligados quando uma nota menciona outra ou partilham
`[[wikilinks]]`. Pergunta em voz alta ou por escrito, e o JARVIS responde só com base nas tuas notas, numa frase seca
mais os factos, e **a câmara voa até à nota de onde veio a resposta**. Se a resposta usou 4 ou mais notas, acende o
aglomerado inteiro. Conversa de circunstância não mexe na câmara. Ao abrir, diz a saudação com a contagem real.

- **Escrever ou falar**: caixa em baixo, ou o botão 🎙 (Chrome/Edge). Respostas faladas com a voz pt-PT do sistema.
- **"Lembra-te que..."** (ou "remember that...") cria mesmo uma nota em `captures/` dentro da tua pasta de notas, e a
  estrela nasce junto da nota mais relacionada, com um pulso de luz, e a câmara voa até ela.
- **Mãos**: pinça a arrastar roda a galáxia · duas pinças afastar/juntar = zoom · pinça rápida abre a nota sob o cursor ·
  paz mantido repõe a vista. O rato também funciona (arrastar, roda para zoom, clicar num nó).

### Configurar o cérebro (uma vez)

Copia `config.example.json` para `config.json` (já vem um) e **escreve tu a chave no ficheiro**. Nunca a colas em nenhum chat.

```json
{ "provider": "api", "anthropic_api_key": "PUT-YOUR-KEY-HERE", "model": "claude-opus-5-5", "effort": "medium" }
```

Sem chave de API? Usa a tua subscrição do Claude Code: `{"provider": "claude-cli"}` (mais lento; precisa do comando `claude`
instalado e com sessão iniciada). O `config.json` nunca é servido ao browser; está testado.

### O que sai da tua máquina (galáxia)

- Cada pergunta envia à API da Anthropic **a pergunta e até 6 excertos de notas** (cerca de 1400 caracteres cada). Nada mais.
- O botão 🎙 usa o reconhecimento de voz do Chrome, que envia o áudio para os servidores da Google. Se isso não te agrada, escreve em vez de falar.
- "Lembra-te que..." escreve ficheiros na tua pasta de notas.
- O servidor só aceita pedidos de localhost, e recusa `Host`/`Origin` estranhos, para outras páginas não o poderem usar.

## Os teus modelos 3D

Larga qualquer `.glb` em `props/` e recarrega. Se não carregar, costuma estar comprimido com Draco
(o HOLO já traz o descodificador; se mesmo assim falhar: `npx @gltf-transform/cli copy in.glb out.glb`).
Para a pose inicial, acrescenta uma linha ao mapa `POSE` em `holo.html`, por exemplo
`'meu-modelo.glb': { rx: .15, ry: 0, scale: 1 }` (`rx` inclina, `ry` roda, `scale` redimensiona).

Os dois modelos incluídos (`capsula-demo.glb`, `asteroide-demo.glb`) são **formas de demonstração geradas
por código**, não scans reais. Para museu a sério: 3d.si.edu (Smithsonian), Sketchfab, Poly Pizza.
Confirma a licença de cada modelo.

## Ajustar o toque

No topo do script de `holo.html` há constantes com nome: `PINCH_IN` (maior = pinça mais permissiva),
`PINCH_OUT`, `PINCH_EARN`, `AMP` (alcance do braço), `TAP_MS`/`TAP_MOVE`, `FLICK_V`, `ACCENT`, e o objeto
`PHRASES` com as frases do Jarvis. Para mudar a marca: `TITLE`, `RING_LABEL`, `ACCENT`, `ACCENT_JARVIS`.

## Opus 5.5: cérebro, voz e olhos

- **Regras do modelo** (em `jarvis/llm.py`, com testes): o pensamento do Opus 5.5 está sempre ligado, por isso nunca se envia "thinking desligado" nem
  `tool_choice` forçado; o esforço vai em `output_config.effort` (Haiku não o aceita); `max_tokens` é pelo menos 2000 porque cobre pensamento **e**
  resposta, com uma repetição maior se vier texto vazio.
- **Trocar de cérebro por voz**: "experimenta o Opus 5", "muda para o Fable 5.1", "volta ao teu cérebro normal". O nome falado vira um id exato
  da lista conhecida; se não existir ("Opus 6") ele **recusa** em vez de escolher o mais parecido. A troca só dura até reiniciar.
- **Voz**: o microfone junta o que dizes e só envia depois de 900 ms de silêncio (não corta a meio da frase); dizer "para"/"cala-te" interrompe-o.
  `?mute=1` na URL desliga a fala (útil a gravar ou em reuniões). A saudação é uma linha curta; a contagem de notas fica no ecrã.
- **Olhos (👁 ou "vê o meu ecrã")**: o browser pede-te para partilhar o ecrã, tira **um** fotograma, e a partilha termina logo. O fotograma vai para a API da Anthropic.

## Telefone, Google e bolso (opcionais, precisam das tuas contas)

Todas as chaves escreves tu em `config.json` (ver `config.example.json`); nunca no chat. O ficheiro e os de `state/` ficam a 600.

| Parte | O que precisas | Como arrancar |
|---|---|---|
| Telefone (ligar-te) | conta Retell, um número, `telephony.api_key/from/callback` | `python3 setup_phone.py --dry` e depois sem `--dry` (idempotente) |
| Google (agenda, correio) | projeto Google Cloud, Gmail+Calendar, consentimento *In production*, cliente Web com redirect `http://localhost:4890/oauth/callback` | abre `http://localhost:4890/oauth/start` |
| Telegram | bot do @BotFather em `telegram.bot_token`; chave de fala (OpenAI/ElevenLabs) para notas de voz | diz "pocket code" na galáxia e envia o código, sozinho, ao bot |
| Hotline | número do Retell + `cloudflared` + `telephony.passcode` e `hotline_token` (32+ caracteres aleatórios) | ver `jarvis/tunnel.py` |

(O pack usa a porta 4700; aqui é 4890, por isso o redirect do Google é nessa porta.)

- **Só rascunhos**: não existe função de enviar email, nem existirá. Resultados de email/agenda são tratados como dados não confiáveis; depois de ler correio ou calendário no mesmo turno, alterar/mover recusa-se.
- **"Chama-me" não é "chama-me se"**: "só me ligues se…" arma a linha urgente e nunca liga. Tabela de 21 frases em `jarvis/router.py`, verificada no preflight. Urgente toca uma vez, com 10 minutos de intervalo.
- **Depois da chamada**: a transcrição vira instruções (uma verificação + a ação que ela condiciona = uma instrução), executam-se, e chega **uma** confirmação (cartão + Telegram, nunca duas vezes).
- **Lembretes e briefing** ("daqui a vinte minutos faz-me uma chamada de lembrete sobre…", "chama-me com o briefing todas as manhãs às 8", "para as chamadas da manhã") guardam-se em `state/desk.json` e sobrevivem a reinícios.
- **Hotline**: o código é verificado **no servidor** (tempo constante, bloqueio de 15 min após 3 falhas); o agente nunca o vê. Um estranho só deixa uma mensagem inerte, que nunca entra nas notas.
- **Palco**: "stage an urgent call in two minutes" (aceita "Georgia State" como mishearing) toca só ao telefone com um cenário fictício. Diz "encenei esta" quando filmares. `POST /stage` com `{"dry": true}` valida sem ligar.

## Segurança e preflight

`python3 preflight.py` (sem `--live` não gasta nada): config, ids de modelo, tabela de chamadas e uma secção de segurança contra um servidor real: Host estranho recusado,
`<script src>` de outro site recusado, POST com Origin estranha recusado, corpo gigante recusado, `config.json` nunca servido, segredos a 600.
Cabeçalhos `nosniff`, `same-origin`, `no-referrer` e anti-frame; timeouts de socket; o `.gitignore` cobre `config.json*`. Respostas de modelo e transcrições mostram-se como texto, nunca como HTML.

## Testes

Servidor e Parte 2 (serviços simulados, 57 testes: segurança, grafo, chat, regras do Opus 5.5, troca de cérebro, telefone, Google, Telegram, hotline, depois-da-chamada):

```
pip install pytest
python3 -m pytest tests -q
```

Galáxia no browser (25 testes, precisa de `pip install playwright && playwright install chromium`): `python3 tests/test_galaxy.py`.

Interface dos gestos: `http://localhost:4890/?probe=1` corre uma bateria com mãos sintéticas e mostra `passou/total` no título do
separador e numa lista no ecrã (45 testes: poses, pinça, tap, momento, evaporar, arquivar, zoom, rodar,
esticar/esmagar, repor, efeitos, modelos 3D, Jarvis, robustez).

## Limites honestos

- O resumo ao esmagar é **extrativo** (primeiras frases da nota), não um resumo por IA.
- A voz é a do teu sistema (procura pt-PT; se não houver, usa a que existir).
- Os testes usam mãos sintéticas; a precisão com uma mão real depende da luz. Um candeeiro de frente ajuda mais do que qualquer constante.
- A galáxia foi testada com a API simulada e mãos sintéticas; **não** foi testada com uma chave real nem com o microfone/voz de um Chrome real.
- O modelo por defeito é `claude-opus-5-5`, como no pack Opus 5.5. As regras da API foram confirmadas na documentação oficial, mas nenhuma chamada real foi feita daqui.
- **Telefone, Google, Telegram e hotline foram testados só contra serviços simulados** (as respostas imitam o formato documentado). Nunca foram tentados contra o Retell, o Google ou o Telegram reais, nem com uma chamada verdadeira. Corre `python3 preflight.py --live` e faz as chamadas de teste tu, ao teu próprio número.
- O túnel do cloudflared e a religação automática do agente de entrada (`jarvis/tunnel.py`) estão escritos mas não foram executados.
- Rastreio: MediaPipe Hands (versão legada), incluído em `vendor/` para funcionar offline.

## Licenças

HOLO: MIT (`LICENSE`). MediaPipe: Apache-2.0. three.js e 3d-force-graph (`vendor/force-graph3d.js`, empacotado): MIT.
