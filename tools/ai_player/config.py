"""Lyra's settings: the game account (environment or local.env) and the tuning constants.

Other modules read these as config.NAME at run time, so tests can change them in one place."""
import os

import roclient

HERE = os.path.dirname(os.path.abspath(__file__))


def load_local_env(path=os.path.join(HERE, "local.env")):
    """KEY=VALUE lines from local.env into the environment, without overriding what is already set."""
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())


load_local_env()
MODEL = os.environ.get("RATHENA_AI_MODEL", "claude-opus-5-5")
HOST = os.environ.get("AI_PLAYER_HOST", "127.0.0.1")
USER = os.environ.get("AI_PLAYER_USER", "")
PASSWORD = os.environ.get("AI_PLAYER_PASS", "")
PIN = os.environ.get("AI_PLAYER_PIN", "")
NAME = os.environ.get("AI_PLAYER_NAME", "Lyra")
SEX = os.environ.get("AI_PLAYER_SEX", "F")

MEMORY_FILE = os.path.join(HERE, "memory.json")
ITEM_DB_GLOB = os.path.join(HERE, "..", "..", "db", "re", "item_db_*.yml")
VIEW_RANGE = 14           # battle_config area_size: the server sends every unit within this square radius
MIN_DECISION_GAP = 1.5    # seconds between two model calls
MAP_SETTLE = 2.5          # seconds to wait after entering a map before deciding
IDLE_WITH_PLAYERS = (20, 35)
IDLE_ALONE = (15, 30)     # alone she takes the initiative more often: nobody else gives her reasons to act
DEFEND_WINDOW = 3         # seconds a hit on her (or the followed player) makes the attacker her target
OUTCOME_DELAY = 1.5       # seconds to wait for experience, drops and item effects to arrive
SILENT_NPC_AFTER = 3      # seconds after a click with no dialog before telling her nothing happened
GO_TIMEOUT = 20           # seconds before giving up on reaching a destination (plus 0.4 s per planned cell)
WALK_REPEAT = 0.3         # seconds between walk requests while walking, like a held mouse button
TALK_TIMEOUT = 60         # seconds to reach an NPC in sight and click it
NPC_WAIT_TIMEOUT = 120    # seconds an NPC window may wait for her answer before she closes it
CHAT_WINDOW = 300         # seconds of chat history shown to the model
TICK = 0.25               # seconds between two runs of the body loop (reflexes and the routine's Tick)
HUNT_STOP_HP = 0.3        # stop a fighting routine below this fraction of max HP (once no healing item is left)
POTION_AT = 0.5           # drink a healing item below this fraction of max HP, like a player's reflex
POTION_GAP = 1.0          # seconds between two healing items
HEALING = 0               # client item type of healing items (roclient.ITEM_TYPES)
ITEM_LOG_WINDOW = 90      # seconds of inventory changes shown to the model
DEFEND_GIVE_UP = 15       # seconds without landing a hit before the self-defence reflex gives up
ATTACK_RANGE = 1          # melee: Novices and every first class Lyra can aim for
ATTACK_REFRESH = 2        # re-send the attack this often while next to the target (cheap, and recovers a dropped one)
EMOTES = ["none"] + sorted(roclient.EMOTES)
MOODS = ["animada", "feliz", "curiosa", "tranquila", "entediada", "cansada", "irritada", "triste", "assustada"]
