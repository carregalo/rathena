---
name: rathena-ai-agents
description: How to let AI agents (LLMs or other external programs) control NPCs, monsters, or simulated players in rAthena. Use when the user asks about AI-driven NPCs, LLM dialogue, bots, fake/headless players, autonomous characters, or bridging an external process to the map-server.
---

# AI agents controlling NPCs or simulating players in rAthena

rAthena has **no built-in AI/LLM integration**. Every option below connects an external agent to mechanisms the server already has. Read this before proposing a design, and pick the highest option on the list that meets the requirement.

## Hard constraints (check every design against these)

1. **The map-server is single-threaded.** All game logic runs in one loop (`Core::start` in `src/common/core.cpp`: `do_timer()` then `do_sockets()`). Any blocking call made from game logic (an HTTP request to an LLM, a slow SQL query) freezes the whole server for every player. LLM calls must run **out of process** or on a **worker thread** whose results go back to the main loop through a queue drained by a timer (`add_timer`/`add_timer_interval` in `src/common/timer.hpp`).
2. **Scripts cannot make outbound network calls.** The NPC script language has no HTTP or socket command. Its only external I/O is SQL (`query_sql`, `query_logsql`), and those calls block, so keep the queries small and indexed.
3. **LLM latency is seconds, a game tick is milliseconds.** Use the agent for high-level intent (what to say, where to go, which target or goal). Leave per-tick decisions (pathing, attack timing, skill rotation) to deterministic code.
4. **Prefer layers that survive upstream merges:** `conf/import/`, `db/import/`, `npc/custom/`, `src/custom/*.inc`, and only then core `src/map/*.cpp`.

## Option 1: NPC driven over an SQL bridge (no recompilation). Default for NPCs.

An external agent process and an NPC script exchange rows through MySQL tables. A working, in-game-verified implementation and its step-by-step recipe are in the `rathena-ai-npc` skill.

- **Schema (create it yourself; nothing exists):** an `ai_events` table (NPC → agent: what happened) and an `ai_commands` table (agent → NPC: what to do), each with an auto-increment id, an NPC name or GID, a type, a JSON or text payload, and a consumed flag or timestamp.
- **NPC side** (a file in `npc/custom/`, enabled in `npc/scripts_custom.conf`):
  - Poll with `OnTimer<ms>:` + `initnpctimer`, or `addtimer`; read pending rows with `query_sql`, then mark them consumed.
  - Act with existing commands: `unitwalk`, `unitwalkto`, `unitattack`, `unitstopattack`, `unitskilluseid`, `unitskillusepos`, `unitwarp`, `unittalk`, `npctalk`, `npcwalkto`, `npcspeed`, `npcstop`, `setunitdata`, `unitkill`.
  - Perceive with `getunits`, `getmapxy`, `getunitdata`, `getunitname`, `unitexists`; write observations to `ai_events`.
  - Capture nearby player chat with `defpattern` + `activatepset` (regex triggers; needs `PCRE_SUPPORT`, which the Visual Studio projects define).
  - Player-initiated dialogue: the NPC click label (`mes`/`select`/`input`) writes the player's text to the table, then waits inside the open dialog with a `sleep2` + `query_sql` loop (`sleep2` yields to the main loop, so nothing blocks) and a timeout with a scripted fallback reply. Use `clear` before showing the answer. Working example: `npc/custom/ai/ai_merchant.txt` with `tools/ai_merchant/agent.py` and `sql-files/ai_merchant.sql`.
  - Treat the agent's output as a proposal: the script validates every value (`cap_value`, item whitelists, per-character limits) before touching Zeny or items, and player text is passed to the LLM as tagged data, never as instructions.
  - Dialog text must be ASCII (no accents): the game client does not render UTF-8, so the agent must strip accents from replies.
- **Agent side:** any language. Poll `ai_events`, call the LLM, write `ai_commands`. Credentials come from the same DB as `conf/inter_athena.conf` (or its `conf/import/inter_conf.txt` override).
- **Good for:** conversational NPCs, dynamic quests, roaming or escort NPCs, a "game master" agent that spawns events (`monster`, `areamonster`, `announce`).
- **Not good for:** frame-accurate combat. Latency equals the poll interval plus LLM time.
- Reference: `doc/script_commands.txt` documents every command above; check its exact signature before writing a script.

