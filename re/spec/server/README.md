# Mapa do código do rAthena para o servidor do jogo novo

Levantamento feito no código desta branch (rAthena, modo Renewal, PACKETVER 20211103). Objetivo: separar o
**motor**, que o jogo novo mantém, dos **sistemas e conteúdo do Ragnarok**, que saem, e definir a ordem de
remoção.

## Tamanho por parte

| Pasta | Arquivos | Linhas | Papel |
| --- | ---: | ---: | --- |
| `src/common` | 47 | 17.016 | Base comum: laço principal, temporizadores, sockets, SQL, YAML, utilitários |
| `src/login` | 14 | 3.869 | Servidor de login (contas, sessões) |
| `src/char` | 36 | 14.084 | Servidor de personagens (lista, criação, gravação, comunicação entre servidores) |
| `src/map` | 2.577 | 250.567 | O jogo em si; 2.488 dos arquivos são habilidades (`map/skills/`) |
| `src/web` | 20 | 1.900 | Serviços HTTP do cliente oficial moderno |
| `src/tool` | 7 | 7.023 | Ferramentas: cache de mapas, conversores |
| `src/config`, `src/custom` | 14 | 512 | Configuração de compilação e pontos de extensão |

## O motor (fica)

| Arquivo(s) | Linhas | Função |
| --- | ---: | --- |
| `common/*` | 17.016 | Laço único com temporizadores, rede, banco de dados, leitura de dados |
| `login/*` | 3.869 | Autenticação |
| `char/*` | 14.084 | Personagens e persistência (enxugar junto com o map) |
| `map.cpp` | 4.697 | Mapas, células, blocos de unidades, área de visão |
| `clif.cpp` | 21.057 | Protocolo com o cliente: cada pacote recebido e enviado |
| `pc.cpp` | 13.822 | O jogador: atributos, nível, inventário, equipamento |
| `unit.cpp`, `path.cpp` | 4.000 | Movimento, caminho (A*), ataque contínuo |
| `battle.cpp` | 8.208 | Cálculo de dano e acerto |
| `status.cpp` | 14.701 | Atributos derivados e estados (buffs/debuffs) |
| `skill.cpp` | 14.398 | Motor de habilidades (as habilidades em si ficam em `skills/`) |
| `mob.cpp` | 6.192 | Monstros: dados, IA, nascimento, drops |
| `npc.cpp`, `script.cpp` | 29.795 | NPCs e a linguagem de script do conteúdo |
| `itemdb.cpp` | 3.999 | Banco de itens |
| `storage.cpp`, `trade.cpp`, `party.cpp`, `chat.cpp`, `channel.cpp` | 4.550 | Armazém, troca, grupo, chat |
| `chrif.cpp`, `intif.cpp` | 5.005 | Comunicação do map-server com o char-server |
| `atcommand.cpp`, `pc_groups.cpp` | 10.593 | Comandos de GM (úteis para testar) |
| `log.cpp`, `mapreg.cpp`, `date.cpp` | 1.066 | Registro, variáveis globais de script, datas |
| `quest.cpp` | 788 | Diário de missões: fica desligado no começo, mas o motor de script depende dele |

## Sistemas do Ragnarok (saem), em ordem de remoção

A ordem segue o quanto cada sistema é citado nos arquivos centrais (`pc`, `clif`, `battle`, `status`,
`unit`, `skill`, `map`, `mob`, `npc`, `script`, `chrif`, `intif`, `atcommand`): primeiro os menos
entrelaçados, para cada passo ser pequeno e testável.

| Ordem | Sistema | Arquivo | Citações no núcleo |
| ---: | --- | --- | ---: |
| 1 | Busca de lojas | `searchstore.cpp` | 18 |
| 2 | Lojas de jogador (venda) | `vending.cpp` | 36 |
| 3 | Lojas de jogador (compra) | `buyingstore.cpp` | 43 |
| 4 | Duelos | `duel.cpp` | 80 |
| 5 | Clãs | `clan.cpp` | 82 |
| 6 | Loja de dinheiro real | `cashshop.cpp` | 101 |
| 7 | Elementais | `elemental.cpp` | 118 |
| 8 | Mercenários | `mercenary.cpp` | 171 |
| 9 | Conquistas | `achievement.cpp` | 188 |
| 10 | Instâncias (masmorras privadas) | `instance.cpp` | 313 |
| 11 | Correio | `mail.cpp` | 376 |
| 12 | Campos de batalha | `battleground.cpp` | 417 |
| 13 | Bichinhos | `pet.cpp` | 439 |
| 14 | Homúnculos | `homunculus.cpp` | 590 |
| — | Clãs de guerra (guild) | `guild.cpp` | 783: **decidir depois**; o sistema social pode servir ao jogo, a guerra de castelos não |
| — | Gerador de navegação | `navi.cpp` | só existe no build gerador; sai junto com o `navigenerator` |
| — | Servidor web | `src/web` | o cliente novo não usa |

**Habilidades** (`map/skills/`, 2.488 arquivos): ficam só as do Aprendiz (`novice`) e as de monstros
(`npc`, `other`). As 14 árvores de classes do Ragnarok saem; o jogo novo define as suas depois.

**Conteúdo** (`db/`, `npc/`, `conf/`): nada do mundo do Ragnarok é carregado. O servidor novo começa com
um mapa de teste, depois o Condado; monstros, itens e NPCs são todos do jogo novo.

## Como cada remoção é feita

1. Retirar o arquivo do sistema e as suas chamadas no núcleo, deixando no lugar o comportamento "não
   existe" (por exemplo, um pacote do cliente para esse sistema passa a ser ignorado).
2. Compilar os quatro servidores.
3. Subir e passar no teste da alpha (entrar, andar, atacar, pegar item, morrer, chat).
4. Um commit por sistema removido.
