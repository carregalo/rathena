"""Runs the agent's own Lua routines (lua/base written by hand, lua/learned written by the model).

The shape follows the game client's homunculus AI (AI/AI.lua): the engine offers a few primitive actions
and a routine decides when to call them, once per tick. The client's AI/*.lua files are neither used nor
changed. Routines run in lua/sandbox.lua: no access to files, the OS or Python objects, and an instruction
limit per call.
"""
import json
import logging
import math
import os
import re
import time

import lupa.lua54 as lua

import roclient

HERE = os.path.dirname(os.path.abspath(__file__))
LUA_DIR = os.path.join(HERE, "lua")
BASE_DIR = os.path.join(LUA_DIR, "base")
LEARNED_DIR = os.path.join(LUA_DIR, "learned")
API_DOC = open(os.path.join(LUA_DIR, "API.md"), encoding="utf-8").read()

MAX_MEMORY = 64 * 1024 * 1024
MAX_CODE = 6000            # characters in a learned routine
VIEW_RANGE = 14            # battle_config area_size
MOVE_STEP = 12             # Move() walks at most this far per leg; routines call it again until arriving
TARGET_WINDOW = 3          # seconds a hit counts for GetV(V_TARGET)
NOTIFY_GAP = 10            # seconds between two Notify() calls
ROUTINE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
V_POSITION, V_TYPE, V_NAME, V_TARGET, V_HP, V_MAXHP, V_SP, V_MAXSP = range(8)

log = logging.getLogger("ai_player")


def cells(ax, ay, bx, by):
    """Square distance, the way the server measures view and attack range."""
    return max(abs(ax - bx), abs(ay - by))


def short_name(name):
    return name.split("#", 1)[0]


def _deny_attributes(obj, attr_name, is_setting):
    raise AttributeError("python objects are not accessible from routines")


def _header(code):
    """Purpose and args lines from the first comment lines of a routine."""
    lines = [l.strip()[2:].strip() for l in code.splitlines()[:3] if l.strip().startswith("--")]
    purpose = lines[0] if lines else ""
    args = next((l[5:].strip() for l in lines[1:] if l.lower().startswith("args:")), "")
    return purpose, args


