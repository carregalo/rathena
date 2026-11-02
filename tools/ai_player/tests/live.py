"""Live checklist: Lyra logs in to the running server and performs each action for real, from the most basic
to the most complex. The model is not called (no API cost) unless --llm is given.

Run with the agent stopped: the same account cannot be online twice. Before logging in, the test setup puts
her in Prontera's centre and tops up 2000 zeny and 3 Red Potions in the database, so every run starts from
the same place. Her memory file is not touched (a temporary Mind is used).

    python tests/live.py            # levels 1 to 4
    python tests/live.py --llm      # also level 5: one real decision by the model
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import agent  # noqa: E402
import atlas  # noqa: E402
import luaengine  # noqa: E402
import roclient  # noqa: E402
from luaengine import cells  # noqa: E402

DB = os.environ.get("AI_PLAYER_DB_CMD", "docker exec rathena-db mariadb -uragnarok -pragnarok ragnarok -N -e").split()
RESULTS = os.path.join(HERE, "tests", "last_live_results.json")
RED_POTION, JELLOPY = 501, 909


def sql(query):
    return subprocess.run(DB + [query], capture_output=True, text=True, check=True).stdout.strip()


def prepare():
    """Same starting point every run: Prontera's centre, enough zeny and potions for the shop and item tests."""
    who = f"name='{agent.NAME}'"
    char_id = sql(f"SELECT char_id FROM `char` WHERE {who}")
    if not char_id:
        raise SystemExit(f"character {agent.NAME} not found")
    if sql(f"SELECT online FROM `char` WHERE {who}") != "0":
        raise SystemExit(f"{agent.NAME} is online: stop the agent before the live checklist")
    sql(f"UPDATE `char` SET last_map='prontera', last_x=156, last_y=191, zeny=GREATEST(zeny, 2000) WHERE {who}")
    have = int(sql(f"SELECT COALESCE(SUM(amount), 0) FROM inventory WHERE char_id={char_id} AND nameid={RED_POTION}"))
    if have < 3:
        sql(f"INSERT INTO inventory (char_id, nameid, amount, identify) VALUES ({char_id}, {RED_POTION}, {3 - have}, 1)")


class Lyra:
    """The real client, body and Lua engine, without the brain: each check drives them directly."""

    def __init__(self):
        self.names = agent.load_item_names()
        self.atlas = atlas.Atlas()
        self.events = []  # (time, kind, what)

    async def start(self):
        self.client = roclient.Client(agent.HOST, agent.USER, agent.PASSWORD, agent.PIN, agent.NAME, sex=agent.SEX)
        await self.client.connect()
        self.mind = agent.Mind(os.path.join(tempfile.mkdtemp(), "mind.json"))
        self.body = agent.Body(self.client, self.mind, self.names, self.atlas)
        self.tasks = [asyncio.create_task(self.client.run()), asyncio.create_task(self.body.run()),
                      asyncio.create_task(self._collect())]

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        self.client.close()

    async def _collect(self):
        while True:
            kind, what = await self.client.events.get()
            self.events.append((time.time(), kind, what))

    @property
    def w(self):
        return self.client.world

    async def until(self, cond, timeout, step=0.1):
        end = time.time() + timeout
        while time.time() < end:
            if any(t.done() and t.exception() for t in self.tasks):
                raise AssertionError(f"conexao caiu: {[t.exception() for t in self.tasks if t.done()]}")
            value = cond()
            if value:
                return value
            await asyncio.sleep(step)
        return None

    def event(self, kinds, since):
        return next(((k, v) for t, k, v in self.events if t >= since and k in kinds), None)

    async def routine(self, name, args, timeout):
        since = time.time()
        err = self.body.engine.start(name, json.dumps(args))
        assert err is None, err
        got = await self.until(lambda: self.event(("routine_done", "routine_error"), since), timeout)
        self.body.engine.stop()
        assert got, f"{name} nao terminou em {timeout}s (esta em {self.w.map} {self.w.x},{self.w.y})"
        assert got[0] == "routine_done", got[1]
        return got[1]

    def item(self, item_id):
        return next((i for i in self.w.inventory.values() if i.item_id == item_id), None)

    def count(self, item_id):
        return sum(i.amount for i in self.w.inventory.values() if i.item_id == item_id)

    async def open_npc(self, npc, kind, npc_map=None, timeout=120):
        """visit routine, then wait for the NPC window of the given kind."""
        args = {"npc": npc, **({"map": npc_map} if npc_map else {})}
        done = await self.routine("visit", args, timeout)
        wait = await self.until(lambda: self.w.npc_wait if self.w.npc_wait and self.w.npc_wait["kind"] == kind else None, 15)
        assert wait, f"{npc} nao abriu uma janela {kind} ({done})"
        return wait

    async def answer(self, text):
        return agent.answer_npc(self.client, self.body, text)


