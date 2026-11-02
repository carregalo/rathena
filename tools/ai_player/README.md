# Lyra: uma jogadora controlada por IA no rAthena

A Lyra é uma personagem de verdade no servidor. Ela entra pela tela de login como qualquer jogador, com conta,
PIN e personagem próprios, e é controlada por um programa externo: o Claude decide o que ela quer fazer, e o
código executa no jogo. O servidor não foi alterado. Para ele, a Lyra é um cliente comum.

Este diretório tem tudo o que ela precisa:

| Arquivo | Papel |
| --- | --- |
| `roclient.py` | Fala o protocolo do jogo (login, char, mapa) e mantém o estado do mundo |
| `atlas.py` | Conhecimento dos mapas lido dos dados do servidor: células, portais, NPCs |
| `luaengine.py`, `lua/` | Motor de rotinas em Lua: o que o corpo dela faz sozinho entre as decisões |
| `agent.py` | O cérebro: o laço de decisões do Claude (`decide`, `act`, `brain`, `main`) |
| `config.py` | A conta (ambiente ou `local.env`) e as constantes de ajuste |
| `persona.py` | História de origem, prompt do sistema e schema de cada decisão |
| `observation.py` | O texto que ela vê a cada turno |
| `mind.py` | A memória persistente |
| `body.py` | O corpo: ações básicas, reflexos e medição dos resultados |
| `npc.py` | Responder e descrever janelas de NPC e registrar o que cada NPC faz |
| `gamedata.py` | Nomes de itens e classes lidos do servidor, texto ASCII, busca na mochila |
| `protocol/` | Ferramentas que extraem do código do servidor os tamanhos e formatos dos pacotes |
| `tests/` | A checklist: testes offline e um teste no jogo, do básico ao complexo |

Ao lado, `tools/ai_merchant/` tem o Tobias, um NPC mercador que negocia preços usando o Claude
(ver a skill `.claude/skills/rathena-ai-npc`).

## Como funciona

```
          a cada evento (chat, NPC, luta, descoberta) ou a cada 15-35 s parada
 Claude  <───────────────────────────────────────────────────────────────── observação
 (agent.py: brain) ─── decisão JSON ──>  fala, objetivo, rotina + argumentos, resposta ao NPC, itens
                                              │
                                              v
 Rotina Lua (lua/base, lua/learned) ── Tick a cada 0,25 s ──> API: Move, Attack, PickUp, Talk, Route...
                                              │
 Corpo (agent.py: Body) ── reflexos: poção, revidar ── medição: dano, experiência, drops, efeitos
                                              │
 roclient.py ── pacotes ──> servidor rAthena (login 6900, char 6121, map 5121)
```

Três camadas, como na IA de homúnculos do próprio jogo (`AI/AI.lua` no cliente, usada só como referência):

1. **O cérebro** (`brain`, `decide`, `act` em `agent.py`). Monta uma observação em texto: história, nível,
   humor, objetivo, diário, o que ela aprendeu, o que vê, a mochila, o chat e a janela de NPC aberta. O
   Claude devolve uma decisão com saída estruturada (`DECISION_SCHEMA`), que o código valida antes de usar.
2. **As rotinas** (`luaengine.py`). São programas Lua que rodam a cada 0,25 s até terminarem: `go`, `follow`,
   `hunt`, `explore`, `travel`, `visit`. O Claude escolhe qual rodar e pode escrever rotinas novas, que ficam
   em `lua/learned/` como técnicas aprendidas. Elas rodam isoladas em `lua/sandbox.lua`: sem arquivos, sistema
   operacional, `load`, `debug` ou objetos Python, com limite de instruções e de memória.
3. **O corpo** (`Body` em `agent.py`). Guarda as ações básicas (andar com caminho calculado, perseguir e
   atacar, conversar com NPC) e os reflexos que não podem depender de uma rotina (beber poção, revidar quem
   a ataca ou ataca quem ela segue). Também mede o resultado de cada experiência e grava na memória.

