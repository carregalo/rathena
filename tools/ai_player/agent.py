"""AI-controlled player for rAthena: Claude decides, roclient.py acts in the game.

The bot logs in as a normal character (account and pincode below) and asks Claude what to do when
someone talks, something notable happens, or it has been idle for a while. Claude picks intentions
(say something, talk to an NPC, use an item, remember something) and which Lua routine her body runs
between turns (lua/base: go, follow, hunt, explore; lua/learned: routines Claude wrote itself), so the
bot does not wait for the model between steps or between monsters. Reflexes (potions, self-defence)
stay in code, and the code validates every action (chat length and rate, emote whitelist, HP floor).

This module is the brain loop (decide, act, brain, main). The rest: config.py (account and constants),
persona.py (story, prompt, decision schema), observation.py (what she sees each turn), mind.py (memory),
body.py (primitives, reflexes, outcomes), npc.py (NPC windows), gamedata.py (item and class names),
luaengine.py + lua/ (routines), atlas.py (maps, portals, NPCs), roclient.py (the game protocol).

Run:  pip install -r requirements.txt
      python agent.py
Environment: ANTHROPIC_API_KEY (or an `ant auth login` profile), RATHENA_AI_MODEL,
AI_PLAYER_HOST / _USER / _PASS / _PIN / _NAME / _SEX. The account settings can also live in local.env
(KEY=VALUE per line, not committed); the real environment wins over the file.
"""
import asyncio
import json
import logging
import os
import random
import time

import anthropic

import atlas
import config
import roclient
from body import Body
from gamedata import JOB_NAMES, find_item, load_item_names, to_game_text
from luaengine import short_name
from mind import Mind
from npc import answer_npc, note_npc_service
from observation import observation
from persona import DECISION_SCHEMA, SYSTEM_PROMPT

log = logging.getLogger("ai_player")


async def decide(api, prompt):
    response = await api.beta.messages.create(
        model=config.MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"refusal: {response.stop_details}")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def act(client, mind, body, item_names, d):
    w = client.world
    for field_name, worn, action in (("use_item", None, body.use_item), ("equip_item", False, client.equip),
                                     ("unequip_item", True, client.unequip)):
        if d[field_name].strip():
            item = find_item(w, item_names, d[field_name], worn)
            if item:
                action(item.index)
            else:
                log.info("%s: no %r in the inventory", field_name, d[field_name])
    said = False
    text = to_game_text(d["say"])
    if text:
        said = client.say(text)
    engine = body.engine
    if d["new_routine_code"].strip():
        err = engine.write(d["new_routine_name"], d["new_routine_purpose"], d["new_routine_code"])
        if err:
            client.events.put_nowait(("routine_error", f"{d['new_routine_name']}: {err}"))
    if d["routine"].strip():
        err = engine.start(d["routine"], d["routine_args"])
        if err:
            client.events.put_nowait(("routine_error", f"{d['routine']}: {err}"))
    else:
        engine.stop()
    body.set_talk(d["talk_to_npc"])
    reply_result = ""
    if w.npc_wait and w.npc_wait["since"] == body.wait_shown:  # answer only the window she was shown
        reply_result = answer_npc(client, body, d["npc_reply"])
        if w.npc_wait:  # still open: the answer did not fit, or the storage stays open for more
            client.events.put_nowait(("npc_reply", reply_result))
    mind.set_goal(d["goal"])
    if d["emote"] != "none":
        client.emote(d["emote"])
    mind.remember(d["remember_player"], d["remember_note"])
    mind.feel(d["mood"], d["mood_reason"])
    mind.write_diary(d["diary_entry"])
    mind.learn(d["learned"])
    mind.rewrite_story(d["story_update"])
    log.info("[%s] %s | say=%r routine=%r args=%s wrote=%r talk=%r npc=%r use=%r equip=%r goal=%r emote=%s "
             "learned=%r story=%s", mind.mood["state"], d["thought"][:100], text if said else "",
             engine.active["name"] if engine.active else "", d["routine_args"][:80],
             d["new_routine_name"] if d["new_routine_code"].strip() else "", body.talk, reply_result, d["use_item"],
             d["equip_item"], mind.goal[:60], d["emote"], d["learned"][:60],
             "updated" if d["story_update"].strip() else "-")


REASONS = {
    "chat": "{} falou no chat",
    "whisper": "{} sussurrou para voce",
    "map": "voce chegou em {}",
    "hp_low": "seu HP ficou baixo e voce parou a rotina {}",
    "respawn": "voce morreu e renasceu no ponto de retorno (rotina que rodava: {})",
    "routine_done": "uma rotina terminou: {}",
    "routine_error": "uma rotina falhou e foi parada (corrija ou escolha outra): {}",
    "routine_note": "uma rotina te avisou: {}",
    "npc_wait": "{} espera sua resposta (veja JANELA DE NPC ABERTA)",
    "npc_reply": "sua resposta ao NPC: {}",
    "shop_result": "resultado na loja: {}",
    "npc_missing": "voce queria conversar com {}, mas nao o encontrou por perto",
    "attacked": "um {} atacou voce (ou quem voce segue) e voce esta revidando",
    "discovery": "voce viu algo novo: {}",
    "npc_silent": "voce clicou em {} e nada aconteceu: nao respondeu nada",
    "item_effect": "voce experimentou um item: {}",
    "idle": "nada aconteceu faz um tempo: siga o seu objetivo, ou escolha um novo e experimente algo",
}
MILESTONES = {"level_up", "job_change"}