class LuaEngine:
    def __init__(self, body, say, find_item, answer):
        """body: agent.Body (moves, attacks, talks); say(text), find_item(name, worn) and answer(text) (to the
        open NPC window) come from agent.py."""
        self.body, self.client = body, body.client
        self.say, self.find_item, self.answer = say, find_item, answer
        self.L = lua.LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False,
                                attribute_filter=_deny_attributes, max_memory=MAX_MEMORY)
        self.sandbox = self.L.execute(open(os.path.join(LUA_DIR, "sandbox.lua"), encoding="utf-8").read())
        self.api = self.L.table_from(self._api())
        self.routines = {}          # name -> {"code", "purpose", "args", "learned"}
        self.active = None          # {"name", "args", "args_key", "env", "since"}
        self.done_text = None
        self.move_target = None
        self.route = None           # the trip FollowRoute is on: {"key", "map", "steps"}
        self.notified_at = 0.0
        self.load_library()

    # ------------------------------------------------------------------ library

    def load_library(self):
        for folder, learned in ((BASE_DIR, False), (LEARNED_DIR, True)):
            for file in sorted(os.listdir(folder)):
                if file.endswith(".lua"):
                    code = open(os.path.join(folder, file), encoding="utf-8").read()
                    purpose, args = _header(code)
                    self.routines[file[:-4]] = {"code": code, "purpose": purpose, "args": args, "learned": learned}

    def describe(self):
        lines = []
        for name, r in self.routines.items():
            who = "sua" if r["learned"] else "basica"
            lines.append(f"- {name} ({who}): {r['purpose']}" + (f" | args: {r['args']}" if r["args"] else ""))
        return lines

    def write(self, name, purpose, code):
        """Stores a routine written by the model in lua/learned. Returns an error message or None."""
        name = name.strip().lower()
        if not ROUTINE_NAME.match(name):
            return "nome invalido: use letras minusculas, numeros e _ (2 a 30 caracteres)"
        if name in self.routines and not self.routines[name]["learned"]:
            return f"{name} e uma rotina basica; escolha outro nome"
        if len(code) > MAX_CODE:
            return f"rotina grande demais (maximo {MAX_CODE} caracteres)"
        if purpose.strip() and not code.lstrip().startswith("--"):
            code = f"-- {purpose.strip()}\n{code}"
        ok, err = self.sandbox.load(code, name, self.sandbox.new_env(self.api))
        if not ok:
            return f"a rotina nao compila ou falhou ao carregar: {err}"
        with open(os.path.join(LEARNED_DIR, name + ".lua"), "w", encoding="utf-8") as f:
            f.write(code)
        p, a = _header(code)
        self.routines[name] = {"code": code, "purpose": p, "args": a, "learned": True}
        log.info("routine %s written (%d chars)", name, len(code))
        if self.active and self.active["name"] == name:
            self.active = None  # restart with the new code on the next start()
        return None

    # ------------------------------------------------------------------ running

    def start(self, name, args_json):
        """Starts a routine, or keeps it running when name and args are the same. Returns an error or None."""
        name = name.strip().lower()
        if name not in self.routines:
            return f"nao existe rotina chamada {name}"
        try:
            args = json.loads(args_json) if args_json.strip() else {}
        except ValueError as e:
            return f"routine_args nao e um JSON valido: {e}"
        if not isinstance(args, dict):
            return "routine_args precisa ser um objeto JSON, ex.: {\"monster\": \"Poring\"}"
        key = json.dumps(args, sort_keys=True)
        if self.active and self.active["name"] == name and self.active["args_key"] == key:
            return None
        self.stop()
        env = self.sandbox.new_env(self.api)
        ok, err = self.sandbox.load(self.routines[name]["code"], name, env)
        if not ok:
            return f"erro ao carregar {name}: {err}"
        lua_args = self.L.table_from(args, recursive=True)
        self.active = {"name": name, "args": args, "lua_args": lua_args, "args_key": key, "env": env,
                       "since": time.time()}
        self.done_text = None
        ok, err = self.sandbox.call(env, "Start", lua_args)
        if not ok:
            self.active = None
            return f"erro em {name}.Start: {err}"
        log.info("routine %s started with %s", name, key)
        return None

    def stop(self):
        if self.active:
            log.info("routine %s stopped", self.active["name"])
        self.active = None
        self.move_target = None
        self.route = None
        self.body.dest = None

    def tick(self):
        if not self.active:
            return
        a = self.active
        ok, err = self.sandbox.call(a["env"], "Tick", a["lua_args"])
        if not ok:
            self.stop()
            self.client.events.put_nowait(("routine_error", f"{a['name']}: {err}"))
        elif self.done_text is not None:
            text, self.done_text = self.done_text, None
            self.stop()
            self.client.events.put_nowait(("routine_done", f"{a['name']}: {text}"))

    def status(self):
        if not self.active:
            return ""
        a = self.active
        return f"rotina {a['name']} {a['args_key']} ha {int(time.time() - a['since'])} s"

    def arg(self, key):
        return self.active["args"].get(key) if self.active else None

    # ------------------------------------------------------------------ API seen by routines

    def _api(self):
        body, client = self.body, self.client

        def world():
            return client.world

        def GetTick():
            return int(time.monotonic() * 1000)

        def GetActors():
            w = world()
            return self.L.table_from([u.gid for u in w.units.values() if cells(u.x, u.y, w.x, w.y) <= VIEW_RANGE + 2])

        def GetV(v, gid):
            w = world()
            if gid == w.account_id:
                return {V_POSITION: (w.x, w.y), V_TYPE: "self", V_NAME: w.name, V_TARGET: body.target or 0,
                        V_HP: w.hp, V_MAXHP: w.max_hp, V_SP: w.sp, V_MAXSP: w.max_sp}.get(v)
            u = w.units.get(gid)
            if u is None:
                return None
            if v == V_POSITION:
                return u.x, u.y
            if v == V_TYPE:
                return u.kind
            if v == V_NAME:
                return short_name(u.name)
            if v == V_TARGET:
                now = time.time()
                return next((t for at, src, t, _ in reversed(w.hits)
                             if src == gid and now - at <= TARGET_WINDOW), 0)
            return None

        def IsMonster(gid):
            u = world().units.get(gid)
            return 1 if u is not None and u.kind == "monster" else 0

        def GetDistance(gid):
            w = world()
            u = w.units.get(gid)
            return cells(u.x, u.y, w.x, w.y) if u is not None else -1

        def FindByName(kind, name):
            w = world()
            want = short_name(str(name)).lower()
            found = [u for u in w.units.values() if u.kind == kind and short_name(u.name).lower() == want]
            return min(found, key=lambda u: cells(u.x, u.y, w.x, w.y)).gid if found else 0

        def GetLastSeen(name):
            want = short_name(str(name)).lower()
            spot = next(((x, y) for n, (x, y, _) in world().last_seen.items() if short_name(n).lower() == want), None)
            return spot if spot else None

        def WasKilled(gid):
            return gid in world().killed

        def Move(x, y, span=0):
            w = world()
            x, y, span = int(x), int(y), int(span or 0)
            if self.move_target == (x, y) and body.dest:
                return True  # still on the way
            self.move_target = (x, y)
            if body.atlas is None or body.atlas.grid(w.map) is None:
                dist = math.hypot(x - w.x, y - w.y)
                if dist > MOVE_STEP:  # no map cells known: one short leg at a time
                    x, y = round(w.x + (x - w.x) * MOVE_STEP / dist), round(w.y + (y - w.y) * MOVE_STEP / dist)
            if cells(x, y, w.x, w.y) > span and not body.go(max(1, x), max(1, y), span):
                self.move_target = None
                return False  # no way to walk there from here
            return True

        def IsMoving():
            return body.dest is not None or time.time() < world().walk_until

        def Stop():
            body.dest, self.move_target = None, None

        def Attack(gid):
            return body.attack(gid)

        def GetGroundItems():
            w = world()
            names = body.item_names
            return self.L.table_from([
                self.L.table_from({"id": gid, "name": names.get(item_id, f"item {item_id}"), "x": x, "y": y,
                                   "amount": amount, "dist": cells(x, y, w.x, w.y)})
                for gid, (item_id, amount, x, y) in w.items.items() if cells(x, y, w.x, w.y) <= VIEW_RANGE + 2])

        def PickUp(gid):
            w = world()
            item = w.items.get(gid)
            if item is None:
                return False
            _, _, x, y = item
            if cells(x, y, w.x, w.y) <= 1:
                client.pick_up(gid)
            else:
                Move(x, y)
            return True

        def GetInventory():
            names = body.item_names
            return self.L.table_from([
                self.L.table_from({"name": names.get(i.item_id, f"item {i.item_id}"), "amount": i.amount,
                                   "type": roclient.ITEM_TYPES.get(i.type, "outro"), "worn": bool(i.worn)})
                for i in world().inventory.values()])

        def UseItem(name):
            item = self.find_item(str(name), None)
            if item:
                body.use_item(item.index)
            return item is not None

        def Equip(name):
            item = self.find_item(str(name), False)
            if item:
                client.equip(item.index)
            return item is not None

        def Unequip(name):
            item = self.find_item(str(name), True)
            if item:
                client.unequip(item.index)
            return item is not None

        def Talk(name, x=None, y=None):
            body.set_talk(str(name), (int(x), int(y)) if x is not None and y is not None else None)
            return True

        def GetMap():
            return world().map

        def FindNpc(name):
            if body.atlas is None:
                return self.L.table_from([])
            return self.L.table_from([self.L.table_from({"name": n.name, "map": n.map, "x": n.x, "y": n.y})
                                      for n in body.atlas.find_npcs(str(name), world().map,
                                                                    pos=(world().x, world().y))])

        def Route(to_map, x=None, y=None):
            w = world()
            if body.atlas is None:
                return None, "sem mapa de viagem"
            dst = (int(x), int(y)) if x is not None and y is not None else None
            steps = body.atlas.route(w.map, w.x, w.y, str(to_map), dst)
            if steps is None:
                return None, f"nenhum caminho a pe conhecido de {w.map} ate {to_map}"
            return self.L.table_from([self.L.table_from(s) for s in steps]), None

        def FollowRoute(to_map, x=None, y=None, near=2):
            """One step of a trip to another map (or a point of it): True on arrival, False while on the way,
            nil and the reason when there is no way. The route is planned once and again after each portal."""
            w = world()
            to_map, near = str(to_map), int(near or 2)
            dst = (int(x), int(y)) if x is not None and y is not None else None
            if w.map == to_map and (dst is None or cells(dst[0], dst[1], w.x, w.y) <= near):
                return True
            r = self.route
            if not r or r["key"] != (to_map, dst) or r["map"] != w.map:
                steps = body.atlas.route(w.map, w.x, w.y, to_map, dst) if body.atlas else None
                if steps is None:
                    self.route = None
                    return None, f"nenhum caminho a pe conhecido de {w.map} ate {to_map}"
                self.route = r = {"key": (to_map, dst), "map": w.map, "steps": steps}
            step = r["steps"][0]
            if not Move(step["x"], step["y"], step.get("span", near)):  # the last step has no portal span
                self.route = None
                return None, f"nao consigo andar ate {step['x']},{step['y']} em {w.map}"
            return False

        def GetNpcWait():
            wait = world().npc_wait
            if not wait:
                return None
            info = {"kind": wait["kind"], "name": short_name(wait["name"])}
            if wait["kind"] == "menu":
                info["options"] = self.L.table_from([o for o in wait["options"]])
            return self.L.table_from(info)

        def Reply(text):
            return self.answer(str(text))

        def Say(text):
            return self.say(str(text))

        def Emote(name):
            client.emote(str(name))

        def Notify(text):
            if time.time() - self.notified_at >= NOTIFY_GAP and self.active:
                self.notified_at = time.time()
                client.events.put_nowait(("routine_note", f"{self.active['name']}: {str(text)[:200]}"))

        def Done(text=""):
            self.done_text = str(text)[:200]

        def Log(text):
            log.info("lua %s: %s", self.active["name"] if self.active else "?", str(text)[:200])

        api = {name: fn for name, fn in locals().items() if callable(fn) and name[0].isupper()}
        api.update(MyID=client.world.account_id, V_POSITION=V_POSITION, V_TYPE=V_TYPE, V_NAME=V_NAME,
                   V_TARGET=V_TARGET, V_HP=V_HP, V_MAXHP=V_MAXHP, V_SP=V_SP, V_MAXSP=V_MAXSP)
        return api