# ---------------------------------------------------------------- the checklist, from basic to complex

async def c_login(l):
    assert l.w.map and l.w.account_id, "nao entrou em nenhum mapa"
    return f"{l.w.map} {l.w.x},{l.w.y}"


async def c_status(l):
    ok = await l.until(lambda: l.w.max_hp > 0 and l.w.inventory, 10)
    assert ok, "status ou mochila nao chegaram"
    return f"HP {l.w.hp}/{l.w.max_hp}, {len(l.w.inventory)} itens, {l.w.zeny} zeny"


async def c_sees(l):
    ok = await l.until(lambda: len(l.w.units) > 0, 10)
    assert ok, "nenhuma unidade a vista"
    kinds = sorted({u.kind for u in l.w.units.values()})
    return f"{len(l.w.units)} unidades ({', '.join(kinds)})"


async def c_walk(l):
    x0, y0 = l.w.x, l.w.y
    target = next(((x0 + dx, y0 + dy) for dx, dy in ((5, 0), (-5, 0), (0, 5), (0, -5), (4, 4), (-4, -4))
                   if l.atlas.walkable(l.w.map, x0 + dx, y0 + dy)), None)
    assert target, "nenhuma celula livre perto"
    assert l.body.go(*target), "o atlas nao achou caminho"
    ok = await l.until(lambda: (l.w.x, l.w.y) == target and l.w.last_walk_result == "ok", 15)
    assert ok, f"nao chegou em {target}: esta em {l.w.x},{l.w.y} ({l.w.last_walk_result})"
    return f"{x0},{y0} -> {target[0]},{target[1]}"


async def c_walk_far(l):
    x0, y0 = l.w.x, l.w.y
    spot = next((s for s in (l.atlas.nearest_walkable(l.w.map, x0 + dx, y0 + dy, 6)
                             for dx, dy in ((0, 80), (0, -80), (80, 0), (-80, 0))) if s
                 and l.atlas.path(l.w.map, (x0, y0), s)), None)
    assert spot, "nenhum ponto alcancavel a 80 celulas"
    path = [(x0, y0)] + l.atlas.path(l.w.map, (x0, y0), spot)
    steps = sum(1.4 if a[0] != b[0] and a[1] != b[1] else 1 for a, b in zip(path, path[1:]))
    ideal = steps * (l.w.speed or roclient.DEFAULT_SPEED) / 1000  # walking the whole path without a stop
    t = time.time()
    done = await l.routine("go", {"x": spot[0], "y": spot[1]}, 90)
    assert (l.w.x, l.w.y) == spot, done
    await l.until(lambda: time.time() >= l.w.walk_until, 10)  # until she really stands there
    took = time.time() - t
    assert took < ideal * 1.25 + 1, f"lento demais: {took:.1f}s para um caminho de {ideal:.1f}s (paradas no caminho)"
    return f"{x0},{y0} -> {spot[0]},{spot[1]} em {took:.1f}s (sem paradas seriam {ideal:.1f}s)"


async def c_chat(l):
    text = "teste da checklist"
    assert l.client.say(text), "o chat recusou (limite de 3 s?)"
    ok = await l.until(lambda: text in l.w.own_chat, 5)
    assert ok, "o servidor nao devolveu a fala"
    return l.w.own_chat


async def c_emote(l):
    l.client.emote("smile")
    await asyncio.sleep(0.5)
    return "enviado"


async def c_use_item(l):
    potion = l.item(RED_POTION)
    assert potion, "sem Red Potion"
    since, before = time.time(), l.count(RED_POTION)
    l.body.use_item(potion.index)
    ok = await l.until(lambda: any(t >= since and what == "used" and i == RED_POTION for t, what, i, _ in l.w.item_log), 5)
    assert ok, "o servidor nao confirmou o uso"
    return f"Red Potion {before} -> {l.count(RED_POTION)}"


