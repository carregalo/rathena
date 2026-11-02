"""Headless Ragnarok client for this rAthena build (PACKETVER from packet_table.json).

Logs in like the game client (login -> pincode -> character -> map), keeps the world state that the
server sends (own position and HP, units in sight, chat) and offers a few actions: walk, chat, emote.
Packet lengths and client->server packet ids come from packet_table.json, which
protocol/make_table.py generates from the server's own headers.
"""
import asyncio
import json
import logging
import math
import os
import socket
import struct
import time
from dataclasses import dataclass, field

log = logging.getLogger("roclient")

TABLE = json.load(open(os.path.join(os.path.dirname(__file__), "packet_table.json")))
CHAR_LEN = {int(k, 16): v for k, v in TABLE["char"].items()}
ZONE_LEN = {int(k, 16): v for k, v in TABLE["zone"].items()}

# Unit object types (clif_bl_type in src/map/clif.cpp)
UNIT_TYPES = {0x0: "player", 0x1: "player", 0x2: "item", 0x5: "monster", 0x6: "npc", 0x7: "pet",
              0x8: "homunculus", 0x9: "mercenary", 0xA: "elemental", 0xC: "npc", 0xD: "monster", 0xE: "monster"}

WARP_CLASS = 45  # JT_WARPNPC (enum e_job_types in src/map/npc.hpp): portals look like NPCs with this class

# enum emotion_type in src/map/clif.hpp
EMOTES = {"surprise": 0, "question": 1, "delight": 2, "throb": 3, "sweat": 4, "aha": 5, "fret": 6,
          "anger": 7, "money": 8, "think": 9, "thanks": 15, "sorry": 17, "smile": 18}

# Client->map ids used here; all are registered for this build (see TABLE["handlers"]).
CZ_ENTER, CZ_NOTIFY_ACTORINIT, CZ_REQUEST_TIME, CZ_REQUEST_MOVE = 0x0436, 0x007d, 0x0360, 0x035f
CZ_REQUEST_CHAT, CZ_REQ_EMOTION, CZ_RESTART = 0x00f3, 0x00bf, 0x00b2
CZ_REQUEST_ACT = 0x0437  # <target id>.L <action>.B; action 7 = attack continuously, but only from within range:
                         # the server never walks a player to the target, it answers 0x0139 (unit_attack_timer_sub)
DEFAULT_SPEED = 150  # ms per cell (status SP_SPEED); a diagonal step takes speed * 14 / 10 (unit.cpp)
CZ_ITEM_PICKUP = 0x0362  # <ground item id>.L; the server only accepts it within 2 cells
CZ_CONTACTNPC = 0x0090   # <npc id>.L <type>.B; the server requires the bot to stand close to the NPC
CZ_REQ_NEXT_SCRIPT, CZ_CHOOSE_MENU, CZ_CLOSE_DIALOG = 0x00b9, 0x00b8, 0x0146
CZ_USE_ITEM = 0x0439          # <index>.W <account id>.L
CZ_REQ_WEAR_EQUIP = 0x0998    # <index>.W <equip location>.L
CZ_REQ_TAKEOFF_EQUIP = 0x00ab  # <index>.W
# NPC inputs and shops; layouts printed by protocol/dump_npc.cpp
CZ_INPUT_NUMBER = 0x0143      # <npc id>.L <value>.L
CZ_INPUT_TEXT = 0x01d5        # <length>.W <npc id>.L <text>.?B
CZ_DEAL_TYPE = 0x00c5         # <npc id>.L <0 = buy, 1 = sell>.B
CZ_BUY = 0x00c8               # <length>.W { <amount>.W <item id>.L }*
CZ_SELL = 0x00c9              # <length>.W { <index>.W <amount>.W }*
CZ_STORAGE_PUT, CZ_STORAGE_GET, CZ_STORAGE_CLOSE = 0x0364, 0x0365, 0x0193  # <index>.W <amount>.L
ZC_BUY_LIST = 0x0b77          # header 4, entries of 19: item id.L@0 price.L@4 discount price.L@8 type.B@12
ZC_SELL_LIST = 0x00c7         # header 4, entries of 10: index.W@0 price.L@2 overcharge.L@6
ZC_STORAGE_ADD = 0x0b44       # index.W@2 amount.L@4 item id.L@8
INV_STORAGE = 2               # e_inventory_type INVTYPE_STORAGE (src/map/clif.cpp)
SHOP_RESULTS = {0: "deu certo", 1: "zeny insuficiente", 2: "peso demais para carregar", 3: "mochila cheia"}