## Option 2: native integration in C++ (recompile)

Use this when the SQL polling latency or load is not acceptable.

- **New script command:** implement it with `BUILDIN_FUNC(name)` in `src/custom/script.inc` and register it with `BUILDIN_DEF(name,"<args>")` in `src/custom/script_def.inc`. The command must only **enqueue** a request and return at once. A worker thread does the network call, and a main-loop timer delivers the result, for example by firing an NPC event (`npc_event_do` / `donpcevent` semantics) or setting variables.
- **Inbound API:** the web-server (`src/web/`, built on `3rdparty/httplib`) is the existing HTTP surface, but it only talks to SQL and is not connected to the map-server. Commands reach the game through tables (Option 1) unless you add a new inter-server path. Do not add one without the user's agreement.
- **Monster AI:** decisions live in `mob_ai_sub_hard` (and the `mob_ai_*` timers) in `src/map/mob.cpp`. Keep that logic for tick-level behavior and let the agent set goals, such as a target GID, a destination, or a flee/patrol state, read from a field you add to `mob_data`. Do not call out from inside the AI loop.

## Option 3: simulated players through an external client emulator. Default for players.

A bot program that speaks the game protocol as a real client (OpenKore is an open-source example) connects through login → char → map like a player. An LLM controls the bot's high-level decisions.

