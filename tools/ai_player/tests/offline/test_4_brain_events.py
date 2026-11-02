"""Offline test of agent.on_event: every event has its effect, even one folded into another event's turn."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import agent  # noqa: E402
import config  # noqa: E402
import roclient  # noqa: E402
from body import Body  # noqa: E402
from mind import Mind  # noqa: E402

config.MAP_SETTLE = 0


class FakeClient:
    def __init__(self):
        self.world = roclient.World(name="Lyra", map="prt_fild08", x=170, y=375, account_id=1000)
        self.events = asyncio.Queue()
        self.respawned = False

    def respawn(self):
        self.respawned = True


async def main():
    c = FakeClient()
    mind = Mind(os.path.join(tempfile.mkdtemp(), "m.json"))
    body = Body(c, mind, {})
    checks = {}

    reason = await agent.on_event("chat", "teste", c, mind, body, {})
    checks["chat reason"] = reason == "teste falou no chat"

    # the events that used to lose their effect when they came second in a turn
    reason = await agent.on_event("died", "", c, mind, body, {})
    checks["died: respawn + diary"] = c.respawned and mind.stats["deaths"] == 1 and "Morri em prt_fild08" in mind.diary[-1]
    c.world.last_warp, c.world.map = ("prt_fild08", 170, 378), "prontera"
    reason = await agent.on_event("map", "prontera", c, mind, body, {})
    checks["map: visit + portal learned"] = "prontera" in mind.world["places"] and \
        "O portal em prt_fild08 170,378 leva para prontera" in mind.world["facts"]
    reason = await agent.on_event("level_up", ("base_level", 3), c, mind, body, {})
    checks["level up: diary"] = mind.diary[-1].endswith("Subi para o nivel de base 3!") and "nivel de base 3" in reason
    reason = await agent.on_event("idle", "", c, mind, body, {})
    checks["idle reason"] = reason == agent.REASONS["idle"]

    print("\n".join(f"{'ok  ' if v else 'FAIL'} {k}" for k, v in checks.items()))
    print("PASS" if all(checks.values()) else "FAIL")


asyncio.run(main())