async def c_equip(l):
    worn = next((i for i in l.w.inventory.values() if i.worn and i.type == 4), None) or \
        next((i for i in l.w.inventory.values() if i.worn), None)
    assert worn, "nada vestido para testar"
    name = l.names.get(worn.item_id, worn.item_id)
    l.client.unequip(worn.index)
    assert await l.until(lambda: l.w.inventory[worn.index].worn == 0, 5), f"nao tirou {name}"
    l.client.equip(worn.index)
    assert await l.until(lambda: l.w.inventory[worn.index].worn != 0, 5), f"nao vestiu {name} de novo"
    return f"tirou e vestiu {name}"


async def c_npc_dialog(l):
    wait = await l.open_npc("Guide", "menu", "prontera")
    options = [o for o in wait["options"] if o]
    await l.answer("sair")
    assert await l.until(lambda: l.w.npc_wait is None, 5), "a janela nao fechou"
    return f"menu com {len(options)} opcoes: {' / '.join(options[:4])}"


async def c_kafra_menu(l):
    wait = await l.open_npc("Kafra Employee", "menu", "prontera")
    since = time.time()
    result = await l.answer("save")
    assert result.startswith("voce escolheu"), result
    got = await l.until(lambda: l.event(("npc_dialog", "npc_wait"), since), 15)
    assert got, "a Kafra nao respondeu a escolha"
    if l.w.npc_wait:
        await l.answer("sair")
    return f"{result}; resposta: {' '.join(got[1][1])[:80]}"


async def c_shop_buy(l):
    await l.open_npc("Tool Dealer", "deal", "prt_in")
    await l.answer("comprar")
    assert await l.until(lambda: l.w.npc_wait and l.w.npc_wait["kind"] == "buy", 5), "a lista de compra nao veio"
    since, zeny, before = time.time(), l.w.zeny, l.count(RED_POTION)
    result = await l.answer('[{"item": "Red Potion", "amount": 1}]')
    got = await l.until(lambda: l.event(("shop_result",), since), 10)
    assert got and "deu certo" in got[1], f"{result}; {got}"
    assert await l.until(lambda: l.count(RED_POTION) == before + 1, 5), "a pocao nao entrou na mochila"
    return f"comprou 1 Red Potion: {zeny} -> {l.w.zeny} zeny"


async def c_shop_sell(l):
    await l.open_npc("Tool Dealer", "deal", "prt_in")
    await l.answer("vender")
    assert await l.until(lambda: l.w.npc_wait and l.w.npc_wait["kind"] == "sell", 5), "a lista de venda nao veio"
    sellable = {index for index, _ in l.w.npc_wait["items"]}
    item = next((i for i in l.w.inventory.values() if i.item_id == JELLOPY and i.index in sellable), None) or \
        next((i for i in l.w.inventory.values() if i.item_id == RED_POTION and i.index in sellable), None)
    assert item, "nada para vender"
    name = l.names[item.item_id]
    since, zeny = time.time(), l.w.zeny
    await l.answer(json.dumps([{"item": name, "amount": 1}]))
    got = await l.until(lambda: l.event(("shop_result",), since), 10)
    assert got and "deu certo" in got[1], str(got)
    assert await l.until(lambda: l.w.zeny > zeny, 5), "o zeny nao aumentou"
    return f"vendeu 1 {name}: {zeny} -> {l.w.zeny} zeny"


async def c_learned_routine(l):
    x0, y0 = l.w.x, l.w.y
    spot = next(((x0 + dx, y0 + dy) for dx, dy in ((3, 0), (-3, 0), (0, 3), (0, -3))
                 if l.atlas.walkable(l.w.map, x0 + dx, y0 + dy)), None)
    assert spot, "nenhuma celula livre perto"
    code = ("-- Teste da checklist: vai ate um ponto e termina.\n"
            "function Tick(args)\n"
            "  local x, y = GetV(V_POSITION, MyID)\n"
            "  if x == args.x and y == args.y then Done('cheguei') return end\n"
            "  Move(args.x, args.y)\n"
            "end\n")
    learned = luaengine.LEARNED_DIR
    tmp = tempfile.mkdtemp()
    luaengine.LEARNED_DIR = tmp  # never leave the test routine among her own
    try:
        err = l.body.engine.write("checklist_teste", "", code)
        assert err is None, err
        done = await l.routine("checklist_teste", {"x": spot[0], "y": spot[1]}, 30)
    finally:
        luaengine.LEARNED_DIR = learned
        l.body.engine.routines.pop("checklist_teste", None)
        shutil.rmtree(tmp, ignore_errors=True)
    return done