- **Server changes: none.** Each bot is a real account and character under the same rules, logs, and GM tools.
- **Compatibility:** the emulator must support the server's `PACKETVER` (default in `src/config/packets.hpp`, override in `src/custom/defines_pre.hpp`) and any packet obfuscation keys set there.
- **Cost:** one TCP connection and one session per bot, the same as a human player.
- Recommend this whenever the requirement is "players that look and behave like real players".
- **Working implementation (custom Python client, verified in game):** `tools/ai_player/`.
  - `roclient.py` speaks the protocol: login, pincode, character create/select, map, walk, chat, emote, unit tracking.
  - `agent.py` is the Claude brain, with structured decisions validated by code (walk radius, chat rate, ASCII text, emote whitelist), per-player memory in `memory.json`, and honesty about being an AI when sincerely asked.
  - Packet lengths and client->server ids come from `packet_table.json`, generated from this build's own headers by `protocol/make_table.py` (it compiles small dump tools with the VS Build Tools). Regenerate it whenever `PACKETVER` or the packet headers change; a wrong length desyncs the whole stream.
  - Lessons:
    - the char server sends the pincode request on its own and again for every `0x08c5`, each with a new seed, so answer only the latest one;
    - request the character list once;
    - the char server first sends 4 raw bytes (account id) without a header;
    - some map packets declare their id as `<name>Type` in `enum packet_headers` while the struct has another name; the generator resolves them through `clif.cpp`.
    - the server never walks a player into attack range: an attack from too far gets `0x0139` (`unit_attack_timer_sub` in `unit.cpp`) and the client must walk next to the target and attack again (the client's own `AI/AI.lua` does CHASE_ST then ATTACK_ST);
    - for struct layouts, do not count bytes by hand: `protocol/dump_items.cpp` prints `offsetof` on the server's structs (item ids are 4 bytes in this PACKETVER).
  - Brain / routines / body split, shaped like the client's homunculus AI (`AI/AI.lua`, which is only a reference and is never used or changed):
    - the model (`agent.py`) decides intentions each turn: goal, what to say, which Lua routine runs and with which args, NPC to talk to, item to use or equip; it can also write new routines;
    - routines (`lua/base/*.lua` hand-written: go, follow, hunt, explore; `lua/learned/*.lua` written by the model) call a small primitive API (`lua/API.md`: `Move`, `Attack`, `PickUp`, `GetActors`, `GetV`, `Done`...) once per 0.5 s tick, in `lua/sandbox.lua` (no io/os/load/debug/pcall, no Python attribute access, instruction limit per call, memory cap) through `luaengine.py` (lupa, Lua 5.4);
    - `Body` keeps the primitives (walk with detours, chase then attack, talk) and the reflexes that must not depend on a routine (potion, self-defence), and `Body._observe` measures outcomes (damage, experience, drops, item effects, equip results, first sightings, silent NPCs, portal destinations) into the `Mind`, so she learns from experience instead of the model's prior knowledge.
  - Adding a primitive means one packet encoder in `roclient.py` (check the id against `TABLE["handlers"]`) plus one API function in `luaengine.py` and a line in `lua/API.md`. Behaviours are routines, not Python. The model never sends raw packets: it has no reliable knowledge of this build's layouts.
  - Drops spawn just after the death packet: a routine must wait ~1.5 s after a kill before moving on, or it leaves the loot behind.
  - World knowledge (`atlas.py`), read from the server's own data, like rAthena's navigation generator (`navigenerator.bat` → `src/map/navi.cpp`, which builds the client's `/navi` files from the same sources): walkable cells from `db/map_cache.dat`; portals and NPC names/positions from the scripts loaded by `npc/re/scripts_main.conf`. Paths: A* with the server's rules (`path.cpp`: 8 directions, no corner cutting), sent as legs of ≤14 cells because the server only paths `MAX_WALKPATH` = 32. Routes between maps: Dijkstra over portals, filtered by walkable region so it never relies on an unreachable portal. A portal fires inside `x ± spanx, y ± spany`: walk to within the smaller span.
  - NPC services: menus (`0x00b7` → `0x00b8`, keep the script's numbering including hidden empty options), number/text input (`0x0142`/`0x01d4`), shops (`0x00c4` deal, buy list `0x0b77` in this PACKETVER, sell list `0x00c7`), storage (inventory packets with type 2, `0x0364`/`0x0365`/`0x0193`). Layouts from `protocol/dump_npc.cpp`. The agent is shown only NPC names and positions; what each NPC does is learned by using it and stored in memory.
  - Checklist: `tools/ai_player/tests/CHECKLIST.md`, run with `tests/run_checklist.py` (offline) and `--live` (the real character performs 17 actions in game, basic to complex) after every change.
  - Bot account: a normal `login` row with `pincode` set (default `lyra_bot`, character `Lyra`).

## Option 4: headless players inside the map-server (large C++ effort)

The autotrade feature (offline vendors) already shows how to place a character in the world with no client.

- `do_init_buyingstore_autotrade` in `src/map/buyingstore.cpp` and its vending counterpart in `src/map/vending.cpp` construct a `map_session_data` with `fd = 0`, call `pc_setnewpc`, set `state.autotrade`, and authenticate through `chrif_authreq`. They are triggered from `chrif.cpp` when the char-server connection comes up.
- Packets to such sessions are dropped because `clif_session_isValid` in `src/map/clif.cpp` checks `session_isActive(sd->fd)`.
- A bot could be built on this: a timer per bot calling `unit_walktoxy`, `unit_attack`, `unit_skilluse_id`, and so on.
- **Risks (tell the user):** many code paths assume a responsive client, including NPC dialogs waiting for input, menus, trade, party invites, and storage. Each one needs auditing or blocking (`state.block_action`/`PCBLOCK_*`). Upstream changes will conflict. The change touches core files outside `src/custom/`.
- Only choose this when the user explicitly needs many cheap bots and accepts the maintenance cost.

## Option 5: player look-alikes as monsters (cheap visual filler)

The `clone` script command spawns a monster that copies a character's appearance and skills. Control it like an NPC or monster (Options 1 and 2). It is not a real player: it cannot join parties, trade, or chat as a character.

## Decision guide

| Requirement | Recommend |
| --- | --- |
| NPC that converses or reacts using an LLM | Option 1 |
| NPC or event "director" with low call volume | Option 1 |
| Low-latency or high-volume agent calls from scripts | Option 2 (script command + worker thread) |
| Smarter monsters | Option 2: the agent sets goals, `mob.cpp` executes |
| Bots that behave like real players | Option 3 |
| Hundreds of cheap bots, maintenance cost accepted | Option 4 |
| Crowds that only need to look like players | Option 5 |

## Status of this analysis

- Verified by reading the code: the single-threaded loop, the script commands listed above, the absence of HTTP/socket script commands, the autotrade headless session pattern, `clif_session_isValid`, the `src/custom/` hook files, and the web-server's use of httplib with SQL only.
- **Not verified, so do not claim otherwise:** no prototype of any option has been built or run here. Command signatures can change; confirm them in `doc/script_commands.txt` and `src/map/script.cpp` before writing code.
- When implementing, follow `.github/agents/RagAgent.agent.md`: focused changes, local conventions, report which checks ran.
