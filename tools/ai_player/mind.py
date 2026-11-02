"""Lyra's persistent memory: players, diary, mood, stats, story, goal and what she learned."""
import json
import time

import config
from luaengine import short_name
from persona import ORIGIN_STORY

class Mind:
    """Persistent memory: notes per player, a diary of notable events, the current mood and life stats."""

    def __init__(self, path):
        self.path = path
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data and "players" not in data:  # first version stored only player notes
            data = {"players": data}
        self.players = data.get("players", {})
        self.diary = data.get("diary", [])
        self.mood = data.get("mood", {"state": "curiosa", "why": "acabei de chegar na capital"})
        self.stats = data.get("stats", {"kills": 0, "deaths": 0})
        self.world = data.get("knowledge", {"places": {}, "npcs": {}, "monsters": {}, "facts": []})
        self.world.setdefault("items", {})                         # item name -> effects observed
        self.world.setdefault("seen", {"monsters": [], "items": []})  # seen but never tried
        self.story = data.get("story", ORIGIN_STORY)
        self.goal = data.get("goal", "")

    def save(self):
        data = {"players": self.players, "diary": self.diary, "mood": self.mood, "stats": self.stats,
                "knowledge": self.world, "story": self.story, "goal": self.goal}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def rewrite_story(self, text):
        text = text.strip()[:1200]
        if text:
            self.story = text
            self.save()

    def about(self, names):
        return {n: self.players[n] for n in names if n in self.players}

    def remember(self, player, note):
        player, note = player.strip()[:24], note.strip()[:200]
        if player and note:
            self.players[player] = (self.players.get(player, []) + [note])[-8:]
            self.save()

    def write_diary(self, entry):
        entry = entry.strip()[:200]
        if entry:
            self.diary = (self.diary + [f"{time.strftime('%d/%m %H:%M')} {entry}"])[-40:]
            self.save()

    def feel(self, state, why):
        if state in config.MOODS and (state != self.mood["state"] or why.strip()):
            self.mood = {"state": state, "why": why.strip()[:150] or self.mood["why"]}
            self.save()

    def count(self, stat):
        self.stats[stat] = self.stats.get(stat, 0) + 1
        self.save()

    # -- knowledge of the world, learned only from experience

    def visit(self, place):
        if place and place not in self.world["places"]:
            self.world["places"][place] = time.strftime("%d/%m %H:%M")
            self.write_diary(f"Cheguei pela primeira vez em {place}")

    def see_npc(self, name, place, x, y):
        name = short_name(name)
        if name and name not in self.world["npcs"]:
            self.world["npcs"][name] = {"where": f"{place} {x},{y}", "said": []}
            self.save()

    def npc_said(self, name, lines):
        name = short_name(name)
        entry = self.world["npcs"].setdefault(name, {"where": "?", "said": []})
        entry["said"] = (entry["said"] + [" ".join(lines)[:300]])[-3:]
        self.save()

    def npc_does(self, name, what):
        """What she found out an NPC does by using it (menu options, a shop, the storage, a result)."""
        name = short_name(name)
        entry = self.world["npcs"].setdefault(name, {"where": "?", "said": []})
        does = entry.setdefault("faz", [])
        if what not in does:
            entry["faz"] = (does + [what[:200]])[-6:]
            self.save()

    def set_goal(self, goal):
        goal = goal.strip()[:200]
        if goal and goal != self.goal:
            self.goal = goal
            self.save()

    def fought(self, monster, outcome):
        m = self.world["monsters"].setdefault(short_name(monster), {"derrotados": 0, "me_derrotou": 0})
        m[outcome] = m.get(outcome, 0) + 1
        self.save()

    def monster_fact(self, monster, key, value):
        """What a monster did to her or gave her: strongest hit taken or dealt, experience, drops."""
        m = self.world["monsters"].setdefault(short_name(monster), {"derrotados": 0, "me_derrotou": 0})
        if key in ("dano_em_voce", "seu_dano"):
            if value <= m.get(key, 0):
                return
            m[key] = value
        elif key == "drops":
            if value in m.setdefault("drops", []):
                return
            m["drops"] = (m["drops"] + [value])[-8:]
        else:
            m[key] = value
        self.save()

    def item_effect(self, item, effect):
        effects = self.world["items"].setdefault(item, [])
        if effect not in effects:
            self.world["items"][item] = (effects + [effect])[-4:]
            self.save()

    def discover(self, kind, name):
        """True the first time a kind of monster or item is seen; NPCs count once see_npc records them."""
        known = self.world["monsters"] if kind == "monsters" else self.world["items"]
        if not name or name in known or name in self.world["seen"][kind]:
            return False
        self.world["seen"][kind] = (self.world["seen"][kind] + [name])[-200:]
        self.save()
        return True

    def learn(self, fact):
        fact = fact.strip()[:200]
        if fact and fact not in self.world["facts"]:
            self.world["facts"] = (self.world["facts"] + [fact])[-60:]
            self.save()

    def knowledge(self, place):
        k = self.world
        here = {n: v for n, v in k["npcs"].items() if v["where"].startswith(place + " ")}
        lines = [f"Lugares que voce conhece: {', '.join(k['places']) or 'nenhum'}"]
        if here:
            lines.append(f"NPCs que voce ja viu em {place}:")
            for n, v in list(here.items())[:20]:
                said = f" - disse: {v['said'][-1][:160]}" if v["said"] else " (nunca conversou)"
                does = f" | o que voce descobriu que ele faz: {'; '.join(v['faz'])}" if v.get("faz") else ""
                lines.append(f"- {n} em {v['where'].split(' ', 1)[1]}{said}{does}")
        elsewhere = [f"{n} ({v['where'].split(' ', 1)[0]}): {'; '.join(v['faz'])}"
                     for n, v in k["npcs"].items() if v.get("faz") and n not in here]
        if elsewhere:
            lines.append("NPCs de outros lugares que voce ja usou: " + " | ".join(elsewhere[-15:]))
        others = len(k["npcs"]) - len(here)
        if others > 0:
            lines.append(f"(e mais {others} NPCs em outros lugares)")
        if k["monsters"]:
            lines.append("O que voce sabe dos monstros que enfrentou:")
            for n, v in k["monsters"].items():
                parts = [f"derrotou {v.get('derrotados', 0)}, perdeu {v.get('me_derrotou', 0)}"]
                if "dano_em_voce" in v:
                    parts.append(f"ja te tirou ate {v['dano_em_voce']} HP num golpe")
                if "seu_dano" in v:
                    parts.append(f"voce tira ate {v['seu_dano']} por golpe")
                if "exp" in v:
                    parts.append(f"rende {v['exp']}")
                if v.get("drops"):
                    parts.append("deixa cair " + ", ".join(v["drops"]))
                lines.append(f"- {n}: " + "; ".join(parts))
        if k["items"]:
            lines.append("O que voce sabe dos itens que experimentou:")
            lines += [f"- {n}: " + "; ".join(e) for n, e in list(k["items"].items())[-25:]]
        untried = k["seen"]["monsters"][-10:] + k["seen"]["items"][-10:]
        if untried:
            lines.append("Coisas que voce ja viu mas nunca experimentou: " + ", ".join(untried))
        if k["facts"]:
            lines.append("Coisas que voce aprendeu:")
            lines += [f"- {f}" for f in k["facts"][-15:]]
        return lines
