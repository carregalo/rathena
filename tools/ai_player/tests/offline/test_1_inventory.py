"""Offline test of roclient inventory parsing with packets laid out like the server's structs (dump_items.cpp)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import roclient  # noqa: E402

c = roclient.Client("x", "u", "p", "0000", "Lyra")
c.world.account_id = 2000002
sent = []
c._send = lambda pid, body, first=False: sent.append((pid, body))
w = c.world


def normal(index, item_id, kind, amount):
    return struct.pack("<HIBHI", index, item_id, kind, amount, 0).ljust(34, b"\0")


def equip(index, item_id, kind, slots, worn):
    return struct.pack("<HIBII", index, item_id, kind, slots, worn).ljust(68, b"\0")


def var(pid, body):
    return struct.pack("<HH", pid, len(body) + 4) + body


c._handle(0x0b08, var(0x0b08, b"\0"))
body = b"\0" + normal(2, 501, 0, 3) + normal(3, 909, 3, 5)
c._handle(0x0b09, var(0x0b09, body))
c._handle(0x0b39, var(0x0b39, b"\0" + equip(4, 1201, 5, 2, 2) + equip(5, 2301, 4, 16, 0)))
ok_list = (w.inventory[2].amount == 3 and w.inventory[3].item_id == 909 and w.inventory[4].worn == 2
           and w.inventory[5].slots == 16 and len(w.inventory) == 4)

pickup = bytearray(70)
struct.pack_into("<HHHI", pickup, 0, 0x0b41, 3, 2, 909)  # index 3 +2 Jellopy
struct.pack_into("<IBB", pickup, 28, 0, 3, 0)
c._handle(0x0b41, bytes(pickup))
ok_pickup = w.inventory[3].amount == 7

use = struct.pack("<HHIIHB", 0x01c8, 2, 501, 2000002, 2, 1)
c._handle(0x01c8, use)
ok_use = w.inventory[2].amount == 2

c.equip(5)
ok_send = sent[-1] == (0x0998, struct.pack("<HI", 5, 16))
c._handle(0x0999, struct.pack("<HHIHB", 0x0999, 5, 16, 0, 0))
ok_equip = w.inventory[5].worn == 16

c._handle(0x07fa, struct.pack("<HHHH", 0x07fa, 0, 3, 7))
ok_delete = 3 not in w.inventory

print("log:", [(what, item, n) for _, what, item, n in w.item_log])
checks = dict(list=ok_list, pickup=ok_pickup, use=ok_use, send=ok_send, equip=ok_equip, delete=ok_delete)
print("PASS" if all(checks.values()) else f"FAIL {checks}")