### Memória e personagem

`Mind` (`agent.py`) é persistida em `memory.json` (fora do git):

- história de origem reescrita a cada marco (subir de nível, mudar de classe);
- humor com motivo, diário e notas por jogador;
- conhecimento aprendido só por experiência: lugares visitados, NPCs e o que disseram e fazem, monstros
  (dano recebido e causado, experiência, drops), efeito de itens.

O prompt (`SYSTEM_PROMPT`) mantém a Lyra dentro do mundo. A única exceção: ela não nega ser uma IA se alguém
perguntar sinceramente, fora da brincadeira.

### Mapa de viagem (`atlas.py`)

O atlas lê as mesmas fontes que o gerador de navegação do rAthena (`navigenerator.bat` → `src/map/navi.cpp`):

- `db/map_cache.dat`: as células andáveis de cada mapa;
- os scripts carregados por `npc/re/scripts_main.conf`: portais (`warp`) e NPCs (nome e posição).

Com isso:

- **Caminho no mapa:** A* com as regras do servidor (`src/map/path.cpp`: 8 direções, diagonal só com os dois
  lados livres).
- **Andar sem parar:** como um jogador segurando o botão do mouse, a cada 0,3 s ela pede para andar até o
  ponto do caminho 22 passos à frente de onde está. O servidor troca o destino na próxima célula
  (`unit_walktoxy` em `src/map/unit.cpp`), e cada pedido fica dentro do limite de 32 passos (`MAX_WALKPATH`).
- **Rotas entre mapas:** Dijkstra sobre os portais, usando só portais alcançáveis a pé a partir de onde ela
  está (regiões calculadas uma vez e guardadas em `.atlas_cache.json`).
- **Achar NPCs:** por nome, os mais próximos primeiro (em portais a atravessar).

O atlas mostra a ela os nomes e posições dos NPCs, mas **não o que eles fazem**: isso ela descobre usando
cada NPC (menus, lojas, armazém), e fica registrado na memória.

### Serviços de NPC

`roclient.py` entende todas as janelas de NPC. `answer_npc` em `agent.py` traduz a resposta dela (campo
`npc_reply`, ou `Reply()` numa rotina) no pacote certo:

| Janela | Pacote do servidor | Resposta dela |
| --- | --- | --- |
| Texto e "próximo" | `0x00b4`, `0x00b5` | automático (ela lê tudo) |
| Menu | `0x00b7` | número ou texto da opção (`0x00b8`; a numeração do script conta opções vazias) |
| Número / texto | `0x0142` / `0x01d4` | `0x0143` / `0x01d5` |
| Loja | `0x00c4`, lista de compra `0x0b77`, de venda `0x00c7` | comprar/vender e a lista JSON de itens; a compra é recusada se faltar zeny |
| Armazém | inventário tipo 2 (`0x0b08`/`0x0b09`/`0x0b39`/`0x0b0b`) | `{"guardar": [...], "retirar": [...]}` |

## Como rodar

