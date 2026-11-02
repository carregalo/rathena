"""The text Lyra sees each turn: story, state, memory, travel map, what is in sight, bag, NPC window, chat."""
import json
import time

import atlas
import config
import roclient
from gamedata import JOB_NAMES
from luaengine import cells, short_name
from npc import describe_wait

def percent(value, total):
    return f"{100 * value // total}%" if total else "?"


ITEM_CHANGES = {"gained": "ganhou", "used": "usou", "lost": "perdeu", "equipped": "vestiu",
                "unequipped": "tirou", "equip_failed": "nao conseguiu vestir/tirar"}


def town_label(m):
    return f" ({atlas.MAIN_TOWNS[m]})" if m in atlas.MAIN_TOWNS else ""


def travel_map(world_atlas, mind, w):
    """What her travel map shows: the main towns by name and how far they are, this map's NPCs by name and
    position (not what they do: she finds that out by using them), and where this map's exits lead."""
    if world_atlas is None:
        return []
    hops = world_atlas.map_hops(w.map)
    towns = sorted((hops[m], m) for m in atlas.MAIN_TOWNS if m in hops)
    lines = ["Seu mapa de viagem - cidades (portais a atravessar daqui): " +
             ", ".join(f"{m} {atlas.MAIN_TOWNS[m]} ({h})" for h, m in towns)]
    known = mind.world["npcs"]
    groups = {}
    for n in world_atlas.npcs.get(w.map, []):
        groups.setdefault(n.name, []).append(f"{n.x},{n.y}")
    if groups:
        parts = []
        for name, spots in sorted(groups.items()):
            mark = "" if name in known and known[name].get("said") else " *"
            parts.append(f"{name}{mark} {'; '.join(spots[:3])}" + (f" (+{len(spots) - 3})" if len(spots) > 3 else ""))
        lines.append(f"NPCs de {w.map} no seu mapa ({len(groups)} nomes; * = nunca conversou): " + " | ".join(parts[:80]))
    exits = {}
    for x, y, to in world_atlas.exits(w.map):
        exits.setdefault(to, (x, y))
    if exits:
        lines.append(f"Saidas de {w.map}: " + ", ".join(f"{to} em {x},{y}" for to, (x, y) in sorted(exits.items())))
    return lines


