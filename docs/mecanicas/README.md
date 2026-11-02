# Mecânicas do Ragnarok Online no rAthena: análise para um jogo novo

Este documento descreve como o servidor rAthena (código aberto, GPL) implementa as mecânicas básicas do
Ragnarok Online, modo Renewal. Os números e as fórmulas vêm do código e dos bancos de dados deste repositório.
Cada seção aponta onde a regra está e termina com o que vale a pena levar como **ideia de design** para um
jogo original.

> **Limites de uso.** O servidor é GPL: copiar o código obriga o jogo novo a ser GPL também. O cliente, a arte,
> os mapas, a música, os nomes e os textos pertencem à Gravity e não podem ser usados. O que se aproveita
> daqui são as **ideias de sistema**: como estruturar atributos, combate, progressão e mundo. O jogo novo
> precisa de mundo, regras, números, nomes e arte próprios.

## Sumário

1. [Arquitetura](#1-arquitetura)
2. [O laço do servidor e o tempo](#2-o-laço-do-servidor-e-o-tempo)
3. [Mundo: mapas, células, visão e movimento](#3-mundo-mapas-células-visão-e-movimento)
4. [Personagem: atributos e valores derivados](#4-personagem-atributos-e-valores-derivados)
5. [Progressão: níveis, experiência e classes](#5-progressão-níveis-experiência-e-classes)
6. [Combate](#6-combate)
7. [Habilidades e estados](#7-habilidades-e-estados)
8. [Monstros: dados, IA, nascimento e drops](#8-monstros-dados-ia-nascimento-e-drops)
9. [Itens e equipamentos](#9-itens-e-equipamentos)
10. [NPCs, scripts e missões](#10-npcs-scripts-e-missões)
11. [Economia e social](#11-economia-e-social)
12. [Dados e configuração](#12-dados-e-configuração)
13. [O que levar para o jogo novo](#13-o-que-levar-para-o-jogo-novo)

---

## 1. Arquitetura

Quatro processos, todos em C++ (`src/`), com o estado persistido em MySQL/MariaDB:

| Servidor | Porta | Função |
| --- | --- | --- |
| `login-server` | 6900 | Conta e senha, sessão, escolha do servidor de personagens |
| `char-server` | 6121 | Lista, criação e seleção de personagens, PIN; grava o personagem no banco |
| `map-server` | 5121 | **O jogo em si**: mundo, movimento, combate, NPCs, itens, chat |
| `web-server` | 8888 | Serviços HTTP do cliente moderno (emblemas, configurações) |

O cliente conecta em sequência login → char → map, passando credenciais de sessão de um para o outro. Dentro
do jogo, cliente e servidor trocam pacotes binários curtos (2 bytes de id + campos fixos ou com tamanho).
O servidor é **autoritativo**: o cliente só pede ("quero andar até x,y", "quero atacar o id N"), e o servidor
decide, calcula e avisa todos que estão vendo.

- Tabela de pacotes: `src/map/clif_packetdb.hpp`, estruturas em `src/map/packets*.hpp`.
- Tratamento de cada pedido: `clif_parse_*` em `src/map/clif.cpp`.

**Para o jogo novo:** separar autenticação, personagens e mundo em serviços distintos escala bem, e o
modelo "cliente pede, servidor decide" é o que impede trapaça. O protocolo binário próprio pode ser trocado
por algo mais simples (WebSocket com mensagens tipadas) sem perder nada de essencial.

## 2. O laço do servidor e o tempo

O map-server roda num **único thread**: `Core::start` (`src/common/core.cpp`) repete
`do_timer()` (executa os temporizadores vencidos) e `do_sockets()` (lê e trata pacotes). Toda ação com
duração é um temporizador (`add_timer` em `src/common/timer.hpp`): passo de caminhada, golpe seguinte,
renascimento de monstro, fim de um efeito.

- Uma ação lenta no laço (uma consulta pesada ao banco) congela o mundo para todos.
- Não há "tick" global fixo de jogo: cada unidade tem seus próprios temporizadores, com precisão de ms.

**Para o jogo novo:** o modelo de temporizadores por entidade é simples e determinístico. Um laço único
facilita a consistência; para escalar, divide-se por mapa (cada mapa num processo ou thread).

## 3. Mundo: mapas, células, visão e movimento

- **Mapa = grade de células.** Cada célula é andável, parede, água andável ou abismo
  (`map_gat2cell` em `src/map/map.cpp`). As grades ficam compactadas em `db/map_cache.dat`.
- **Visão:** cada jogador recebe tudo o que está num quadrado de `area_size` = 14 células
  (`conf/battle/client.conf`). Quem entra ou sai desse quadrado gera pacotes de "apareceu" e "sumiu".
- **Movimento:** o servidor calcula o caminho com A* em 8 direções; a diagonal só é permitida se as duas
  células laterais estiverem livres, e um pedido é limitado a 32 passos (`path_search`,
  `MAX_WALKPATH` em `src/map/path.cpp/.hpp`). A velocidade padrão é 150 ms por célula, e a diagonal custa
  ×1,4 (`unit.cpp`). Um novo pedido durante a caminhada só troca o destino na próxima célula.
- **Portais:** NPCs do tipo `warp` com uma área retangular; pisar dentro dela troca de mapa
  (scripts em `npc/re/warps/`).
- **Navegação do cliente (`/navi`):** gerada pelo próprio servidor a partir dos mapas, portais e NPCs
  (`navigenerator.bat` → `src/map/navi.cpp`).

**Para o jogo novo:** grade de células com área de interesse quadrada é a forma mais barata de sincronizar um
mundo grande. Validar o caminho no servidor e deixar o cliente pedir trechos curtos dá movimento fluido sem
confiar no cliente.

## 4. Personagem: atributos e valores derivados

Seis atributos primários, de 1 a `max_parameter` = 99 em Renewal (`conf/battle/player.conf`): **STR, AGI,
VIT, INT, DEX, LUK**. Classes avançadas têm ainda seis "traits" (POW, STA, WIS, SPL, CON, CRT).

**Pontos para distribuir:** tabela por nível em `db/re/statpoint.yml` (48 no nível 1, 80 no 10, 1.273 no 99).
Subir um atributo custa mais quanto mais alto ele está (`pc_need_status_point`).

**Valores derivados** (`status_calc_misc` em `src/map/status.cpp`, Renewal, para jogadores):

| Valor | Fórmula |
| --- | --- |
| Precisão (HIT) | 175 + nível + DEX + LUK/3 (+ bônus) |
| Esquiva (FLEE) | 100 + nível + AGI + LUK/5 (+ bônus) |
| Defesa leve (soft DEF) | (nível + VIT)/2 + AGI/5 |
| Defesa mágica leve (soft MDEF) | INT + nível/4 + (DEX + VIT)/5 |
| Ataque base (status ATK) | STR + DEX/5 + LUK/3 + nível/4 (corpo a corpo; à distância troca STR e DEX) |
| HP máximo | HP base da classe no nível × (1 + VIT/100), ×1,25 para classes renascidas |
| SP máximo | SP base da classe no nível × (1 + INT/100), idem |
| Velocidade de ataque (ASPD) | √(DEX²/5 + AGI²/2) × 0,25 + 196, menos a penalidade da arma da classe; teto `max_aspd` = 190 |

O HP e o SP base vêm de tabelas por classe e nível (`db/re/job_basepoints.yml`), não de fórmula.
A penalidade de arma por classe está em `db/re/job_aspd.yml` (`status_base_amotion_pc`).

**Para o jogo novo:** o padrão "atributos primários → valores derivados por fórmulas lineares simples →
tabelas por classe para o que precisa de curva" é fácil de balancear. Vale reduzir para 3 ou 4 atributos com
papéis claros (no RO, LUK e DEX têm efeitos difusos, difíceis de explicar ao jogador).

## 5. Progressão: níveis, experiência e classes

- **Dois níveis independentes:** nível de base (atributos, HP) e nível de classe (pontos de habilidade).
  Cada monstro dá experiência de base e de classe separadas.
- **Curva de experiência:** tabela em `db/re/job_exp.yml`. Exemplo para o nível de base: 548 (nível 1→2),
  5.337 (10), 42.165 (50), 1.252.761 (98). Cresce rápido nos níveis altos.
- **Penalidade por diferença de nível:** monstros muito acima ou abaixo do jogador dão menos experiência e
  drops (`db/re/level_penalty.yml`).
- **Morte:** perde 1% da experiência do nível (`death_penalty_base/job` em `conf/battle/exp.conf`).
- **Taxas globais:** `base_exp_rate`, `job_exp_rate` (100 = oficial).
- **Classes:** Aprendiz → primeira classe (Espadachim, Mago...) → segunda → transcendental → terceira →
  quarta. A troca acontece por missão com NPC (`npc/re/jobs/`), e a árvore de habilidades de cada classe
  fica em `db/re/skill_tree.yml`. Ids de classe em `enum e_job` (`src/common/mmo.hpp`).

**Para o jogo novo:** a separação nível de base / nível de classe dá duas fontes de progresso ao mesmo
tempo e ajuda a sensação de evolução constante. A troca de classe por missão transforma progressão em
conteúdo.

## 6. Combate

### Cadência
Um ataque automático repete enquanto o alvo estiver ao alcance; o intervalo vem da ASPD. O servidor não leva
o atacante até o alvo: se estiver longe, responde "longe demais" e o cliente aproxima e pede de novo
(`unit_attack_timer_sub` em `src/map/unit.cpp`).

### Acertou? (`is_attack_hitting` em `src/map/battle.cpp`)
- Crítico, golpe perfeito e alguns efeitos acertam sempre.
- Senão: chance = HIT do atacante − FLEE do alvo (Renewal parte de 0; pré-Renewal partia de 80), limitada
  entre `min_hitrate` = 5% e `max_hitrate` = 100% (`conf/battle/battle.conf`).
- Muitos atacantes reduzem a esquiva do alvo (`agi_penalty_*`): cercar alguém funciona.

### Quanto dano? (pipeline de `battle_calc_weapon_attack`)
1. Ataque base: ataque de atributos + ataque da arma × modificador de tamanho (pequeno/médio/grande)
   + ataque de equipamento.
2. × razão da habilidade (100% no ataque comum).
3. × tabela de elementos: elemento do ataque contra elemento e nível do alvo (`db/re/attr_fix.yml`;
   por exemplo, Água contra Fogo = 150%, Água contra Água = 25%).
4. × bônus de cartas e equipamentos por raça, tamanho e elemento (`battle_calc_cardfix`).
5. **Defesa (Renewal):** `dano × (4000 + DEF) / (4000 + 10 × DEF) − DEF leve`
   (`battle_calc_defense_reduction`). DEF alta tem retorno decrescente e nunca anula o dano.
6. Efeitos finais (barreiras, redução por estados) em `battle_calc_damage`.

Ataques mágicos (`battle_calc_magic_attack`) seguem o mesmo esquema com MATK e MDEF.

**Para o jogo novo:** a fórmula de defesa com retorno decrescente evita personagens imunes. A tabela de
elementos e a de tamanhos criam escolhas táticas (qual arma ou magia usar contra qual inimigo) com pouco
código. O piso de 5% de acerto garante que todo ataque tenha chance.

## 7. Habilidades e estados

- **Habilidades** (`db/re/skill_db.yml`): nível máximo, tipo (arma, mágica, outra), alvo, alcance, número de
  golpes, elemento, custo de SP por nível, tempos de conjuração, atraso e recarga. Exemplo: Bash, 10 níveis,
  8 SP do nível 1 ao 5 e 15 do 6 ao 10. A lógica de cada uma está em `src/map/skill.cpp` e nas razões de dano
  de `battle_calc_attack_skill_ratio`.
- **Estados (buffs e debuffs)** (`db/re/status.yml`, `src/map/status.cpp`): bênção, veneno, atordoamento etc.
  Têm duração, chance de resistência por atributo e ícone no cliente.

**Para o jogo novo:** descrever habilidades em dados (custo, alcance, tempos) e só a parte única em código
deixa o balanceamento nas mãos do design, sem recompilar.

## 8. Monstros: dados, IA, nascimento e drops

**Dados** (`db/re/mob_db.yml`), exemplo do Poring: nível 1, 55 HP, 150 exp de base e 40 de classe, ataque 1,
alcance 1, perseguição até 12 células, tamanho médio, raça planta, elemento Água 1, velocidade 400 ms por
célula, intervalo de ataque 1.872 ms, IA tipo 02.

**IA** (`mob_ai_sub_hard` e afins em `src/map/mob.cpp`; tipos em `doc/mob_db_mode_list.txt`):
uma máquina de estados (parado → perseguir → atacar) controlada por bits de comportamento:

| Bit | Efeito |
| --- | --- |
| Aggressive | ataca quem chega perto, sem ser provocado |
| Looter | pega itens do chão quando está parado |
| Assist | ajuda monstros da mesma espécie que estão lutando |
| CastSensor | reage a quem começa a conjurar magia perto |
| ChangeTarget | troca de alvo para quem o ataca |
| CanMove / CanAttack | monstros fixos (plantas) não andam nem atacam |
| Boss / MVP | imunidades e recompensas especiais |

Combinações prontas: 01 passivo, 02 passivo que coleta, 04/05 agressivo, 06 planta, 21 agressivo completo.
Quando parado, o monstro anda ao acaso (`mob_randomwalk`). Monstros podem usar habilidades por condição
(`db/re/mob_skill_db.txt`).

**Nascimento:** linhas de spawn nos scripts, por exemplo
`prt_fild08,0,0	monster	Poring	1002,20,5000`: 20 Porings em qualquer ponto do mapa, renascendo 5 s após
morrer. O monstro renasce com o mesmo id (`mob_setdelayspawn`).

**Drops:** cada monstro tem uma lista de itens com chance em 1/10.000 (Jellopy 7000 = 70%; faca 100 = 1%),
multiplicada pelas taxas de `conf/battle/drops.conf` e pela penalidade de nível. Os itens caem no chão perto
do corpo, logo depois da morte.

**Para o jogo novo:** os bits de comportamento combinados geram variedade de inimigos com uma IA só. A
experiência separada por tipo e a tabela de drops por chance são a base do ciclo "caçar → ganhar → equipar".

## 9. Itens e equipamentos

- **Tipos** (`db/re/item_db_*.yml`): cura, usável, material, arma, armadura, carta, ovo de bichinho,
  munição, pacote. Campos comuns: preço de compra, peso, slots de carta, onde se equipa, classes e nível
  mínimos, e um **script** com o efeito.
- **O efeito é script.** Exemplo: a Red Potion tem `itemheal rand(45,65),0;`. Equipamentos usam `bonus` para
  somar atributos e modificadores.
- **Peso:** a capacidade depende de STR e da classe. Em Renewal, a partir de 70% o personagem para de
  regenerar (`natural_heal_weight_rate`), e a partir de 90% também não ataca nem usa habilidades
  (`major_overweight_rate`, `conf/battle/player.conf`).
- **Refino** (`db/re/refine.yml`): +1 a +20 com chance de falhar e quebrar o item.
- **Cartas:** encaixadas em slots, somam bônus.
- **Combos:** conjuntos de itens com bônus extra (`db/re/item_combos.yml`).

**Para o jogo novo:** item = dados + pequeno script de efeito é muito flexível. Refino com risco e cartas em
slots criam metas de longo prazo e mercado entre jogadores.

## 10. NPCs, scripts e missões

- Toda a lógica de conteúdo (NPCs, lojas, portais, missões, eventos, troca de classe) é escrita numa
  linguagem de script própria, interpretada pelo map-server (`src/map/script.cpp`; referência completa em
  `doc/script_commands.txt`).
- Uma conversa é uma sequência de comandos: `mes` (texto), `next` (botão "próximo"), `select("a:b:c")`
  (menu), `input` (número ou texto), `close`. Cada um vira um pacote para o cliente.
- **Missões:** o diário de missões do cliente usa `db/re/quest_db.yml`; o progresso fica em variáveis do
  personagem.
- **Lojas:** NPCs do tipo `shop` com a lista de itens e preços.

**Para o jogo novo:** separar motor (C++) e conteúdo (script) permite que quem cria missões não mexa no
servidor. Uma linguagem pronta e conhecida (Lua) evita manter um interpretador próprio.

## 11. Economia e social

- **Zeny:** a moeda. Entra pela venda de itens a NPCs e por missões; sai em compras, refino e serviços.
- **Armazém** compartilhado entre os personagens da conta (Kafra), **troca** direta entre jogadores,
  **lojas de jogador** (vending e buying store).
- **Grupo (party):** divide experiência entre membros com até 15 níveis de diferença
  (`party_share_level` em `conf/inter_athena.conf`).
- **Clã (guild):** níveis, habilidades de clã e a guerra por castelos (War of Emperium, `npc/guild/`).
- **Chat:** público por área, sussurro, grupo e clã.

**Para o jogo novo:** o que segura um MMO é o social. Divisão de experiência em grupo e um objetivo coletivo
(os castelos) criam motivo para jogar junto.

## 12. Dados e configuração

| O que mudar | Onde |
| --- | --- |
| Taxas de experiência e drops | `conf/battle/exp.conf`, `conf/battle/drops.conf` |
| Regras de combate e de jogador | `conf/battle/battle.conf`, `conf/battle/player.conf` |
| Monstros, itens, habilidades, classes | `db/re/*.yml` (sobrescreva em `db/import/`) |
| Mapas e portais | `db/map_cache.dat`, `npc/re/warps/` |
| Conteúdo (NPCs, missões) | `npc/` (custom em `npc/custom/`) |
| Persistência | banco SQL (`sql-files/main.sql`) |

O padrão do rAthena é: **regras no código, números nos dados, conteúdo em script, ajustes de servidor em
configuração.** Quase todo balanceamento acontece sem recompilar.

## 13. O que levar para o jogo novo

Ideias que funcionam e vale reaproveitar, com a sua própria versão:

1. Servidor autoritativo, mundo em grade de células, área de interesse quadrada.
2. Temporizadores por entidade num laço único por mapa.
3. Poucos atributos primários, valores derivados por fórmulas simples, curvas em tabela.
4. Dois eixos de progresso (nível e classe) e troca de classe como conteúdo.
5. Acerto contra esquiva com piso e teto; defesa com retorno decrescente; tabelas de elemento e tamanho.
6. Habilidades, monstros e itens descritos em dados; o único código é o efeito específico.
7. IA de monstros por bits de comportamento combinados.
8. Drops por chance, refino com risco e encaixes, para metas de longo prazo e mercado.
9. Conteúdo em linguagem de script separada do motor.
10. Sistemas sociais (grupo, clã, objetivo coletivo) desde o começo.

O que **não** levar: código copiado (licença GPL), nomes, monstros, mapas, arte, música, textos e o
cliente da Gravity. Também vale evitar o que o RO tem de difícil de explicar: atributos com efeitos
espalhados (LUK), dezenas de exceções por habilidade dentro das fórmulas de dano, e o peso que bloqueia
regeneração e ataque.

### Próximos passos sugeridos

- Definir o gênero e o escopo do jogo novo (MMO, cooperativo pequeno, single player com servidor?).
- Escolher o que manter do modelo acima e escrever um documento de design com os números próprios.
- Decidir a tecnologia (motor do cliente, linguagem do servidor). Este repositório pode continuar servindo de
  referência e de banco de testes, inclusive com agentes como a Lyra testando as mecânicas.
