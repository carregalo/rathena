"""Offline test: travel and visit over the real atlas (a fake server moves her and applies portals with the map
cells), NPC windows parsed from server-shaped packets, and answer_npc for every window kind."""
import asyncio
import os
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from body import Body  # noqa: E402
import config  # noqa: E402
from mind import Mind  # noqa: E402
import npc  # noqa: E402
import atlas  # noqa: E402
import roclient  # noqa: E402

config.TICK = 0.01
config.WALK_REPEAT = 0.02
WORLD = atlas.Atlas()
NAMES = {501: "Red Potion", 502: "Orange Potion", 909: "Jellopy"}


class FakeServer(roclient.Client):
    """A roclient.Client whose _send is a tiny server: walks follow the map cells, portals change maps,
    NPCs nearby show up as units."""

    def __init__(self, start_map, x, y):
        super().__init__("x", "u", "p", "0000", "Lyra")
        w = self.world
        w.account_id, w.map, w.x, w.y, w.hp, w.max_hp, w.zeny = 1000, start_map, x, y, 60, 60, 500
        self.sent = []
        self.maps_seen = [start_map]
        self.clicked = []
        self._spawn_npcs()

    def _spawn_npcs(self):
        w = self.world
        w.units = {}
        for i, n in enumerate(WORLD.npcs.get(w.map, [])):
            w.units[50000 + i] = roclient.Unit(50000 + i, "npc", n.name, n.x, n.y)

    def _send(self, pid, body, first=False):
        self.sent.append((pid, body))
        w = self.world
        if pid == roclient.CZ_REQUEST_MOVE:
            x, y = roclient.decode_pos(body)
            path = WORLD.path(w.map, (w.x, w.y), (x, y))
            if path is None or len(path) > 32:  # the server's path_search limit
                w.last_walk_result = "pending"
                return
            w.x, w.y, w.last_walk_result = x, y, "ok"
            for warp in WORLD.warps.get(w.map, []):
                if abs(w.x - warp.x) <= warp.sx and abs(w.y - warp.y) <= warp.sy:
                    w.map, w.x, w.y = warp.to_map, warp.to_x, warp.to_y
                    self.maps_seen.append(w.map)
                    self._spawn_npcs()
                    break
        elif pid == roclient.CZ_CONTACTNPC:
            self.clicked.append(struct.unpack_from("<I", body)[0])


async def run_routine(name, args, client, seconds):
    mind = Mind(os.path.join(tempfile.mkdtemp(), "m.json"))
    body = Body(client, mind, NAMES, WORLD)
    task = asyncio.create_task(body.run())
    err = body.engine.start(name, args)
    assert err is None, err
    done = None
    end = time.time() + seconds
    while time.time() < end and done is None:
        await asyncio.sleep(0.02)
        while not client.events.empty():
            kind, what = client.events.get_nowait()
            if kind in ("routine_done", "routine_error"):
                done = (kind, what)
    task.cancel()
    return done