# Inventory packets of this PACKETVER; offsets printed by protocol/dump_items.cpp (offsetof on the server's structs).
ZC_INVENTORY_START, ZC_INVENTORY_END = 0x0b08, 0x0b0b
ZC_INVENTORY_NORMAL, ZC_INVENTORY_EQUIP = 0x0b09, 0x0b39  # list after a 5-byte header (type, length, inventory type)
NORMAL_ITEM, NORMAL_ITEM_SIZE = "<HIBHI", 34   # index, item id, type, amount, equippable locations
EQUIP_ITEM, EQUIP_ITEM_SIZE = "<HIBII", 68     # index, item id, type, equippable locations, worn locations
ZC_ITEM_PICKUP_ACK = 0x0b41    # index@2 amount@4 item id@6 locations@28 type@32 result@33
ZC_USE_ITEM_ACK = 0x01c8       # index@2 item id@4 account id@8 amount left@12 ok@14
ZC_WEAR_EQUIP_ACK = 0x0999     # index@2 locations@4 view@8 result@10 (0 = ok in this version)
ZC_TAKEOFF_EQUIP_ACK = 0x099a  # index@2 locations@4 result@8 (0 = ok in this version)
ZC_DELETE_ITEM, ZC_ITEM_THROW_ACK = 0x07fa, 0x00af
# Client item types (itemtype() in src/map/itemdb.hpp)
ITEM_TYPES = {0: "cura", 2: "usavel", 3: "material", 4: "armadura", 5: "arma", 6: "carta", 7: "ovo de bichinho",
              8: "acessorio de bichinho", 10: "municao", 11: "usavel", 12: "equipamento sombrio", 18: "pacote"}

# Unit appear packets; the three share a prefix and end with name[24].
UNIT_FIXED = "<hhBIIhhhihHIIH"  # type..accessory (common prefix)
IDLE_REST = "<HHhhhHIhhiBB3sBBBhhiiBH24s"
SPAWN_REST = "<HHhhhHIhhiBB3sBBhhiiBh24s"
WALK_REST = "<IHHhhhHIhhiBB6sBBhhiiBH24s"


def check_handler(name, pid):
    ids = {h["id"] for h in TABLE["handlers"].get(name, [])}
    if f"0x{pid:04x}" not in ids:
        raise RuntimeError(f"0x{pid:04x} is not registered for {name} in this build; regenerate the table")


for _name, _pid in (("WantToConnection", CZ_ENTER), ("LoadEndAck", CZ_NOTIFY_ACTORINIT), ("TickSend", CZ_REQUEST_TIME),
                    ("WalkToXY", CZ_REQUEST_MOVE), ("GlobalMessage", CZ_REQUEST_CHAT), ("Emotion", CZ_REQ_EMOTION),
                    ("Restart", CZ_RESTART), ("NpcNextClicked", CZ_REQ_NEXT_SCRIPT), ("ActionRequest", CZ_REQUEST_ACT), ("TakeItem", CZ_ITEM_PICKUP), ("NpcClicked", CZ_CONTACTNPC),
                    ("NpcSelectMenu", CZ_CHOOSE_MENU), ("NpcCloseClicked", CZ_CLOSE_DIALOG), ("UseItem", CZ_USE_ITEM),
                    ("EquipItem", CZ_REQ_WEAR_EQUIP), ("UnequipItem", CZ_REQ_TAKEOFF_EQUIP),
                    ("NpcAmountInput", CZ_INPUT_NUMBER), ("NpcStringInput", CZ_INPUT_TEXT),
                    ("NpcBuySellSelected", CZ_DEAL_TYPE), ("NpcBuyListSend", CZ_BUY), ("NpcSellListSend", CZ_SELL),
                    ("MoveToKafra", CZ_STORAGE_PUT), ("MoveFromKafra", CZ_STORAGE_GET), ("CloseKafra", CZ_STORAGE_CLOSE)):
    check_handler(_name, _pid)


def cstr(raw):
    return raw.split(b"\0", 1)[0].decode("latin1")