def observation(client, mind, body, item_names, reason, milestone):
    w = client.world
    in_view = [u for u in w.units.values() if cells(u.x, u.y, w.x, w.y) <= config.VIEW_RANGE + 2]
    by_kind = {}
    for u in sorted(in_view, key=lambda u: cells(u.x, u.y, w.x, w.y)):
        by_kind.setdefault(u.kind, []).append(u)
        if u.kind == "npc":
            mind.see_npc(u.name, w.map, u.x, u.y)

    lines = [
        f"Motivo deste turno: {reason}",
        *(["ESTE TURNO E UM MARCO: preencha story_update com a historia reescrita."] if milestone else []),
        f"Sua historia: {mind.story}",
        f"Classe: {JOB_NAMES.get(w.job, f'classe {w.job}')}, nivel de base {w.base_level} "
        f"(experiencia {percent(w.base_exp, w.next_base_exp)}), nivel de classe {w.job_level} "
        f"(experiencia {percent(w.job_exp, w.next_job_exp)}). Zeny: {w.zeny}.",
        f"Seu humor agora: {mind.mood['state']} ({mind.mood['why']})",
        f"Seu objetivo atual: {mind.goal or '(nenhum ainda: escolha um)'}",
        f"Sua vida ate aqui: {mind.stats.get('kills', 0)} monstros derrotados, {mind.stats.get('deaths', 0)} mortes.",
        "Seu diario (mais recente por ultimo):",
        *([f"- {e}" for e in mind.diary[-10:]] or ["- (vazio)"]),
        *mind.knowledge(w.map),
        *travel_map(body.atlas, mind, w),
        f"Voce esta em {w.map}{town_label(w.map)} {w.x},{w.y}, HP {w.hp}/{w.max_hp}.",
        f"Fazendo agora: {body.status()}",
        "Suas rotinas (o que seu corpo sabe fazer sozinho):",
        *body.engine.describe(),
        f"Resultado do ultimo movimento: {w.last_walk_result or 'nenhum'}",
    ]
    players = by_kind.pop("player", [])
    lines.append(f"Jogadores ({len(players)}):")
    lines += [f"- {short_name(u.name)} em {u.x},{u.y} (dist {cells(u.x, u.y, w.x, w.y)})" for u in players] or ["- nenhum"]

    monsters = by_kind.pop("monster", [])
    groups = {}
    for u in monsters:
        groups.setdefault(short_name(u.name) or "?", []).append(u)
    lines.append(f"Monstros ({len(monsters)}):")
    for name, units in groups.items():
        spots = ", ".join(f"{u.x},{u.y} (dist {cells(u.x, u.y, w.x, w.y)})" for u in units[:6])
        lines.append(f"- {name} x{len(units)}: {spots}")
    if not groups:
        lines.append("- nenhum")

    npcs = by_kind.pop("npc", [])
    lines.append(f"NPCs ({len(npcs)}):")
    lines += [f"- {short_name(u.name)} em {u.x},{u.y} (dist {cells(u.x, u.y, w.x, w.y)})" for u in npcs[:25]] or ["- nenhum"]

    portals = by_kind.pop("portal", [])
    if portals:
        lines.append(f"Portais, redemoinhos de luz no chao ({len(portals)}): " + ", ".join(
            f"{short_name(u.name)} em {u.x},{u.y} (dist {cells(u.x, u.y, w.x, w.y)})" for u in portals))
    for kind, units in by_kind.items():  # pets, homunculi, mercenaries, elementals...
        lines.append(f"{kind} ({len(units)}): " + ", ".join(f"{short_name(u.name)} em {u.x},{u.y}" for u in units[:8]))

    items = [(cells(x, y, w.x, w.y), item_names.get(item_id, f"item {item_id}"), amount, x, y)
             for item_id, amount, x, y in w.items.values() if cells(x, y, w.x, w.y) <= config.VIEW_RANGE + 2]
    if items:
        lines.append(f"Itens no chao ({len(items)}): " +
                     ", ".join(f"{n} x{a} em {x},{y}" for _, n, a, x, y in sorted(items)[:10]))

    lines.append(f"Sua mochila ({len(w.inventory)} itens):")
    for i in sorted(w.inventory.values(), key=lambda i: (i.type, i.index)):
        worn = ", vestido" if i.worn else ""
        lines.append(f"- {item_names.get(i.item_id, f'item {i.item_id}')} x{i.amount} "
                     f"({roclient.ITEM_TYPES.get(i.type, 'outro')}{worn})")
    if not w.inventory:
        lines.append("- vazia")
    now = time.time()
    changes = [f"{ITEM_CHANGES.get(what, what)} {item_names.get(item_id, f'item {item_id}')}"
               + (f" x{amount}" if amount > 1 else "") for t, what, item_id, amount in w.item_log
               if now - t < config.ITEM_LOG_WINDOW]
    if changes:
        lines.append("Mudancas recentes na mochila: " + "; ".join(changes[-10:]))

    body.wait_shown = w.npc_wait["since"] if w.npc_wait else None
    if w.npc_wait:
        lines += ["JANELA DE NPC ABERTA:", *describe_wait(w, item_names)]

    chat = [f"[{kind}] {speaker}: {text}" for t, speaker, text, kind in w.chat if now - t < config.CHAT_WINDOW][-12:]
    lines += ["<chat>", *(chat or ["(silencio)"]), "</chat>"]
    speakers = {speaker for t, speaker, _, kind in w.chat if now - t < config.CHAT_WINDOW and kind != "self"}
    notes = mind.about({short_name(u.name) for u in players} | speakers)
    if notes:
        lines.append("O que voce lembra destes jogadores: " + json.dumps(notes, ensure_ascii=False))
    return "\n".join(lines)
