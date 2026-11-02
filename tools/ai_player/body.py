"""Lyra's body: primitives, reflexes and outcome measurement between model turns."""
import asyncio
import logging
import math
import random
import time

import atlas
import config
import luaengine
from gamedata import find_item, to_game_text
from luaengine import cells, short_name
from npc import answer_npc

log = logging.getLogger("ai_player")

class Body:
    """What runs between model turns, every config.TICK. Like the client's homunculus AI (AI/AI.lua), the engine
    keeps a few primitives (walk with detours, chase and attack, talk to an NPC) and reflexes (drink a
    potion, hit back at a monster attacking her or the player she follows); the behaviour itself is a Lua
    routine (luaengine.py), chosen or written by the model. It also measures what each experience gave
    her and writes it to the Mind."""

    def __init__(self, client, mind, item_names, world_atlas=None):
        self.client = client
        self.mind = mind
        self.item_names = item_names
        self.atlas = world_atlas
        self.path = None            # cells to dest from the atlas (A*), or [] when unknown
        self.path_i = 0             # her index along self.path
        self.dest_map = ""
        self.dest_span = 0
        self.go_timeout = config.GO_TIMEOUT
        self.talk_near = None       # (x, y) to pick the right NPC when several share a name
        self.wait_shown = None      # "since" of the NPC window shown in the last prompt
        self.pending_kills = []     # (time, name, x, y, exp mark, ground items before) awaiting exp and drops
        self.pending_uses = []      # (time, item name, hp, sp, max hp) awaiting the item's effect
        self.hits_seen = 0.0
        self.log_seen = 0.0
        self.exp_mark = None
        self.told_enemy = set()
        self.monster_names = {}     # gid -> name of monsters seen, kept a while after they vanish
        self.clicked = None         # (npc name, time) of the last click, to notice NPCs that say nothing
        self.dest = None            # (x, y) walked to with detours by _go_step
        self.dest_since = self.go_sent = 0.0
        self.go_fails = 0
        self.talk = ""              # NPC to walk to and talk with (one-shot)
        self.talk_since = 0.0
        self.last_goal = None
        self.target = None          # gid currently attacked
        self.target_name = ""
        self.target_since = 0.0
        self.defending = False      # the target was chosen by the reflex, not by the routine
        self.attack_sent = 0.0
        self.healed_at = 0.0
        self.kills = 0
        self.engine = luaengine.LuaEngine(
            self, say=lambda text: client.say(to_game_text(text)),
            find_item=lambda name, worn: find_item(client.world, item_names, name, worn),
            answer=lambda text: answer_npc(client, self, text))

    # ------------------------------------------------------------------ primitives used by the routines

    def go(self, x, y, span=0):
        """Starts walking to (x, y); False when the map's cells say it cannot be reached from here."""
        w = self.client.world
        self.dest, self.dest_span, self.dest_map = (x, y), span, w.map
        self.dest_since, self.go_sent, self.go_fails = time.time(), 0.0, 0
        self.path, self.go_timeout = None, config.GO_TIMEOUT
        if self.atlas and self.atlas.grid(w.map) is not None:
            planned = self.atlas.path(w.map, (w.x, w.y), (x, y), span)
            if planned is None:
                self.dest = None
                return False
            self.path, self.path_i, self.go_timeout = planned, 0, config.GO_TIMEOUT + 0.4 * len(planned)
        return True

    def _go_step(self, w):
        """Walks to self.dest (any cell within dest_span of it) the way a player holding the mouse button does:
        the whole path is planned over the map's cells (atlas A*), and every config.WALK_REPEAT seconds a new walk is
        requested to the path cell atlas.LEG steps ahead of where she really is. A walk request during a walk
        only changes the target at the next cell (unit_walktoxy in src/map/unit.cpp), so she never stops, and
        each target stays within the server's 32-step path limit. On a map the atlas does not know, a refused
        walk is retried through a stepping stone."""
        now = time.time()
        x, y = self.dest
        if w.map != self.dest_map or cells(w.x, w.y, x, y) <= self.dest_span or now - self.dest_since > self.go_timeout:
            self.dest = None
            return
        if now - self.go_sent < config.WALK_REPEAT:
            return
        if self.go_sent:
            refused = w.last_walk_result != "ok"
            self.go_fails = self.go_fails + 1 if refused else 0
            if refused:
                self.path = None  # plan again from where she really is
        here = self._position(w, now)
        if self.path is None:
            known = self.atlas is not None and self.atlas.grid(w.map) is not None
            planned = self.atlas.path(w.map, here, (x, y), self.dest_span) if known else None
            if known and planned is None:
                self.dest = None  # walled off from here: let the routine choose something else
                return
            self.path, self.path_i = planned or [], 0
        if self.path:
            # where she is along the path (the server's last start cell plus the time walked since)
            window = range(self.path_i, min(len(self.path), self.path_i + atlas.LEG + 8))
            self.path_i = min(window, key=lambda i: cells(*self.path[i], *here), default=self.path_i)
            ahead = 4 if self.go_fails else atlas.LEG  # a refused target: a closer one (a unit in the way)
            goal = self.path[min(self.path_i + ahead, len(self.path) - 1)]
            if goal == (w.x, w.y) and now < w.walk_until:
                return  # already heading to the end of the path
        else:
            goal = (x, y)
            if self.go_fails:
                step = max(3, cells(x, y, here[0], here[1]) // 2)
                angle = math.atan2(y - here[1], x - here[0]) + random.uniform(-1.2, 1.2)
                goal = (max(1, round(here[0] + math.cos(angle) * step)), max(1, round(here[1] + math.sin(angle) * step)))
        self.client.walk_to(*goal)
        self.go_sent = now

    def _position(self, w, now):
        """Her cell now: the start of the last accepted walk, moved along by the time walked since."""
        if not w.walk_from or now >= w.walk_until:
            return w.x, w.y
        (x0, y0), total = w.walk_from, max(w.walk_until - w.walk_from_at, 0.01)
        f = min(1.0, (now - w.walk_from_at) / total)
        return round(x0 + (w.x - x0) * f), round(y0 + (w.y - y0) * f)

    def attack(self, gid):
        """Attack(id) for routines: 2 = hitting, 1 = closing in, 0 = not a monster in sight."""
        w = self.client.world
        u = w.units.get(gid)
        if u is None or u.kind != "monster":
            return 0
        if self.target != gid:
            self._set_target(w, u)
        self.defending = False
        return self._engage(w, u)

    def _engage(self, w, t):
        """Walks next to the target, then attacks; the server keeps hitting (action 7) while it stays in range."""
        if time.time() < w.walk_until:
            return 1  # still on the way: an attack sent now would be refused as too far
        if cells(t.x, t.y, w.x, w.y) > config.ATTACK_RANGE:
            goal = (t.x + (w.x > t.x) - (w.x < t.x), t.y + (w.y > t.y) - (w.y < t.y))
            if goal != self.last_goal or w.too_far_at > self.attack_sent:
                self.client.walk_to(*goal)
                self.last_goal, self.attack_sent = goal, 0.0
            return 1
        if w.too_far_at > self.attack_sent or time.time() - self.attack_sent > config.ATTACK_REFRESH:
            self.client.attack(t.gid)
            self.attack_sent = time.time()
        self.target_since = time.time()
        return 2

    def use_item(self, index):
        """Uses an item and remembers the state before, so _observe can tell what it did."""
        w = self.client.world
        item = w.inventory.get(index)
        if item:
            self.pending_uses.append((time.time(), self.mind_item_name(item.item_id), w.hp, w.sp, w.max_hp))
            self.client.use_item(index)

    def mind_item_name(self, item_id):
        return self.item_names.get(item_id, f"item {item_id}")

    def set_talk(self, name, near=None):
        name = short_name(name.strip())[:24]
        if name and name.lower() != self.talk.lower():
            self.talk, self.talk_since, self.talk_near = name, time.time(), near

    def _talk_step(self, w):
        """Walks within 3 cells of the NPC and clicks it once; gives up after config.TALK_TIMEOUT."""
        want = self.talk.lower()
        near = self.talk_near or (w.x, w.y)
        matches = [u for u in w.units.values() if u.kind in ("npc", "portal") and short_name(u.name).lower() == want]
        npc = min(matches, key=lambda u: cells(u.x, u.y, *near), default=None)
        if npc is None or time.time() - self.talk_since > config.TALK_TIMEOUT:
            self.client.events.put_nowait(("npc_missing", self.talk))
            self.talk = ""
            return
        if npc.kind == "portal":  # a portal is used by stepping on it, not by clicking
            self.go(npc.x, npc.y)
            self.talk = ""
            return
        if cells(npc.x, npc.y, w.x, w.y) > 3:
            if self.dest != (npc.x, npc.y):
                self.go(npc.x, npc.y, span=2)  # NPCs often stand on cells nobody can walk on
            if self.dest:
                self._go_step(w)
            return
        self.client.talk_to(npc.gid)
        self.clicked = (npc.name, time.time())
        self.talk = ""

    def status(self):
        w = self.client.world
        parts = []
        if self.talk:
            parts.append(f"indo conversar com {self.talk}")
        if self.defending and self.target in w.units:
            parts.append(f"se defendendo de {short_name(w.units[self.target].name)}")
        routine = self.engine.status()
        if routine:
            parts.append(f"{routine}, {self.kills} monstros derrotados nesta sessao")
        return "; ".join(parts) or "nada continuo (nenhuma rotina rodando)"

    # ------------------------------------------------------------------ the loop

    async def run(self):
        while True:
            await asyncio.sleep(config.TICK)
            w = self.client.world
            self._observe(w)
            self.mind.flush(force=False)  # what changed reaches the disk every few seconds
            self._track_kill(w)
            healing = self._heal(w)
            fighting = time.time() - self.attack_sent < 5
            if self.engine.active and fighting and w.max_hp and w.hp < config.HUNT_STOP_HP * w.max_hp and not healing:
                name = self.engine.active["name"]
                self.engine.stop()
                self.client.events.put_nowait(("hp_low", name))
            if w.dead:
                continue
            if self.talk:
                self._talk_step(w)
                continue
            enemy = self._enemy(w)
            if enemy is not None and enemy.gid != self.target:
                self._set_target(w, enemy)
                self.defending = True
                if enemy.gid not in self.told_enemy:
                    if len(self.told_enemy) > 200:  # gids of monsters long gone
                        self.told_enemy.clear()
                    self.told_enemy.add(enemy.gid)
                    self.client.events.put_nowait(("attacked", short_name(enemy.name)))
            if self.defending:  # GetMyEnemy / GetOwnerEnemy: the reflex comes before the routine
                u = w.units.get(self.target)
                if u is not None and time.time() - self.target_since < config.DEFEND_GIVE_UP:
                    self._engage(w, u)
                    continue
                self.defending = False
            if w.npc_wait and time.time() - w.npc_wait["since"] > config.NPC_WAIT_TIMEOUT:
                self.client.close_npc()
            if not w.npc_wait:  # like a player reading an NPC window, the routine waits for her answer
                self.engine.tick()
            if self.dest:
                self._go_step(w)

    def _track_kill(self, w):
        if self.target is None or self.target not in w.killed:
            return
        self.kills += 1
        self.mind.count("kills")
        self.mind.fought(self.target_name, "derrotados")
        dead = w.last_seen.get(self.target_name, (w.x, w.y, 0))
        self.pending_kills.append((time.time(), self.target_name, dead[0], dead[1], self.exp_mark, set(w.items)))
        log.info("defeated %s (%d this session)", self.target_name, self.kills)
        self.target, self.defending = None, False

    def _heal(self, w):
        """Drinks a healing item when HP is below config.POTION_AT; returns whether any healing item is left."""
        potions = [i for i in w.inventory.values() if i.type == config.HEALING and i.amount > 0]
        if (potions and not w.dead and w.max_hp and w.hp < config.POTION_AT * w.max_hp
                and time.time() - self.healed_at > config.POTION_GAP):
            self.use_item(potions[0].index)
            self.healed_at = time.time()
        return bool(potions)

    def _enemy(self, w):
        """A monster that hit her or the player her routine follows (GetMyEnemy / GetOwnerEnemy)."""
        friend = str(self.engine.arg("player") or "").lower()
        friends = {w.account_id} | {u.gid for u in w.units.values()
                                    if u.kind == "player" and friend and short_name(u.name).lower() == friend}
        now = time.time()
        for t, src, target, _ in reversed(w.hits):
            if now - t > config.DEFEND_WINDOW:
                break
            u = w.units.get(src)
            if target in friends and u is not None and u.kind == "monster":
                return u
        return None

    def _set_target(self, w, u):
        self.target, self.target_since, self.target_name = u.gid, time.time(), u.name
        self.attack_sent = 0.0
        self.exp_mark = (w.base_level, w.job_level, w.base_exp, w.job_exp)

    def _observe(self, w):
        """Turns what just happened into knowledge: hits, experience and drops per monster, item effects,
        equipment results, and first sightings (which also give her a turn to react)."""
        now = time.time()
        if self.clicked and now - self.clicked[1] > config.SILENT_NPC_AFTER:
            name, t = self.clicked
            self.clicked = None
            if w.last_dialog_at < t:
                self.mind.npc_said(name, ["(voce clicou e nada aconteceu)"])
                self.client.events.put_nowait(("npc_silent", short_name(name)))
        for u in w.units.values():  # a killing blow arrives together with the vanish packet
            if u.kind == "monster":
                self.monster_names[u.gid] = u.name
        if len(self.monster_names) > 500:
            self.monster_names = {g: n for g, n in self.monster_names.items() if g in w.units}
        for t, src, target, damage in w.hits:
            if t <= self.hits_seen or damage <= 0:
                continue
            if target == w.account_id and src in self.monster_names:
                self.mind.monster_fact(self.monster_names[src], "dano_em_voce", damage)
            elif src == w.account_id and target in self.monster_names:
                self.mind.monster_fact(self.monster_names[target], "seu_dano", damage)
        if w.hits:
            self.hits_seen = w.hits[-1][0]

        for kill in list(self.pending_kills):
            t, name, x, y, mark, before = kill
            for gid, (item_id, _, ix, iy) in w.items.items():  # checked every tick: looting is quick
                if gid not in before and cells(ix, iy, x, y) <= 2:
                    before.add(gid)
                    self.mind.monster_fact(name, "drops", self.mind_item_name(item_id))
            if now - t > config.OUTCOME_DELAY:
                self.pending_kills.remove(kill)
                if mark and mark[:2] == (w.base_level, w.job_level):
                    self.mind.monster_fact(name, "exp", f"{w.base_exp - mark[2]} exp de base e "
                                                        f"{w.job_exp - mark[3]} de classe")

        for use in [u for u in self.pending_uses if now - u[0] > config.OUTCOME_DELAY]:
            self.pending_uses.remove(use)
            t, name, hp, sp, max_hp = use
            used = any(what == "used" and lt >= t - 0.5 and self.mind_item_name(i) == name
                       for lt, what, i, _ in w.item_log)
            effects = []
            if w.hp > hp:
                effects.append(f"recuperou {w.hp - hp} HP")
            if w.sp > sp:
                effects.append(f"recuperou {w.sp - sp} SP")
            if w.max_hp != max_hp:
                effects.append(f"HP maximo mudou {w.max_hp - max_hp:+d}")
            if not used:
                effects.append("nao deu para usar")
            elif not effects:
                effects.append("usado sem efeito visivel (talvez precise de outro momento ou seja de outro tipo)")
            self.mind.item_effect(name, "ao usar: " + ", ".join(effects))
            self.client.events.put_nowait(("item_effect", f"{name}: {', '.join(effects)}"))

        for t, what, item_id, _ in w.item_log:
            if t <= self.log_seen:
                continue
            name = self.mind_item_name(item_id)
            if what == "equipped":
                self.mind.item_effect(name, "voce consegue vestir")
            elif what == "equip_failed":
                self.mind.item_effect(name, "voce nao conseguiu vestir (talvez classe ou nivel)")
            elif what == "gained" and self.mind.discover("items", name):
                self.client.events.put_nowait(("discovery", f"conseguiu um item novo: {name}"))
        if w.item_log:
            self.log_seen = w.item_log[-1][0]

        for u in w.units.values():
            if u.kind == "monster" and cells(u.x, u.y, w.x, w.y) <= config.VIEW_RANGE \
                    and self.mind.discover("monsters", short_name(u.name)):
                self.client.events.put_nowait(("discovery", f"um monstro que voce nunca viu: {short_name(u.name)}"))
        for item_id, _, x, y in w.items.values():
            name = self.mind_item_name(item_id)
            if cells(x, y, w.x, w.y) <= config.VIEW_RANGE and self.mind.discover("items", name):
                self.client.events.put_nowait(("discovery", f"um item no chao que voce nunca viu: {name}"))