def strip_colors(text):
    """Removes ^RRGGBB color codes used in NPC dialogs."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "^" and i + 7 <= len(text) and all(c in "0123456789abcdefABCDEF" for c in text[i + 1:i + 7]):
            i += 7
            continue
        out.append(text[i])
        i += 1
    return "".join(out).strip()


def decode_pos(b):
    x = (b[0] << 2) | (b[1] >> 6)
    y = ((b[1] & 0x3F) << 4) | (b[2] >> 4)
    return x, y


def decode_move(b):
    """MoveData[6] -> (x0, y0, x1, y1)."""
    x0 = (b[0] << 2) | (b[1] >> 6)
    y0 = ((b[1] & 0x3F) << 4) | (b[2] >> 4)
    x1 = ((b[2] & 0x0F) << 6) | (b[3] >> 2)
    y1 = ((b[3] & 0x03) << 8) | b[4]
    return x0, y0, x1, y1


def encode_pos(x, y, direction=0):
    return bytes([(x >> 2) & 0xFF, ((x & 0x03) << 6) | ((y >> 4) & 0x3F), ((y & 0x0F) << 4) | (direction & 0x0F)])


def pincode_encrypt(seed, pin):
    """Inverse of char_pincode_decrypt (src/char/char.cpp): send the digit that maps to each pin digit."""
    tab = list(range(10))
    for i in range(1, 10):
        seed = (0x881234 + seed * 0x3498) & 0xFFFFFFFF
        pos = seed % (i + 1)
        if i != pos:
            tab[i], tab[pos] = tab[pos], tab[i]
    return "".join(str(tab.index(int(d))) for d in pin)


class Stream:
    """Framed packet reader using a length table (-1 = variable length in bytes 2-3)."""

    def __init__(self, reader, writer, lengths, label):
        self.reader, self.writer, self.lengths, self.label = reader, writer, lengths, label
        self.buf = b""

    async def raw(self, n):
        while len(self.buf) < n:
            chunk = await self.reader.read(65536)
            if not chunk:
                raise ConnectionError(f"{self.label}: connection closed")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    async def packet(self):
        head = await self.raw(2)
        pid = struct.unpack("<H", head)[0]
        length = self.lengths.get(pid)
        if length is None or length == 0:
            raise ConnectionError(f"{self.label}: unknown packet 0x{pid:04x}, cannot keep framing")
        if length == -1:
            size = struct.unpack("<H", await self.raw(2))[0]
            return pid, head + struct.pack("<H", size) + await self.raw(size - 4)
        return pid, head + await self.raw(length - 2)

    def send(self, data):
        self.writer.write(data)


@dataclass
class Unit:
    gid: int
    kind: str
    name: str
    x: int
    y: int
    job: int = 0


@dataclass
class Item:
    index: int
    item_id: int
    amount: int
    type: int
    slots: int = 0      # equip locations it fits (0 = not equipment)
    worn: int = 0       # locations it is worn on now


@dataclass
class World:
    account_id: int = 0
    char_id: int = 0
    name: str = ""
    map: str = ""
    x: int = 0
    y: int = 0
    hp: int = 0
    max_hp: int = 0
    job: int = 0
    base_level: int = 0
    job_level: int = 0
    base_exp: int = 0
    next_base_exp: int = 0
    job_exp: int = 0
    next_job_exp: int = 0
    zeny: int = 0
    status_points: int = 0
    skill_points: int = 0
    dead: bool = False
    units: dict = field(default_factory=dict)
    last_seen: dict = field(default_factory=dict)  # name -> (x, y, time) of units that left the view
    items: dict = field(default_factory=dict)  # ground item id -> (item_id, amount, x, y)
    inventory: dict = field(default_factory=dict)  # inventory index -> Item
    item_log: list = field(default_factory=list)  # (time, what, item id, amount): gained, used, lost, equipped, ...
    hits: list = field(default_factory=list)  # (time, attacker gid, target gid, damage) seen in range
    sp: int = 0
    max_sp: int = 0
    last_dialog_at: float = 0.0   # last NPC dialog text or menu
    own_chat: str = ""            # last public message of ours the server echoed
    npc_wait: dict = None         # what an open NPC window expects: {"kind", "npc", "name", ...}
    storage: dict = field(default_factory=dict)  # storage index -> Item while the storage is open
    storage_open: bool = False
    last_warp: tuple = None       # (map, x, y) of the portal taken on the last map change, if any

    def note_item(self, what, item_id, amount=0):
        self.item_log = (self.item_log + [(time.time(), what, item_id, amount)])[-20:]
    killed: list = field(default_factory=list)  # gids of units that died in sight
    dialog: list = field(default_factory=list)  # lines of the NPC dialog in progress
    chat: list = field(default_factory=list)  # (time, speaker, text, kind)
    last_walk_result: str = ""
    walk_until: float = 0.0       # estimated arrival of our own walk (wd.x/y already hold the destination)
    speed: int = 0                # ms per cell, from the status packets (0 = not received yet)
    walk_from: tuple = None       # start cell of the last accepted walk (where she was when the server took it)
    walk_from_at: float = 0.0
    too_far_at: float = 0.0       # last 0x0139: the server refused an attack because the target is out of range

    def nearby(self, limit=15):
        items = sorted(self.units.values(), key=lambda u: math.hypot(u.x - self.x, u.y - self.y))
        return items[:limit]


class Client:
    def __init__(self, host, user, password, pincode, char_name, sex="F"):
        self.host, self.user, self.password, self.pincode = host, user, password, pincode
        self.char_name, self.sex = char_name, 1 if sex == "M" else 0
        self.world = World(name=char_name)
        self.zone = None
        self.events = asyncio.Queue()  # chat lines addressed to the bot and other notable events
        self._crypt_key = 0
        self._last_chat_sent = 0.0
        self._deal_npc = 0

    # ---------------------------------------------------------------- login / char

    async def connect(self):
        auth = await self._login()
        zone = await self._select_character(auth)
        await self._enter_map(auth, zone)

    async def _login(self):
        r, w = await asyncio.open_connection(self.host, 6900)
        s = Stream(r, w, CHAR_LEN, "login")
        s.send(struct.pack("<HI24s24sB", 0x0064, 20211103, self.user.encode(), self.password.encode(), 0))
        pid, p = await s.packet()
        w.close()
        if pid != 0x0AC4:
            raise ConnectionError(f"login refused: packet 0x{pid:04x} {p[2:8].hex()}")
        login_id1, aid, login_id2 = struct.unpack_from("<III", p, 4)
        sex = p[46]
        srv = p[64:64 + 160]
        ip = socket.inet_ntoa(srv[0:4])
        port = struct.unpack_from("<H", srv, 4)[0]
        log.info("logged in as %s (aid %d); char server %s:%d", self.user, aid, ip, port)
        self.world.account_id = aid
        return {"aid": aid, "login_id1": login_id1, "login_id2": login_id2, "sex": sex, "char": (ip, port)}

    async def _select_character(self, auth):
        # The servers announce their LAN address; a local bot always uses the configured host.
        _, port = auth["char"]
        r, w = await asyncio.open_connection(self.host, port)
        s = Stream(r, w, CHAR_LEN, "char")
        s.send(struct.pack("<HIIIHB", 0x0065, auth["aid"], auth["login_id1"], auth["login_id2"], 0, auth["sex"]))
        await s.raw(4)  # account id echo, sent without a packet header
        chars = {}
        pin_ok = False
        pin_seed = None  # seed of the most recent pincode request not answered yet
        while True:
            try:
                # Every pincode request (sent by the server on its own and again for each 0x08c5) rolls a
                # new seed, so answer only once the server has gone quiet, with the latest seed.
                # After the pincode, the character pages arrive in one burst: quiet means "list complete".
                wait = 0.5 if pin_seed is not None else (1.0 if pin_ok else 10)
                pid, p = await asyncio.wait_for(s.packet(), wait)
            except asyncio.TimeoutError:
                if pin_ok:
                    break
                if pin_seed is None:
                    s.send(struct.pack("<HI", 0x08C5, auth["aid"]))  # no request came: ask for it
                else:
                    pin = pincode_encrypt(pin_seed, self.pincode).encode()
                    s.send(struct.pack("<HI4s", 0x08B8, auth["aid"], pin))
                    pin_seed = None
                continue
            log.debug("char <- 0x%04x %s", pid, p[:24].hex())
            if pid == 0x006C:
                raise ConnectionError(f"char server refused: error {p[2]}")
            if pid == 0x08B9:
                seed, _, result = struct.unpack_from("<IIH", p, 2)
                if result == 1:  # ask
                    pin_seed = seed
                elif result in (0, 7):  # passed
                    pin_ok = True
                    s.send(struct.pack("<H", 0x09A1))  # request character pages
                else:
                    raise ConnectionError(f"pincode state {result} not handled (set the account pincode first)")
            elif pid in (0x0B72, 0x006B):
                start = 4 if pid == 0x0B72 else 27
                for off in range(start, len(p) - 174, 175):  # CHARACTER_INFO, 175 bytes
                    name = cstr(p[off + 108:off + 132])
                    chars[name] = {"slot": p[off + 138], "cid": struct.unpack_from("<I", p, off)[0],
                                   "job_level": struct.unpack_from("<i", p, off + 24)[0],
                                   "job": struct.unpack_from("<h", p, off + 84)[0],
                                   "base_level": struct.unpack_from("<h", p, off + 92)[0]}
                if pid == 0x0B72 and pin_ok and len(p) == 4:
                    break  # an empty page ends the list
        if self.char_name not in chars:
            slot = next(i for i in range(15) if i not in {c["slot"] for c in chars.values()})
            s.send(struct.pack("<H24sBHHIB", 0x0A39, self.char_name.encode(), slot, 1, 1, 0, self.sex))
            while True:
                pid, p = await s.packet()
                if pid == 0x0B6F:
                    log.info("created character %s in slot %d", self.char_name, slot)
                    chars[self.char_name] = {"slot": slot}
                    break
                if pid == 0x006E:
                    raise ConnectionError(f"character creation refused: error {p[2]}")
        me = chars[self.char_name]
        self.world.job = me.get("job", 0)
        self.world.base_level = me.get("base_level", 1)
        self.world.job_level = me.get("job_level", 1)
        s.send(struct.pack("<HB", 0x0066, me["slot"]))
        while True:
            pid, p = await s.packet()
            if pid == 0x0AC5:
                cid = struct.unpack_from("<I", p, 2)[0]
                mapname = cstr(p[6:22])
                mip = socket.inet_ntoa(p[22:26])
                mport = struct.unpack_from("<H", p, 26)[0]
                w.close()
                self.world.char_id = cid
                self.world.map = mapname.replace(".gat", "")
                log.info("character %s (cid %d) goes to %s on %s:%d", self.char_name, cid, mapname, mip, mport)
                return {"cid": cid, "ip": mip, "port": mport}
            if pid == 0x006C:
                raise ConnectionError(f"character selection refused: error {p[2]}")

    # ---------------------------------------------------------------- map

    async def _enter_map(self, auth, zone):
        r, w = await asyncio.open_connection(self.host, zone["port"])
        self.zone = Stream(r, w, ZONE_LEN, "zone")
        self._crypt_key = 0
        tick = int(time.monotonic() * 1000) & 0xFFFFFFFF
        body = struct.pack("<IIII4xB", auth["aid"], zone["cid"], auth["login_id1"], tick, auth["sex"])
        self._send(CZ_ENTER, body, first=True)
        while True:
            pid, p = await self.zone.packet()
            if pid == 0x02EB:
                self.world.x, self.world.y = decode_pos(p[6:9])
                break
            if pid in (0x0074, 0x006A):
                raise ConnectionError(f"map server refused entry: error {p[2]}")
        self._send(CZ_NOTIFY_ACTORINIT, b"")
        log.info("entered map at %d,%d", self.world.x, self.world.y)

    def _send(self, pid, body, first=False):
        """Applies the packet-id obfuscation of clif_parse() (a no-op when the server keys are 0)."""
        keys = TABLE.get("obfuscation_keys", [0, 0, 0])
        k0, k1, k2 = keys
        if first:
            key = ((k0 * k1) + k2) & 0xFFFFFFFF
            self._crypt_key = (((((k0 * k1) + k2) & 0xFFFFFFFF) * k1) + k2) & 0xFFFFFFFF
        else:
            key = self._crypt_key
            self._crypt_key = ((self._crypt_key * k1) + k2) & 0xFFFFFFFF
        wire_id = pid ^ ((key >> 16) & 0x7FFF)
        self.zone.send(struct.pack("<H", wire_id) + body)

    def close(self):
        if getattr(self, "zone", None):
            self.zone.writer.close()

    async def run(self):
        """Reads map packets forever and keeps the world state current."""
        keepalive = asyncio.create_task(self._keepalive())
        try:
            while True:
                pid, p = await self.zone.packet()
                log.debug("zone <- 0x%04x len %d %s", pid, len(p), p[:16].hex())
                self._handle(pid, p)
        finally:
            keepalive.cancel()

    async def _keepalive(self):
        while True:
            await asyncio.sleep(10)
            self._send(CZ_REQUEST_TIME, struct.pack("<I", int(time.monotonic() * 1000) & 0xFFFFFFFF))

    def _handle(self, pid, p):
        wd = self.world
        if pid in (0x09FF, 0x09FE, 0x09FD):
            fixed = struct.calcsize(UNIT_FIXED)
            (_, _, objtype, aid, gid, _, _, _, _, job, *_rest) = struct.unpack_from(UNIT_FIXED, p, 0)
            rest_fmt = {0x09FF: IDLE_REST, 0x09FE: SPAWN_REST, 0x09FD: WALK_REST}[pid]
            rest = struct.unpack_from(rest_fmt, p, fixed)
            name = cstr(rest[-1])
            if pid == 0x09FD:
                _, _, x, y = decode_move(rest[13])  # MoveData
            else:
                x, y = decode_pos(rest[12])  # PosDir
            if aid != wd.account_id:
                kind = UNIT_TYPES.get(objtype, f"type{objtype}")
                if kind == "npc" and job == WARP_CLASS:
                    kind = "portal"
                wd.units[aid] = Unit(aid, kind, name, x, y, job)
                wd.last_seen.pop(name, None)
        elif pid == 0x0086:  # another unit moves
            gid = struct.unpack_from("<I", p, 2)[0]
            if gid in wd.units:
                _, _, wd.units[gid].x, wd.units[gid].y = decode_move(p[6:12])
        elif pid == 0x0088:  # unit stopped
            gid, x, y = struct.unpack_from("<IHH", p, 2)
            if gid == wd.account_id:
                wd.x, wd.y, wd.walk_until = x, y, 0.0
            elif gid in wd.units:
                wd.units[gid].x, wd.units[gid].y = x, y
        elif pid == 0x0087:  # own movement accepted
            x0, y0, wd.x, wd.y = decode_move(p[6:12])
            wd.walk_from, wd.walk_from_at = (x0, y0), time.time()  # the cell she really stood on
            dx, dy = abs(wd.x - x0), abs(wd.y - y0)
            diagonal, straight = min(dx, dy), abs(dx - dy)  # the shortest walk; detours only make it longer
            wd.walk_until = time.time() + (wd.speed or DEFAULT_SPEED) * (straight + diagonal * 1.4) / 1000
            wd.last_walk_result = "ok"
        elif pid == 0x0139:  # attack target too far: a real client walks closer and retries
            wd.too_far_at = time.time()
        elif pid in (0x08C8, 0x01DE):  # someone hits someone (normal attack / skill)
            src, target = struct.unpack_from("<II", p, 2 if pid == 0x08C8 else 4)
            damage = struct.unpack_from("<i", p, 22 if pid == 0x08C8 else 24)[0]
            wd.hits = (wd.hits + [(time.time(), src, target, damage)])[-100:]
        elif pid == 0x0080:  # unit vanished
            gid, kind = struct.unpack_from("<IB", p, 2)
            if gid == wd.account_id and kind == 1:
                wd.dead = True
                self.events.put_nowait(("died", ""))
            gone = wd.units.pop(gid, None)
            if gone is not None:
                wd.last_seen[gone.name] = (gone.x, gone.y, time.time())
                if kind == 1:
                    wd.killed = (wd.killed + [gid])[-50:]
        elif pid == 0x009D:  # ground item in sight
            gid, item_id, _, x, y, amount = struct.unpack_from("<IIBHHH", p, 2)
            wd.items[gid] = (item_id, amount, x, y)
        elif pid == 0x0ADD:  # item dropped in sight
            gid, item_id, _, _, x, y, _, _, amount = struct.unpack_from("<IIHBhhBBh", p, 2)
            wd.items[gid] = (item_id, amount, x, y)
        elif pid == 0x00A1:  # ground item gone
            wd.items.pop(struct.unpack_from("<I", p, 2)[0], None)
        elif pid == ZC_INVENTORY_START:
            if p[4] == 0:  # inventory type: 0 = inventory, 1 = cart, 2 = storage
                wd.inventory.clear()
            elif p[4] == INV_STORAGE:
                wd.storage.clear()
        elif pid in (ZC_INVENTORY_NORMAL, ZC_INVENTORY_EQUIP) and p[4] in (0, INV_STORAGE):
            normal = pid == ZC_INVENTORY_NORMAL
            target = wd.inventory if p[4] == 0 else wd.storage
            fmt, size = (NORMAL_ITEM, NORMAL_ITEM_SIZE) if normal else (EQUIP_ITEM, EQUIP_ITEM_SIZE)
            for off in range(5, len(p) - size + 1, size):
                if normal:
                    index, item_id, kind, amount, _ = struct.unpack_from(fmt, p, off)
                    target[index] = Item(index, item_id, amount, kind)
                else:
                    index, item_id, kind, slots, worn = struct.unpack_from(fmt, p, off)
                    target[index] = Item(index, item_id, 1, kind, slots, worn)
        elif pid == ZC_INVENTORY_END and p[2] == INV_STORAGE:
            wd.storage_open = True
            wd.npc_wait = {"kind": "storage", "npc": 0, "name": "Kafra", "since": time.time()}
            self.events.put_nowait(("npc_wait", ("Kafra", [])))
        elif pid == ZC_STORAGE_ADD:
            index, amount, item_id = struct.unpack_from("<HiI", p, 2)
            have = wd.storage.get(index)
            if have:
                have.amount += amount
            else:
                wd.storage[index] = Item(index, item_id, amount, p[12])
        elif pid == 0x00F6:  # item taken out of the storage
            index, amount = struct.unpack_from("<HI", p, 2)
            have = wd.storage.get(index)
            if have:
                have.amount -= amount
                if have.amount <= 0:
                    del wd.storage[index]
        elif pid == 0x00F8:  # storage closed
            wd.storage_open = False
            if wd.npc_wait and wd.npc_wait["kind"] == "storage":
                wd.npc_wait = None
        elif pid == 0x00C4:  # shop: buy or sell?
            self._wait("deal", struct.unpack_from("<I", p, 2)[0])
        elif pid == ZC_BUY_LIST:
            items = [struct.unpack_from("<IiiB", p, off) for off in range(4, len(p) - 18, 19)]
            self._wait("buy", self._deal_npc, items=[(i, discount) for i, _, discount, _ in items])
        elif pid == ZC_SELL_LIST:
            items = [struct.unpack_from("<Hii", p, off) for off in range(4, len(p) - 9, 10)]
            self._wait("sell", self._deal_npc, items=[(index, over) for index, _, over in items])
        elif pid in (0x00CA, 0x00CB):  # buy / sell result
            what = "compra" if pid == 0x00CA else "venda"
            wd.npc_wait = None
            self.events.put_nowait(("shop_result", f"{what}: {SHOP_RESULTS.get(p[2], 'falhou')}"))
        elif pid == 0x0142:  # NPC asks for a number
            self._wait("number", struct.unpack_from("<I", p, 2)[0])
        elif pid == 0x01D4:  # NPC asks for a text
            self._wait("text", struct.unpack_from("<I", p, 2)[0])
        elif pid == ZC_ITEM_PICKUP_ACK:
            index, amount, item_id = struct.unpack_from("<HHI", p, 2)
            slots, kind, result = struct.unpack_from("<IBB", p, 28)
            if result == 0:
                have = wd.inventory.get(index)
                if have and have.item_id == item_id:
                    have.amount += amount
                else:
                    wd.inventory[index] = Item(index, item_id, amount, kind, slots)
                wd.note_item("gained", item_id, amount)
        elif pid in (ZC_DELETE_ITEM, ZC_ITEM_THROW_ACK):
            index, amount = struct.unpack_from("<HH", p, 4 if pid == ZC_DELETE_ITEM else 2)
            have = wd.inventory.get(index)
            if have:
                have.amount -= amount
                wd.note_item("lost", have.item_id, amount)
                if have.amount <= 0:
                    del wd.inventory[index]
        elif pid == ZC_USE_ITEM_ACK:
            index, item_id, aid, left, ok = struct.unpack_from("<HIIHB", p, 2)
            if aid == wd.account_id and ok:
                wd.note_item("used", item_id, 1)
                if left:
                    wd.inventory[index].amount = left
                else:
                    wd.inventory.pop(index, None)
        elif pid in (ZC_WEAR_EQUIP_ACK, ZC_TAKEOFF_EQUIP_ACK):
            index, where = struct.unpack_from("<HI", p, 2)
            failed = p[10 if pid == ZC_WEAR_EQUIP_ACK else 8]
            have = wd.inventory.get(index)
            if have:
                wearing = pid == ZC_WEAR_EQUIP_ACK
                if not failed:
                    have.worn = where if wearing else 0
                wd.note_item(("equipped" if wearing else "unequipped") if not failed else "equip_failed", have.item_id)
        elif pid == 0x0091:  # map change on the same server
            portals = [u for u in wd.units.values() if u.kind == "portal" and max(abs(u.x - wd.x), abs(u.y - wd.y)) <= 3]
            portal = min(portals, key=lambda u: max(abs(u.x - wd.x), abs(u.y - wd.y)), default=None)
            wd.last_warp = (wd.map, portal.x, portal.y) if portal else None
            wd.map = cstr(p[2:18]).replace(".gat", "")
            wd.x, wd.y = struct.unpack_from("<HH", p, 18)
            wd.units.clear()
            wd.items.clear()
            self._send(CZ_NOTIFY_ACTORINIT, b"")
            self.events.put_nowait(("map", wd.map))
        elif pid == 0x008D:  # someone talks nearby: "Name : text"
            gid = struct.unpack_from("<I", p, 4)[0]
            text = cstr(p[8:])
            speaker, _, msg = text.partition(" : ")
            if gid != wd.account_id:
                wd.chat.append((time.time(), speaker.strip(), msg.strip(), "public"))
                self.events.put_nowait(("chat", speaker.strip()))
        elif pid == 0x008E:  # our own public chat, echoed by the server once it accepted it
            wd.own_chat = cstr(p[4:])
        elif pid == 0x09DE:  # whisper
            sender = cstr(p[8:32])
            msg = cstr(p[33:])
            wd.chat.append((time.time(), sender, msg, "whisper"))
            self.events.put_nowait(("whisper", sender))
        elif pid in (0x00B0, 0x00B1):  # status values (enum _sp in src/map/map.hpp)
            var, value = struct.unpack_from("<Hi", p, 2)
            self._status(var, value)
        elif pid == 0x0ACB:  # 64-bit status values (experience)
            var, value = struct.unpack_from("<Hq", p, 2)
            self._status(var, value)
        elif pid == 0x01D7:  # look change; type 0 on ourselves is a class change
            gid, look, value = struct.unpack_from("<IBI", p, 2)
            if gid == wd.account_id and look == 0 and value != wd.job:
                old, wd.job = wd.job, value
                self.events.put_nowait(("job_change", (old, value)))
        elif pid == 0x00B4:  # NPC dialog text
            wd.last_dialog_at = time.time()
            text = strip_colors(cstr(p[8:]))
            if text and not text.startswith("["):  # "[Name]" header lines carry no content
                wd.dialog.append(text)
        elif pid == 0x00B5:  # NPC dialog waits for "next"
            self._send(CZ_REQ_NEXT_SCRIPT, p[2:6])
        elif pid == 0x00B7:  # NPC menu: she chooses (answer_menu); empty options are hidden but keep their number
            wd.last_dialog_at = time.time()
            options = [strip_colors(o) for o in cstr(p[8:]).split(":")]
            self._wait("menu", struct.unpack_from("<I", p, 4)[0], options=options)
        elif pid == 0x00B6:  # NPC dialog closed
            self._send(CZ_CLOSE_DIALOG, p[2:6])
            if wd.npc_wait and wd.npc_wait["kind"] != "storage":
                wd.npc_wait = None
            self._finish_dialog(struct.unpack_from("<I", p, 2)[0])

    STATUS_FIELDS = {0: "speed", 1: "base_exp", 2: "job_exp", 5: "hp", 6: "max_hp", 7: "sp", 8: "max_sp", 9: "status_points", 11: "base_level",
                     12: "skill_points", 20: "zeny", 22: "next_base_exp", 23: "next_job_exp", 55: "job_level"}

    def _status(self, var, value):
        name = self.STATUS_FIELDS.get(var)
        if name is None:
            return
        old = getattr(self.world, name)
        setattr(self.world, name, value)
        if name in ("base_level", "job_level") and old and value > old:
            self.events.put_nowait(("level_up", (name, value)))

    def _npc_name(self, npc_gid):
        npc = self.world.units.get(npc_gid)
        return npc.name if npc else "um NPC"

    def _wait(self, kind, npc_gid, **extra):
        """An NPC window now expects her answer; what was said so far goes to the brain with it."""
        if kind == "deal":
            self._deal_npc = npc_gid
        name = self._npc_name(npc_gid)
        self.world.npc_wait = {"kind": kind, "npc": npc_gid, "name": name, "since": time.time(), **extra}
        lines = list(self.world.dialog)
        self.world.dialog.clear()
        self.events.put_nowait(("npc_wait", (name, lines)))

    def _finish_dialog(self, npc_gid):
        if self.world.dialog:
            npc = self.world.units.get(npc_gid)
            name = npc.name if npc else "um NPC"
            self.events.put_nowait(("npc_dialog", (name, list(self.world.dialog))))
            self.world.dialog.clear()

    # ---------------------------------------------------------------- actions

    def talk_to(self, npc_gid):
        self.world.dialog.clear()
        self._send(CZ_CONTACTNPC, struct.pack("<IB", npc_gid, 1))


    def answer_menu(self, choice):
        """choice: 1-based option number as the script counts them, 255 = cancel."""
        wait = self.world.npc_wait
        if wait and wait["kind"] == "menu":
            self.world.npc_wait = None
            self._send(CZ_CHOOSE_MENU, struct.pack("<IB", wait["npc"], choice))

    def answer_number(self, value):
        wait = self.world.npc_wait
        if wait and wait["kind"] == "number":
            self.world.npc_wait = None
            self._send(CZ_INPUT_NUMBER, struct.pack("<Ii", wait["npc"], value))

    def answer_text(self, text):
        wait = self.world.npc_wait
        if wait and wait["kind"] == "text":
            self.world.npc_wait = None
            raw = text.encode("latin1", "replace")[:70] + b"\0"
            self._send(CZ_INPUT_TEXT, struct.pack("<HI", len(raw) + 8, wait["npc"]) + raw)

    def deal(self, sell):
        wait = self.world.npc_wait
        if wait and wait["kind"] == "deal":
            self.world.npc_wait = None
            self._send(CZ_DEAL_TYPE, struct.pack("<IB", wait["npc"], 1 if sell else 0))

    def buy(self, items):
        """items: [(item id, amount)] from the open buy list."""
        body = b"".join(struct.pack("<HI", amount, item_id) for item_id, amount in items)
        self._send(CZ_BUY, struct.pack("<H", len(body) + 4) + body)

    def sell(self, items):
        """items: [(inventory index, amount)]."""
        body = b"".join(struct.pack("<HH", index, amount) for index, amount in items)
        self._send(CZ_SELL, struct.pack("<H", len(body) + 4) + body)

    def storage_put(self, index, amount):
        self._send(CZ_STORAGE_PUT, struct.pack("<Hi", index, amount))

    def storage_get(self, index, amount):
        self._send(CZ_STORAGE_GET, struct.pack("<Hi", index, amount))

    def close_npc(self):
        """Leaves whatever NPC window is open."""
        wait, self.world.npc_wait = self.world.npc_wait, None
        if not wait:
            return
        if wait["kind"] == "menu":
            self._send(CZ_CHOOSE_MENU, struct.pack("<IB", wait["npc"], 255))
        elif wait["kind"] in ("number", "text"):
            self._send(CZ_CLOSE_DIALOG, struct.pack("<I", wait["npc"]))
        elif wait["kind"] == "storage":
            self._send(CZ_STORAGE_CLOSE, b"")
        # deal / buy / sell windows close on the client side only

    def use_item(self, index):
        self._send(CZ_USE_ITEM, struct.pack("<HI", index, self.world.account_id))

    def equip(self, index):
        item = self.world.inventory.get(index)
        if item and item.slots:
            self._send(CZ_REQ_WEAR_EQUIP, struct.pack("<HI", index, item.slots))

    def unequip(self, index):
        self._send(CZ_REQ_TAKEOFF_EQUIP, struct.pack("<H", index))

    def walk_to(self, x, y):
        self.world.last_walk_result = "pending"
        self._send(CZ_REQUEST_MOVE, encode_pos(x, y))

    def say(self, text):
        text = text.strip()[:120]
        if not text or time.time() - self._last_chat_sent < 3:
            return False
        msg = f"{self.world.name} : {text}".encode("latin1", "replace") + b"\0"
        self._send(CZ_REQUEST_CHAT, struct.pack("<H", len(msg) + 4) + msg)
        self._last_chat_sent = time.time()
        self.world.chat.append((time.time(), self.world.name, text, "self"))
        return True

    def emote(self, name):
        if name in EMOTES:
            self._send(CZ_REQ_EMOTION, bytes([EMOTES[name]]))

    def attack(self, gid):
        self._send(CZ_REQUEST_ACT, struct.pack("<IB", gid, 7))

    def pick_up(self, item_gid):
        self._send(CZ_ITEM_PICKUP, struct.pack("<I", item_gid))

    def respawn(self):
        self._send(CZ_RESTART, b"\x00")
        self.world.dead = False