async def c_travel(l):
    done = await l.routine("travel", {"map": "prt_fild08"}, 300)
    assert l.w.map == "prt_fild08", done
    return done


async def c_hunt(l):
    kills = l.body.kills
    done = await l.routine("hunt", {"monster": "Poring", "limit": 1}, 300)
    assert l.body.kills > kills, done
    return f"{done}; HP {l.w.hp}/{l.w.max_hp}"


async def c_visit_far(l):
    await l.open_npc("Cleric", "menu", "prt_church", timeout=420)
    await l.answer("sair")
    return f"chegou ao Cleric em {l.w.map} {l.w.x},{l.w.y}"


async def c_back_home(l):
    return await l.routine("travel", {"map": "prontera", "x": 156, "y": 191}, 300)


async def c_llm_decision(l):
    obs = agent.observation(l.client, l.mind, l.body, l.names, "teste da checklist: decida o que fazer", False)
    import anthropic
    d = await agent.decide(anthropic.AsyncAnthropic(), obs)
    missing = [k for k in agent.DECISION_SCHEMA["required"] if k not in d]
    assert not missing, f"faltaram campos: {missing}"
    return f"routine={d['routine']!r} say={d['say'][:40]!r}"


CHECKLIST = [
    (1, "conecta e entra no mapa", c_login, 0),
    (1, "recebe status e mochila", c_status, 0),
    (1, "enxerga unidades em volta", c_sees, 0),
    (1, "anda ate um ponto perto", c_walk, 0),
    (1, "anda longe no mesmo mapa (varios trechos)", c_walk_far, 0),
    (1, "fala no chat publico", c_chat, 0),
    (1, "mostra uma emocao", c_emote, 0),
    (2, "usa um item (Red Potion)", c_use_item, 0),
    (2, "tira e veste um equipamento", c_equip, 0),
    (2, "conversa com um NPC e le o menu (Guide)", c_npc_dialog, 0),
    (2, "escolhe uma opcao de menu (Kafra: salvar)", c_kafra_menu, 0),
    (3, "compra numa loja (Tool Dealer)", c_shop_buy, 0),
    (3, "vende numa loja (Tool Dealer)", c_shop_sell, 0),
    (3, "roda uma rotina Lua escrita na hora", c_learned_routine, 0),
    (4, "viaja para outro mapa pelos portais", c_travel, 0),
    (4, "caca e derrota um Poring", c_hunt, 0),
    (4, "acha e visita um NPC em outro mapa (Cleric)", c_visit_far, 0),
    (4, "volta para Prontera", c_back_home, 0),
    (5, "toma uma decisao real com o modelo", c_llm_decision, 1),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="also run level 5 (calls the model, costs API credits)")
    ap.add_argument("--max-level", type=int, default=5)
    ap.add_argument("--only", default="", help="comma-separated item numbers of the checklist, e.g. 1,4,5,15,18")
    opts = ap.parse_args()
    only = {int(n) for n in opts.only.split(",") if n.strip()}
    prepare()
    lyra = Lyra()
    results = []
    try:
        await lyra.start()
        await asyncio.sleep(agent.MAP_SETTLE)
        for number, (level, title, check, needs_llm) in enumerate(CHECKLIST, 1):
            if (only and number not in only) or level > opts.max_level or (needs_llm and not opts.llm):
                results.append({"level": level, "check": title, "status": "pulado", "detail": ""})
                continue
            t = time.time()
            try:
                detail = await check(lyra)
                status = "ok"
            except Exception as e:  # each check reports, the list goes on
                status, detail = "FALHOU", f"{type(e).__name__}: {e}"
                if lyra.w.npc_wait:
                    lyra.client.close_npc()
                lyra.body.engine.stop()
            results.append({"level": level, "check": title, "status": status, "detail": str(detail)[:200],
                            "seconds": round(time.time() - t, 1)})
            print(f"[{status:6}] {number}. {title}: {str(detail)[:150]}", flush=True)
    finally:
        await lyra.stop()
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump({"when": time.strftime("%Y-%m-%d %H:%M"), "results": results}, f, ensure_ascii=False, indent=1)
    failed = [r for r in results if r["status"] == "FALHOU"]
    ran = [r for r in results if r["status"] != "pulado"]
    print(f"\n{len(ran) - len(failed)} de {len(ran)} itens executados passaram ({len(results) - len(ran)} pulados); "
          f"resultados em {RESULTS}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
