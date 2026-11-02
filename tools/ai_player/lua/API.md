Rotinas sao pequenos programas em Lua 5.4 que o seu corpo executa sozinho, a cada meio segundo, ate
terminarem ou voce trocar de rotina. Voce decide QUAL rotina rodar e com quais argumentos; a rotina decide
os passos. O formato segue a IA de homunculos do jogo: o motor oferece poucas acoes, a rotina decide
quando chama-las.

Formato de uma rotina:
  -- primeira linha: para que serve
  -- args: quais argumentos recebe (tabela args)
  local estado = ...          -- variaveis locais persistem entre as chamadas
  function Start(args) end    -- opcional: chamada uma vez ao comecar
  function Tick(args) end     -- obrigatoria: chamada a cada 0.5 s; faca pouco e retorne

Acoes e percepcao disponiveis (ids sao numeros; MyID e voce):
  GetTick()                      -> milissegundos
  GetActors()                    -> lista de ids de tudo a vista (jogadores, monstros, NPCs, portais)
  GetV(V_POSITION, id)           -> x, y           GetV(V_NAME, id) -> nome
  GetV(V_TYPE, id)               -> "player", "monster", "npc", "portal", ... ou nil se sumiu de vista
  GetV(V_TARGET, id)             -> id que ele atacou nos ultimos segundos, ou 0
  GetV(V_HP|V_MAXHP|V_SP|V_MAXSP, MyID) -> seus pontos
  IsMonster(id)                  -> 1 ou 0
  GetDistance(id)                -> celulas ate ele, ou -1
  FindByName(tipo, nome)         -> id do mais proximo com esse nome e tipo, ou 0
  GetLastSeen(nome)              -> x, y onde ele foi visto por ultimo, ou nil
  WasKilled(id)                  -> true se ele morreu a vista
  Move(x, y, span)               -> anda ate la (ou ate span celulas de la) pelo caminho do mapa; chame de novo
                                    enquanto nao chegar
  GetMap()                       -> nome do mapa onde voce esta
  Route(mapa, x, y)              -> passos ate outro mapa: lista de {map, x, y, span, to}; o ultimo e o destino.
                                    Ande ate o x, y do primeiro passo (com Move e o span) para pisar no portal.
                                    nil, motivo se nao houver caminho a pe
  FollowRoute(mapa, x, y, perto) -> um passo da viagem ate outro mapa (ou ate perto celulas de x, y; padrao 2):
                                    true ao chegar, false no caminho, nil e o motivo se nao houver caminho
  FindNpc(nome)                  -> NPCs com esse nome (ou parte dele), mais perto primeiro: lista de {name, map, x, y}
  IsMoving()                     -> true enquanto anda
  Stop()                         -> para de andar
  Attack(id)                     -> persegue e ataca; 2 = batendo, 1 = chegando perto, 0 = alvo invalido
  GetGroundItems()               -> lista de {id, name, x, y, amount, dist}
  PickUp(id)                     -> anda ate o item e pega
  GetInventory()                 -> lista de {name, amount, type, worn}
  UseItem(nome), Equip(nome), Unequip(nome) -> true se o item existe na mochila
  Talk(nome, x, y)               -> vai ate o NPC a vista e conversa (x, y escolhem entre NPCs de mesmo nome)
  GetNpcWait()                   -> nil, ou a janela de NPC aberta: {kind, name, options} (kind: menu, number,
                                    text, deal, buy, sell, storage)
  Reply(texto)                   -> responde a janela aberta como voce faria em npc_reply; retorna o que aconteceu
  Say(texto), Emote(nome)        -> fala no chat (sem acentos) / mostra emocao
  Notify(texto)                  -> avisa voce (sua mente) de algo importante; use pouco
  Done(texto)                    -> termina a rotina e conta o resultado para voce
  math, string, table, pairs, ipairs, tostring, tonumber, type, error

Seus reflexos continuam valendo durante qualquer rotina: tomar pocao com HP baixo e revidar quando um
monstro ataca. Uma rotina com erro, ou que demora demais num Tick, e parada e o erro chega para voce.