```
cd tools\ai_player
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

1. Crie a conta e o PIN da personagem no banco (tabela `login`), ou use a existente.
2. Crie `local.env` (fora do git) com a conta:
   ```
   AI_PLAYER_USER=...
   AI_PLAYER_PASS=...
   AI_PLAYER_PIN=...
   ```
3. Defina `ANTHROPIC_API_KEY` no ambiente (de preferência como variável de usuário do Windows, para não
   aparecer em linhas de comando). Opcional: `RATHENA_AI_MODEL` (padrão `claude-opus-5-5`).
4. Com o servidor no ar: `.venv\Scripts\python.exe agent.py`. Se a personagem ainda não existir, ela é criada
   no primeiro login.

Para depurar, o último texto enviado ao modelo fica em `last_prompt.txt`.

## Checklist (rodar a cada alteração)

Veja `tests/CHECKLIST.md`. Resumo:

```
.venv\Scripts\python.exe tests\run_checklist.py                  # nível 0: offline, sempre
.venv\Scripts\python.exe tests\run_checklist.py --live           # níveis 1-4 no jogo (agente parado)
.venv\Scripts\python.exe tests\live.py --only 1,4,5,15,18        # só alguns itens (ex.: navegação)
```

O teste no jogo usa a própria Lyra. Ele a coloca no centro de Prontera e completa zeny e poções no banco
antes do login, e não toca na memória dela.

## Como estender

- **Nova ação básica:** um encoder de pacote em `roclient.py` (confira o id em `packet_table.json`,
  `handlers`), uma função na API de `luaengine.py` e uma linha em `lua/API.md`, que é o texto que o modelo lê.
- **Novo comportamento:** uma rotina em `lua/base/` (primeira linha: para que serve; segunda: `-- args:`).
  Não escreva comportamento em Python.
- **Formato de pacote:** não conte bytes à mão. Escreva um `dump_*.cpp` em `protocol/` que imprime `offsetof`
  das structs do servidor e compile com `protocol/build.bat`.
- **Nova versão do cliente (`PACKETVER`):** regenere `packet_table.json` com `protocol/make_table.py`.

## Lições do protocolo

- O char-server envia o pedido de PIN sozinho e de novo a cada `0x08c5`, cada vez com outra semente: responda
  só a última.
- O servidor não leva o jogador até o alvo do ataque: responde `0x0139` ("longe demais"), e o cliente precisa
  chegar perto e atacar de novo.
- Os drops aparecem logo depois do pacote de morte: espere ~1,5 s antes de seguir para o próximo alvo.
- A área de um portal é retangular (`x ± spanx, y ± spany`): ande até dentro do lado menor.
- Nesta versão os ids de item têm 4 bytes, e a lista de compra da loja é `0x0b77`, não `0x00c6`.
- Zeny, velocidade, HP e SP só chegam na lista de personagens (`CHARACTER_INFO`); no mapa, o servidor só
  avisa quando mudam.
- O clique em NPC vale até `AREA_SIZE + 1` células (`npc_checknear`): não é preciso encostar no NPC.
- Durante uma caminhada, a posição conhecida é o fim do trecho confirmado, não onde ela está agora.

## Code review: estado e próximos passos

Feito neste review:

- Conta e PIN da Lyra saíram do código para `local.env` (fora do git). A senha e o PIN antigos foram trocados
  no banco, porque estão no histórico do git.
- Corrigida uma condição de corrida: a thread de regiões do atlas e o laço principal dividiam os caches de
  células sem trava.
- Removidos código morto (`World.nearby`) e imports sem uso. `pyflakes` passa sem avisos.

Recomendado, ainda não feito:

1. ~~Dividir `agent.py`~~: feito. As 1.250 linhas viraram oito módulos por responsabilidade (tabela no
   início), sem mudar comportamento. As constantes são lidas como `config.X`, e os testes as ajustam ali.
2. ~~Unificar o tratamento de eventos do `brain`~~: feito (`agent.on_event`). Corrigiu um bug: uma morte ou
   troca de mapa que chegava junto com outro evento perdia o efeito (ela não renascia, o lugar não era
   lembrado).
3. ~~Uma primitiva `FollowRoute(map, x, y)`~~: feito. `travel.lua` e `visit.lua` usam a mesma ação.
4. ~~Gravar a memória com menos frequência~~: feito. A memória vai para o disco no máximo a cada 5 s
   (`MIND_SAVE_INTERVAL`) e ao sair, com escrita atômica.
5. ~~Itens de NPC que falhavam no jogo~~: resolvidos. Ela clica de até 12 células, como o cliente oficial (o
   servidor aceita até `AREA_SIZE + 1`); espera o NPC aparecer quando ainda está andando; termina a rotina
   quando uma janela de NPC abre; e lê zeny, velocidade, HP e SP da lista de personagens, porque o servidor
   não os reenvia ao entrar no mapa.
6. **Chave da API:** a chave colada no chat deve ser revogada e trocada. A nova deve ficar só no ambiente do
   usuário.