async def on_event(kind, who, client, mind, body, item_names):
    """Applies what an event means for her (memory, respawn, map arrival) and returns it in words for the
    turn's reason. Every event goes through here, the one that woke the brain and the ones folded into
    the same turn alike, so none loses its effect."""
    w = client.world
    if kind == "died":
        routine = body.engine.status()
        body.engine.stop()
        mind.count("deaths")
        mind.write_diary(f"Morri em {w.map} {w.x},{w.y}" + (f" ({routine})" if routine else ""))
        mind.feel("assustada", "acabei de morrer")
        client.respawn()
        return REASONS["respawn"].format(routine)
    if kind == "hp_low":
        mind.feel("assustada", f"meu HP ficou baixo na rotina {who}")
    if kind == "level_up":
        field_name, level = who
        label = "nivel de base" if field_name == "base_level" else "nivel de classe"
        mind.write_diary(f"Subi para o {label} {level}!")
        return f"voce acabou de subir para o {label} {level}"
    if kind == "job_change":
        new_job = JOB_NAMES.get(who[1], f"classe {who[1]}")
        mind.write_diary(f"Me tornei {new_job}!")
        return f"voce acabou de mudar de classe: agora e {new_job}"
    if kind == "npc_dialog":
        npc, lines = who
        mind.npc_said(npc, lines)
        return f"voce conversou com {short_name(npc)}, que disse: " + " ".join(lines)[:600]
    if kind == "npc_wait":
        npc, lines = who
        if lines:
            mind.npc_said(npc, lines)
        note_npc_service(mind, w, item_names)
        said = (", depois de dizer: " + " ".join(lines)[:500]) if lines else ""
        return f"{short_name(npc)} espera sua resposta{said} (veja JANELA DE NPC ABERTA)"
    if kind == "map":
        await asyncio.sleep(config.MAP_SETTLE)  # status and units in sight arrive right after a map change
        body.dest = None
        if w.last_warp:
            mind.learn("O portal em {} {},{} leva para {}".format(*w.last_warp, who))
        mind.visit(who)
    return REASONS.get(kind, REASONS["idle"]).format(who)


async def brain(api, client, mind, body, item_names):
    last_call = 0.0
    while True:
        players_near = any(u.kind == "player" for u in client.world.units.values())
        idle = random.uniform(*(config.IDLE_WITH_PLAYERS if players_near else config.IDLE_ALONE))
        try:
            kind, who = await asyncio.wait_for(client.events.get(), idle)
        except asyncio.TimeoutError:
            kind, who = "idle", ""
        reason = await on_event(kind, who, client, mind, body, item_names)
        milestone = kind in MILESTONES
        await asyncio.sleep(max(0.0, config.MIN_DECISION_GAP - (time.monotonic() - last_call)))
        while not client.events.empty():  # fold what arrived meanwhile into this turn
            kind, who = client.events.get_nowait()
            extra = await on_event(kind, who, client, mind, body, item_names)
            if len(reason) < 900:
                reason += "; e tambem " + extra
            milestone = milestone or kind in MILESTONES
        last_call = time.monotonic()
        try:
            prompt = observation(client, mind, body, item_names, reason, milestone)
            with open(os.path.join(config.HERE, "last_prompt.txt"), "w", encoding="utf-8") as f:
                f.write(prompt)  # what the model saw this turn, for debugging
            act(client, mind, body, item_names, await decide(api, prompt))
        except (anthropic.APIError, ValueError, KeyError, StopIteration, RuntimeError) as e:
            log.warning("decision failed: %s", e)
        except Exception:  # a bug in one turn must not take the character offline
            log.exception("unexpected error in this turn")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (config.USER and config.PASSWORD and config.PIN):
        raise SystemExit("set AI_PLAYER_USER, AI_PLAYER_PASS and AI_PLAYER_PIN (environment or local.env)")
    api = anthropic.AsyncAnthropic()
    mind = Mind(config.MEMORY_FILE)
    item_names = load_item_names()
    world_atlas = atlas.Atlas()
    log.info("atlas: %d maps, %d portals, %d NPCs", len(world_atlas.cache_index),
             sum(map(len, world_atlas.warps.values())), sum(map(len, world_atlas.npcs.values())))
    log.info("loaded %d item names", len(item_names))
    while True:
        client = roclient.Client(config.HOST, config.USER, config.PASSWORD, config.PIN, config.NAME, sex=config.SEX)
        try:
            await client.connect()
            mind.visit(client.world.map)
            log.info("%s is online at %s %d,%d as %s lv %d/%d (model %s)", config.NAME, client.world.map, client.world.x,
                     client.world.y, JOB_NAMES.get(client.world.job, client.world.job), client.world.base_level,
                     client.world.job_level, config.MODEL)
            body = Body(client, mind, item_names, world_atlas)
            tasks = {asyncio.create_task(client.run()), asyncio.create_task(body.run()),
                     asyncio.create_task(brain(api, client, mind, body, item_names))}
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        except (ConnectionError, OSError) as e:
            log.error("disconnected: %s; reconnecting in 10 s", e)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
