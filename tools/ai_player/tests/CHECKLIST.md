# Checklist da Lyra

Rode a checklist depois de **qualquer** alteração em `tools/ai_player` (cliente, corpo, motor Lua, rotinas,
atlas, prompt). Uma alteração só está pronta quando a checklist passa.

```
.venv\Scripts\python.exe tests\run_checklist.py            # nível 0 (sempre)
.venv\Scripts\python.exe tests\run_checklist.py --live     # níveis 1 a 4: servidor no ar, agente parado
.venv\Scripts\python.exe tests\run_checklist.py --live --llm   # nível 5: gasta créditos da API
```

O teste ao vivo usa a própria conta e personagem da Lyra. Antes de logar, ele a coloca no centro de Prontera
e completa 2000 zeny e 3 Red Potions no banco, para que toda execução comece igual. A memória dela não é
alterada. Resultados da última execução: `tests/last_live_results.json`.

## Nível 0 — offline (sem servidor, sem API)
| Teste | O que garante |
| --- | --- |
| `offline/test_1_inventory.py` | Leitura da mochila, coleta, uso, equipar e remoção de itens a partir de pacotes no formato do servidor |
| `offline/test_2_lua_engine.py` | Rotinas base (caçar com loot, seguir, explorar), reflexos (revidar, poção), rotina escrita por ela, e o isolamento do Lua (sem `os`, `io`, `load`, `debug`, objetos Python; laço sem fim parado) |
| `offline/test_3_travel_and_npcs.py` | Viagem Prontera → Geffen pelos portais e células reais; visita a um NPC em outro mapa; janelas de NPC: menu, número, loja (compra, venda, zeny insuficiente), armazém |

## Nível 1 — ações básicas no jogo
1. Conecta e entra no mapa
2. Recebe status e mochila
3. Enxerga unidades em volta
4. Anda até um ponto perto
5. Fala no chat público (o servidor devolve a fala)
6. Mostra uma emoção

## Nível 2 — itens e NPCs
7. Usa um item (Red Potion)
8. Tira e veste um equipamento
9. Conversa com um NPC e lê o menu (Guide de Prontera)
10. Escolhe uma opção de menu (Kafra: salvar ponto de retorno)

## Nível 3 — serviços e rotinas próprias
11. Compra numa loja (Tool Dealer)
12. Vende numa loja (Tool Dealer)
13. Roda uma rotina Lua escrita na hora

## Nível 4 — autonomia no mundo
14. Viaja para outro mapa pelos portais (Prontera → prt_fild08)
15. Caça e derrota um Poring
16. Acha e visita um NPC em outro mapa (Cleric, prt_church)
17. Volta para Prontera

## Nível 5 — com o modelo (opcional, custa créditos)
18. Toma uma decisão real com o modelo e a resposta tem todos os campos
