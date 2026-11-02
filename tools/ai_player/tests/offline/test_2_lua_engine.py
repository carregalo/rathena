"""Offline test of the Lua routines engine: base routines, a learned routine, reflexes, and the sandbox."""
import asyncio
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from body import Body  # noqa: E402
import config  # noqa: E402
import luaengine  # noqa: E402
from mind import Mind  # noqa: E402
import roclient  # noqa: E402

config.TICK = 0.03
config.OUTCOME_DELAY = 0.1
LEARNED = tempfile.mkdtemp()
luaengine.LEARNED_DIR = LEARNED  # do not write into the real lua/learned


class FakeClient:
    def __init__(self):
        self.world = roclient.World(name="Lyra", x=100, y=100, hp=60, max_hp=60, account_id=1000)
        self.events = asyncio.Queue()
        self.attacks, self.used, self.walks, self.picked, self.said = [], [], [], [], []

    def attack(self, gid):
        self.attacks.append(gid)

    def use_item(self, index):
        self.used.append(index)
        w = self.world
        w.hp = w.max_hp
        w.note_item("used", w.inventory[index].item_id, 1)

    def pick_up(self, gid):
        self.picked.append(gid)
        self.world.items.pop(gid, None)

    def say(self, text):
        self.said.append(text)
        return True

    def emote(self, name):
        pass

    def walk_to(self, x, y):
        self.walks.append((x, y))
        self.world.x, self.world.y = x, y
        self.world.last_walk_result = "ok"


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def main():
    c = FakeClient()
    w = c.world
    mind = Mind(os.path.join(tempfile.mkdtemp(), "mind.json"))
    body = Body(c, mind, {501: "Red Potion", 909: "Jellopy"})
    eng = body.engine
    task = asyncio.create_task(body.run())
    checks = {}

    # --- hunt (base routine): nearest Poring, chase then attack, loot, next one
    for gid, name, x, y in [(1, "Poring", 110, 100), (2, "Poring", 104, 101), (3, "Lunatic", 101, 100)]:
        w.units[gid] = roclient.Unit(gid, "monster", name, x, y)
    checks["start hunt"] = eng.start("hunt", '{"monster": "Poring", "limit": 2}') is None
    await asyncio.sleep(0.25)
    checks["hunt: nearest, adjacent"] = c.attacks[:1] == [2] and luaengine.cells(104, 101, w.x, w.y) <= 1
    w.hits.append((time.time(), 1000, 2, 12))
    w.base_exp = 5
    w.units.pop(2); w.killed.append(2); w.last_seen["Poring"] = (104, 101, time.time())
    await asyncio.sleep(0.06)
    w.items[77] = (909, 1, 104, 101)
    await asyncio.sleep(0.3)
    checks["hunt: loot + learned"] = 77 in c.picked and mind.world["monsters"]["Poring"].get("drops") == ["Jellopy"]
    checks["hunt: waits for drops"] = c.attacks[-1] == 2
    await asyncio.sleep(1.4)
    checks["hunt: next target"] = c.attacks[-1] == 1
    w.units.pop(1); w.killed.append(1)
    await asyncio.sleep(1.8)
    events = drain(c.events)
    checks["hunt: Done after limit"] = ("routine_done", "hunt: derrotei 2 Poring") in events and eng.active is None

    # --- reflex: a monster hits her while no routine runs -> she fights back
    w.hits.append((time.time(), 3, 1000, 4))
    await asyncio.sleep(0.15)
    checks["reflex defends"] = c.attacks[-1] == 3 and ("attacked", "Lunatic") in drain(c.events)
    w.units.pop(3); w.killed.append(3)
    await asyncio.sleep(0.1)

    # --- follow (base routine)
    w.units[50] = roclient.Unit(50, "player", "teste", 108, 104)
    eng.start("follow", '{"player": "teste"}')
    await asyncio.sleep(0.2)
    checks["follow: walks near"] = luaengine.cells(108, 104, w.x, w.y) <= 2
    w.units.pop(50); w.last_seen["teste"] = (120, 104, time.time())
    await asyncio.sleep(0.2)
    checks["follow: goes to last seen"] = luaengine.cells(120, 104, w.x, w.y) <= 2

    # --- explore (base routine): keeps walking to new places
    eng.start("explore", '{"steps": 3}')
    await asyncio.sleep(0.6)
    checks["explore: 3 legs then Done"] = any(k == "routine_done" and "explorei 3" in v for k, v in drain(c.events))

    # --- a routine written by the model: collect Jellopy, using its own state and Say/Done
    code = '''-- Junta Jellopy do chao ate ter N na mochila e avisa.
-- args: want = quantos
function Tick(args)
  local have = 0
  for _, it in ipairs(GetInventory()) do if it.name == "Jellopy" then have = have + it.amount end end
  if have >= args.want then Say("Juntei " .. have .. " Jellopy!") Done("tenho " .. have) return end
  for _, item in ipairs(GetGroundItems()) do
    if item.name == "Jellopy" then PickUp(item.id) return end
  end
end
'''
    checks["write learned"] = eng.write("juntar_jellopy", "", code) is None and \
        os.path.exists(os.path.join(LEARNED, "juntar_jellopy.lua"))
    w.items[90] = (909, 1, w.x + 5, w.y)
    eng.start("juntar_jellopy", '{"want": 1}')
    await asyncio.sleep(0.3)
    w.inventory[3] = roclient.Item(3, 909, 1, 3)
    await asyncio.sleep(0.15)
    checks["learned runs"] = 90 in c.picked and c.said[-1:] == ["Juntei 1 Jellopy!"] and eng.active is None
    checks["listed"] = any(l.startswith("- juntar_jellopy (sua): Junta Jellopy") for l in eng.describe())

    # --- a monster respawns with the id it had when it died: it must not be counted as killed again
    eng.stop()
    kills = body.kills
    w.units[2] = roclient.Unit(2, "monster", "Poring", w.x + 1, w.y)  # id 2 is still in w.killed
    body.target, body.defending = 2, True
    await asyncio.sleep(0.15)
    checks["respawned id not recounted"] = body.kills == kills
    w.units.pop(2)
    body.target, body.defending = None, False

    # --- the sandbox
    bad = {
        "os": 'os.execute("calc") function Tick() end',
        "io": 'io.open("x","w") function Tick() end',
        "load": 'load("return 1") function Tick() end',
        "require": 'require("os") function Tick() end',
        "python attr": 'local f = GetTick.__globals__ function Tick() end',
        "debug": 'debug.sethook() function Tick() end',
        "no Tick": 'local x = 1',
        "syntax": 'function Tick( end',
    }
    for label, src in bad.items():
        checks[f"blocked: {label}"] = eng.write("ruim", "teste", src) is not None
    checks["base is protected"] = eng.write("hunt", "x", "function Tick() end") is not None
    eng.write("laco", "laco sem fim", "function Tick() while true do end end")
    eng.start("laco", "{}")
    await asyncio.sleep(0.2)
    checks["infinite loop stopped"] = eng.active is None and any(
        k == "routine_error" and "limite de instrucoes" in v for k, v in drain(c.events))
    eng.write("explode", "erro", 'function Tick() error("ops") end')
    eng.start("explode", "{}")
    await asyncio.sleep(0.1)
    checks["runtime error reported"] = any(k == "routine_error" and "ops" in v for k, v in drain(c.events))
    checks["bad args rejected"] = eng.start("hunt", "{nao e json") is not None

    task.cancel()
    shutil.rmtree(LEARNED, ignore_errors=True)
    failed = [k for k, v in checks.items() if not v]
    print("\n".join(f"{'ok  ' if v else 'FAIL'} {k}" for k, v in checks.items()))
    print("PASS" if not failed else f"FAIL: {failed}")


asyncio.run(main())