async def main():
    checks = {}

    # travel prontera -> geffen, walking legs over the real cells and stepping on the real portals
    c = FakeServer("prontera", 156, 60)
    t = time.time()
    done = await run_routine("travel", '{"map": "geffen"}', c, 60)
    print("travel:", done, "maps:", " -> ".join(dict.fromkeys(c.maps_seen)), f"{time.time() - t:.1f}s")
    checks["travel reaches geffen"] = done and done[0] == "routine_done" and c.world.map == "geffen"

    # visit an NPC in another map: the Cleric of prt_church, from Prontera's south gate
    c = FakeServer("prontera", 156, 40)
    done = await run_routine("visit", '{"npc": "Cleric"}', c, 60)
    print("visit:", done, "maps:", " -> ".join(dict.fromkeys(c.maps_seen)))
    clicked = [c.world.units[g].name for g in c.clicked if g in c.world.units]
    checks["visit clicks the Cleric"] = c.world.map == "prt_church" and "Cleric" in clicked

    # NPC windows from server-shaped packets, answered with answer_npc
    c = FakeServer("prontera", 150, 80)
    c.world.units[9] = roclient.Unit(9, "npc", "Kafra Employee#1", 151, 81)
    body = Body(c, Mind(os.path.join(tempfile.mkdtemp(), "m.json")), NAMES, WORLD)
    menu = b"Save:Use Storage::Teleport\0"
    c._handle(0x00B4, struct.pack("<HHI", 0x00B4, 8 + 12, 9) + b"Hello there\0")
    c._handle(0x00B7, struct.pack("<HHI", 0x00B7, 8 + len(menu), 9) + menu)
    ev = c.events.get_nowait()
    checks["menu event with lines"] = ev == ("npc_wait", ("Kafra Employee#1", ["Hello there"]))
    checks["menu text shown"] = any("4) Teleport" in l for l in npc.describe_wait(c.world, NAMES))
    r = npc.answer_npc(c, body, "teleport")
    checks["menu by text keeps script numbering"] = c.sent[-1] == (roclient.CZ_CHOOSE_MENU, struct.pack("<IB", 9, 4))
    print("menu:", r)
    c._handle(0x0142, struct.pack("<HI", 0x0142, 9)); c.events.get_nowait()
    npc.answer_npc(c, body, "quero 3")
    checks["number"] = c.sent[-1] == (roclient.CZ_INPUT_NUMBER, struct.pack("<Ii", 9, 3))
    c._handle(0x00C4, struct.pack("<HI", 0x00C4, 9)); c.events.get_nowait()
    npc.answer_npc(c, body, "comprar")
    checks["deal buy"] = c.sent[-1] == (roclient.CZ_DEAL_TYPE, struct.pack("<IB", 9, 0))
    items = struct.pack("<IiiB4x2x", 501, 50, 50, 0) + struct.pack("<IiiB4x2x", 502, 200, 200, 0)
    c._handle(0x0B77, struct.pack("<HH", 0x0B77, 4 + len(items)) + items); c.events.get_nowait()
    checks["buy list parsed"] = c.world.npc_wait["items"] == [(501, 50), (502, 200)]
    r = npc.answer_npc(c, body, '[{"item": "Orange Potion", "amount": 3}]')
    checks["too expensive refused"] = "custaria 600" in r and c.world.npc_wait is not None
    r = npc.answer_npc(c, body, '[{"item": "Red Potion", "amount": 4}]')
    checks["buy sent"] = c.sent[-1] == (roclient.CZ_BUY, struct.pack("<HHI", 10, 4, 501))
    c._handle(0x00CA, struct.pack("<HB", 0x00CA, 0))
    checks["shop result"] = c.events.get_nowait() == ("shop_result", "compra: deu certo")
    c.world.inventory[5] = roclient.Item(5, 909, 7, 3)
    c._handle(0x00C4, struct.pack("<HI", 0x00C4, 9)); c.events.get_nowait()
    npc.answer_npc(c, body, "vender")
    sell = struct.pack("<Hii", 5, 3, 3)
    c._handle(0x00C7, struct.pack("<HH", 0x00C7, 4 + len(sell)) + sell); c.events.get_nowait()
    npc.answer_npc(c, body, '[{"item": "jellopy", "amount": 10}]')
    checks["sell clamps to what she has"] = c.sent[-1] == (roclient.CZ_SELL, struct.pack("<HHH", 8, 5, 7))
    # storage: start / list / end packets with inventory type 2
    c._handle(0x0B08, struct.pack("<HHB", 0x0B08, 6, 2) + b"\0")
    entry = struct.pack("<HIBHI", 1, 909, 3, 2, 0).ljust(34, b"\0")
    c._handle(0x0B09, struct.pack("<HHB", 0x0B09, 5 + 34, 2) + entry)
    c._handle(0x0B0B, struct.pack("<HBB", 0x0B0B, 2, 0)); c.events.get_nowait()
    checks["storage open"] = c.world.npc_wait["kind"] == "storage" and c.world.storage[1].amount == 2
    npc.answer_npc(c, body, '{"guardar": [{"item": "Jellopy", "amount": 2}], "retirar": [{"item": "Jellopy", "amount": 1}]}')
    checks["storage put+get"] = c.sent[-2] == (roclient.CZ_STORAGE_PUT, struct.pack("<Hi", 5, 2)) and \
        c.sent[-1] == (roclient.CZ_STORAGE_GET, struct.pack("<Hi", 1, 1))
    npc.answer_npc(c, body, "fechar")
    checks["storage close"] = c.sent[-1] == (roclient.CZ_STORAGE_CLOSE, b"") and c.world.npc_wait is None

    failed = [k for k, v in checks.items() if not v]
    print("\n".join(f"{'ok  ' if v else 'FAIL'} {k}" for k, v in checks.items()))
    print("PASS" if not failed else f"FAIL: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
