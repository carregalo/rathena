# Protocolo: fluxo do teste "um jogador andando"

Versão de protocolo: **PACKETVER 20211103** (Renewal), sem ofuscação de ids de pacote.

Arquivos gerados a partir do código do servidor (não editar à mão; gerar com `re/tools/protocol/build.bat` e
`python re/tools/protocol/gen_lengths.py`):

| Arquivo | Conteúdo |
| --- | --- |
| `login_char.json` | Tamanho e posição dos campos dos pacotes de login e de personagem |
| `map.json` | Tabela de pacotes do map-server (o que ele lê, com tamanhos e posições lidas) e estruturas usadas no teste |
| `lengths.json` | Tamanho de **todo** pacote que os servidores enviam ao cliente (`-1` = variável: `uint16` com o tamanho total na posição 2). O cliente usa esta tabela para separar os pacotes no fluxo de bytes |

Todos os números são em little-endian. As posições abaixo são em bytes a partir do início do pacote (o id do
pacote ocupa as posições 0 e 1).

## 1. Login (porta 6900)

| Sentido | Pacote | Conteúdo |
| --- | --- | --- |
| cliente → | `0x0064` CA_LOGIN, 55 bytes | versão `uint32`@2 (o número PACKETVER), usuário `char[24]`@6, senha `char[24]`@30, tipo de cliente `uint8`@54 |
| ← servidor | `0x0ac4` AC_ACCEPT_LOGIN, variável | `login_id1` @4, conta (AID) @8, `login_id2` @12, sexo @46; a partir de @64, um bloco de 160 bytes por servidor de personagens: IP `uint32`@0 (em ordem de rede), porta `uint16`@4, nome `char[20]`@6 |
| ← servidor | `0x083e` AC_REFUSE_LOGIN, 26 bytes | código de erro `uint32`@2 (login recusado) |

O login fecha a conexão depois de responder.

## 2. Personagem (char-server, IP e porta recebidos no login)

| Sentido | Pacote | Conteúdo |
| --- | --- | --- |
| cliente → | `0x0065` CH_ENTER, 17 bytes | AID @2, `login_id1` @6, `login_id2` @10, sexo `uint8`@16 (fonte: `chclif_parse_reqtoconnect`, `src/char/char_clif.cpp`; não há struct) |
| ← servidor | 4 bytes crus | o AID, **sem id de pacote** — é preciso ler esses 4 bytes antes de começar a separar pacotes |
| ← servidor | `0x082d`, `0x006b`, `0x09a0`, `0x020d` | dados da conta e da lista, e quantas páginas de personagens existem (`chclif_mmo_char_send`) |
| cliente → | `0x09a1` CH_CHARLIST_REQ, 2 bytes | pede a lista |
| ← servidor | `0x0b72` HC_ACK_CHARINFO_PER_PAGE, variável | personagens a partir de @4, 175 bytes cada (`CHARACTER_INFO`: id @0, velocidade @82, classe @84, nível @92, nome `char[24]`@108, slot `uint8`@138). Uma página só com o cabeçalho (4 bytes) encerra a lista |
| cliente → | `0x0a39` CH_MAKE_CHAR, 36 bytes | cria o personagem: nome @2, slot @26, cor do cabelo @27, estilo @29, classe `uint32`@31, sexo @35 |
| ← servidor | `0x0b6f` HC_ACCEPT_MAKECHAR, 177 bytes / `0x006e` recusa, 3 bytes | personagem criado (`CHARACTER_INFO` @2) / erro @2 |
| cliente → | `0x0066` CH_SELECT_CHAR, 3 bytes | slot @2 |
| ← servidor | `0x0ac5` HC_NOTIFY_ZONESVR, 156 bytes | id do personagem (CID) @2, mapa `char[16]`@6, IP @22, porta @26 |

Com o PIN desligado no servidor (`pincode_enabled: no`), não há troca de PIN.

## 3. Mapa (map-server, IP e porta do passo anterior)

| Sentido | Pacote | Conteúdo |
| --- | --- | --- |
| cliente → | `0x0436` CZ_ENTER, 23 bytes | AID @2, CID @6, `login_id1` @10, hora do cliente @14, sexo `uint8`@22 (posições lidas por `clif_parse_WantToConnection`) |
| ← servidor | `0x0283`, 6 bytes | o AID |
| ← servidor | `0x02eb` ZC_ACCEPT_ENTER, 13 bytes | hora do servidor @2, posição e direção @6 (3 bytes, ver "Posições"), tamanho da célula @9 e @10 |
| cliente → | `0x007d` CZ_NOTIFY_ACTORINIT, 2 bytes | "terminei de carregar o mapa": a partir daqui o servidor manda o mundo à volta (status, inventário, unidades) |
| cliente → | `0x0360` CZ_REQUEST_TIME, 6 bytes | a cada ~12 s, hora do cliente @2 (mantém a conexão; o servidor responde `0x007f`) |

## 4. Andar

| Sentido | Pacote | Conteúdo |
| --- | --- | --- |
| cliente → | `0x035f` CZ_REQUEST_MOVE, 5 bytes | destino @2 (3 bytes, ver "Posições") |
| ← servidor | `0x0087` ZC_NOTIFY_PLAYERMOVE, 12 bytes | hora do início @2, origem e destino @6 (6 bytes) — só quando o servidor aceita o caminho |
| ← servidor | `0x0088` ZC_STOPMOVE, 10 bytes | unidade @2, x @6, y @8 — parou (por exemplo, caminho interrompido) |

Regras do servidor (`src/map/unit.cpp`, `src/map/path.cpp`):
- o caminho é calculado pelo servidor (8 direções; diagonal só com as duas células laterais livres) e tem no
  máximo 32 passos; destinos mais longes são recusados em silêncio;
- cada passo leva o tempo da velocidade do personagem (150 ms por célula por padrão), ×1,4 na diagonal;
- um novo pedido durante a caminhada troca o destino na próxima célula, sem parar.

## Posições compactadas

- **3 bytes (x, y, direção):** `x = b0 << 2 | b1 >> 6`; `y = (b1 & 0x3f) << 4 | b2 >> 4`; direção = `b2 & 0x0f`.
- **6 bytes (origem e destino):** `x0 = b0 << 2 | b1 >> 6`; `y0 = (b1 & 0x3f) << 4 | b2 >> 4`;
  `x1 = (b2 & 0x0f) << 6 | b3 >> 2`; `y1 = (b3 & 0x03) << 8 | b4`.

(Funções `WBUFPOS` e `WBUFPOS2` do servidor.)
