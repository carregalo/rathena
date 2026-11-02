"""Knowledge of the world's maps for the agent, read from the server's own data:

- db/map_cache.dat: walkable cells of every map (the same cache the map-server loads), for paths;
- the NPC scripts loaded by npc/re/scripts_main.conf: portals (warps), and NPCs with what they offer,
  tagged from the script's folder and the commands it runs (openstorage, savepoint, callshop, ...).

Paths: A* over the cells with the server's movement rules (8 directions, a diagonal step needs both
orthogonal cells free; path.cpp). Routes between maps: Dijkstra over portals, using the walkable region
of each portal so a route never relies on a portal that cannot be reached from where she stands. The
regions are computed once in a background thread and cached in .atlas_cache.json.
"""
import array
import heapq
import json
import logging
import os
import re
import struct
import threading
import zlib
from collections import defaultdict, deque
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
CACHE_FILE = os.path.join(HERE, ".atlas_cache.json")
MAP_CACHES = ["db/map_cache.dat", "db/re/map_cache.dat", "db/import/map_cache.dat"]
NPC_ROOT_CONF = "npc/re/scripts_main.conf"
WALKABLE_GAT = {0, 2, 3, 4, 6}   # map_gat2cell in src/map/map.cpp: 1 = wall, 5 = cliff
INVISIBLE = {"-1", "FAKE_NPC", "111", "HIDDEN_NPC", "139", "HIDDEN_WARP_NPC"}
PORTAL_SPRITES = {"45", "WARPNPC", "HIDDEN_WARP_NPC", "139"}
HEADER = re.compile(r"^([A-Za-z0-9_@\-]+),(\d+),(\d+)(?:,(\d+))?\t(warp2?|script|shop|cashshop|itemshop|pointshop|"
                    r"trader|marketshop|duplicate\(([^)]*)\))\t([^\t]+)\t(.*)$")
COMMENT = re.compile(r"/\*.*?\*/")
SCRIPT_WARP = re.compile(r'\bwarp\s+"([A-Za-z0-9_@\-]+)"\s*,\s*(\d+)\s*,\s*(\d+)')
MAIN_TOWNS = {
    "prontera": "capital do reino", "izlude": "porto perto da capital", "geffen": "cidade dos magos",
    "payon": "cidade das montanhas", "morocc": "cidade do deserto", "alberta": "cidade portuaria dos mercadores",
    "aldebaran": "cidade dos relogios", "comodo": "cidade da praia e das festas", "yuno": "cidade dos sabios",
    "umbala": "aldeia da arvore", "niflheim": "terra dos mortos", "louyang": "cidade oriental",
    "amatsu": "cidade das cerejeiras", "gonryun": "cidade das nuvens", "ayothaya": "cidade dos templos",
    "lighthalzen": "cidade das corporacoes", "einbroch": "cidade das fabricas", "einbech": "cidade mineira",
    "hugel": "vila dos cacadores", "rachel": "cidade do templo de Freya", "veins": "cidade do canyon",
    "moscovia": "reino das neves", "brasilis": "terra das cachoeiras", "dewata": "ilha tropical",
    "malaya": "porto de Malaya", "mora": "vila dos Raffles", "eclage": "cidade das fadas",
}
LEG = 22                       # cells per walk request: plus the few still ahead when it is sent, stays under
                               # the server's MAX_WALKPATH of 32 (path.hpp)
MAX_EXPANSIONS = 400000

log = logging.getLogger("ai_player")


@dataclass
class Warp:
    map: str
    x: int
    y: int
    sx: int
    sy: int
    to_map: str
    to_x: int
    to_y: int
    name: str


@dataclass
class Npc:
    name: str
    map: str
    x: int
    y: int


def display_name(name):
    return name.split("::", 1)[0].split("#", 1)[0].strip()


class Atlas:
    def __init__(self, root=ROOT):
        self.root = root
        self.cache_index = {}            # map -> (bytes buffer, offset, xs, ys, length)
        self.grids = {}                  # map -> (xs, ys, bytearray walkable); a few kept
        self.labels = {}                 # map -> (xs, ys, array of region ids); a few kept
        self.warps = defaultdict(list)   # map -> [Warp]
        self.npcs = defaultdict(list)    # map -> [Npc]
        self.regions = {}                # map -> {"w<i>": region, "d<x>,<y>": region, "n<i>": region}
        self.ready = False
        self._lock = threading.RLock()
        self._load_map_cache()
        self._load_scripts()
        self._load_regions()

    # ------------------------------------------------------------------ loading

    def _load_map_cache(self):
        for rel in MAP_CACHES:
            path = os.path.join(self.root, rel)
            if not os.path.exists(path):
                continue
            buf = open(path, "rb").read()
            if len(buf) < 8:
                continue
            count = struct.unpack_from("<H", buf, 4)[0]
            off = 8  # map_cache_main_header: uint32 + uint16, padded to 8
            for _ in range(count):
                name = buf[off:off + 12].split(b"\0", 1)[0].decode("latin1")
                xs, ys, length = struct.unpack_from("<hhi", buf, off + 12)
                self.cache_index[name] = (buf, off + 20, xs, ys, length)
                off += 20 + length

    def _conf_files(self, conf, seen):
        scripts = []
        path = os.path.join(self.root, conf)
        if conf in seen or not os.path.exists(path):
            return scripts
        seen.add(conf)
        for line in open(path, encoding="latin1"):
            line = line.split("//", 1)[0].strip()
            if line.startswith("npc:"):
                scripts.append(line[4:].strip())
            elif line.startswith("import:"):
                scripts += self._conf_files(line[7:].strip(), seen)
            elif line.startswith("delnpc:"):
                gone = line[7:].strip()
                scripts = [s for s in scripts if s != gone]
        return scripts

    def _load_scripts(self):
        for rel in self._conf_files(NPC_ROOT_CONF, set()):
            path = os.path.join(self.root, rel)
            if not os.path.exists(path):
                continue
            lines = open(path, encoding="latin1").read().splitlines()
            i = 0
            while i < len(lines):
                m = HEADER.match(lines[i])
                i += 1
                if not m:
                    continue
                mapname, x, y, _, kind, _, name, rest = m.groups()
                x, y = int(x), int(y)
                rest = COMMENT.sub("", rest).split("//", 1)[0].strip()
                if kind in ("warp", "warp2"):
                    p = [v.strip() for v in rest.split(",")]
                    if len(p) >= 5 and p[0].isdigit() and p[3].isdigit() and p[4].isdigit():
                        self.warps[mapname].append(Warp(mapname, x, y, int(p[0]), int(p[1]), p[2],
                                                        int(p[3]), int(p[4]), name))
                    continue
                body = []
                if kind == "script":
                    while i < len(lines) and not HEADER.match(lines[i]):
                        body.append(lines[i])
                        i += 1
                sprite = rest.split(",", 1)[0].strip()
                if sprite in PORTAL_SPRITES:  # scripted portal: keep the short, unconditional ones
                    text = "\n".join(body)
                    dest = SCRIPT_WARP.findall(text)
                    if kind == "script" and len(dest) == 1 and len(body) <= 8 and " if " not in f" {text} ":
                        span = [v.strip() for v in rest.split(",")]
                        sx, sy = (int(span[1]), int(span[2])) if len(span) >= 3 and span[1].isdigit() else (1, 1)
                        self.warps[mapname].append(Warp(mapname, x, y, sx, sy, dest[0][0], int(dest[0][1]),
                                                        int(dest[0][2]), display_name(name)))
                    continue
                if mapname == "-" or sprite in INVISIBLE or not display_name(name):
                    continue
                self.npcs[mapname].append(Npc(display_name(name), mapname, x, y))

    # ------------------------------------------------------------------ cells

    def grid(self, m):
        if m in self.grids:
            return self.grids[m]
        entry = self.cache_index.get(m)
        if entry is None:
            return None
        buf, off, xs, ys, length = entry
        cells = zlib.decompress(buf[off:off + length])
        walk = bytearray(1 if c in WALKABLE_GAT else 0 for c in cells)
        grid = (xs, ys, walk)
        with self._lock:  # the regions thread uses the same small caches
            if len(self.grids) > 6:
                self.grids.pop(next(iter(self.grids)))
            self.grids[m] = grid
        return grid

    def walkable(self, m, x, y):
        g = self.grid(m)
        if g is None:
            return True
        xs, ys, walk = g
        return 0 <= x < xs and 0 <= y < ys and walk[x + y * xs] == 1

    def nearest_walkable(self, m, x, y, radius=3):
        best = None
        for r in range(radius + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) == r and self.walkable(m, x + dx, y + dy):
                        d = abs(dx) + abs(dy)
                        if best is None or d < best[0]:
                            best = (d, x + dx, y + dy)
            if best:
                return best[1], best[2]
        return None

    def region_labels(self, m):
        """4-connected walkable regions (equivalent to the server's moves, whose diagonals need both sides free)."""
        if m in self.labels:
            return self.labels[m]
        g = self.grid(m)
        if g is None:
            return None
        xs, ys, walk = g
        lab = array.array("i", [0]) * (xs * ys)
        region = 0
        for start in range(xs * ys):
            if walk[start] and not lab[start]:
                region += 1
                lab[start] = region
                queue = deque([start])
                while queue:
                    c = queue.popleft()
                    x = c % xs
                    for n in (c - 1 if x > 0 else -1, c + 1 if x < xs - 1 else -1, c - xs, c + xs):
                        if 0 <= n < xs * ys and walk[n] and not lab[n]:
                            lab[n] = region
                            queue.append(n)
        labels = (xs, ys, lab)
        with self._lock:
            if len(self.labels) > 3:
                self.labels.pop(next(iter(self.labels)))
            self.labels[m] = labels
        return labels

    def region_at(self, m, x, y):
        info = self.region_labels(m)
        if info is None:
            return None
        spot = self.nearest_walkable(m, x, y)
        if spot is None:
            return None
        xs, _, lab = info
        return lab[spot[0] + spot[1] * xs]

    # ------------------------------------------------------------------ paths

    def path(self, m, start, goal, span=0):
        """A* from start to any walkable cell within span of goal; list of (x, y) after start, or None."""
        g = self.grid(m)
        if g is None:
            return None
        xs, ys, walk = g
        sx, sy = start
        gx, gy = goal
        goals = {(x, y) for x in range(gx - span, gx + span + 1) for y in range(gy - span, gy + span + 1)
                 if 0 <= x < xs and 0 <= y < ys and walk[x + y * xs]}
        if not goals:
            near = self.nearest_walkable(m, gx, gy, 4)
            if near is None:
                return None
            goals = {near}
            gx, gy = near
        if (sx, sy) in goals:
            return []
        if not (0 <= sx < xs and 0 <= sy < ys):
            return None

        def h(x, y):
            dx, dy = abs(x - gx), abs(y - gy)
            return 10 * max(dx, dy) + 4 * min(dx, dy) - 10 * span

        best = {(sx, sy): 0}
        came = {}
        heap = [(h(sx, sy), 0, sx, sy)]
        expansions = 0
        while heap:
            _, cost, x, y = heapq.heappop(heap)
            if (x, y) in goals:
                out = []
                while (x, y) != (sx, sy):
                    out.append((x, y))
                    x, y = came[(x, y)]
                return out[::-1]
            if cost > best.get((x, y), 1 << 30):
                continue
            expansions += 1
            if expansions > MAX_EXPANSIONS:
                return None
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < xs and 0 <= ny < ys) or not walk[nx + ny * xs]:
                    continue
                if dx and dy and not (walk[nx + y * xs] and walk[x + ny * xs]):
                    continue  # the server forbids cutting a corner
                nc = cost + (14 if dx and dy else 10)
                if nc < best.get((nx, ny), 1 << 30):
                    best[(nx, ny)] = nc
                    came[(nx, ny)] = (x, y)
                    heapq.heappush(heap, (nc + h(nx, ny), nc, nx, ny))
        return None

    # ------------------------------------------------------------------ regions of portals and NPCs

    def _load_regions(self):
        try:
            data = json.load(open(CACHE_FILE, encoding="utf-8"))
            if data.get("signature") == self._signature():
                self.regions, self.ready = data["regions"], True
                return
        except (OSError, ValueError, KeyError):
            pass
        threading.Thread(target=self._compute_regions, name="atlas-regions", daemon=True).start()

    def _signature(self):
        n_warps = sum(len(v) for v in self.warps.values())
        n_npcs = sum(len(v) for v in self.npcs.values())
        sizes = [os.path.getsize(os.path.join(self.root, p)) for p in MAP_CACHES if os.path.exists(os.path.join(self.root, p))]
        return f"{n_warps}:{n_npcs}:{sizes}"

    def _compute_regions(self):
        dests = defaultdict(set)
        for ws in self.warps.values():
            for w in ws:
                dests[w.to_map].add((w.to_x, w.to_y))
        maps = set(self.warps) | set(dests) | set(self.npcs)
        regions = {}
        for m in sorted(maps):
            if m not in self.cache_index:
                continue
            r = {}
            for i, w in enumerate(self.warps.get(m, [])):
                r[f"w{i}"] = self._area_region(m, w.x, w.y, max(w.sx, 1), max(w.sy, 1))
            for x, y in dests.get(m, ()):
                r[f"d{x},{y}"] = self.region_at(m, x, y)
            for i, n in enumerate(self.npcs.get(m, [])):
                r[f"n{i}"] = self.region_at(m, n.x, n.y)
            regions[m] = r
            with self._lock:
                self.labels.pop(m, None)
                self.grids.pop(m, None)
        with self._lock:
            self.regions, self.ready = regions, True
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"signature": self._signature(), "regions": regions}, f)
        except OSError:
            pass
        log.info("atlas: regions of %d maps ready", len(regions))

    def _area_region(self, m, x, y, sx, sy):
        info = self.region_labels(m)
        if info is None:
            return None
        xs, ys, lab = info
        for r in range(max(sx, sy) + 2):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    cx, cy = x + dx, y + dy
                    if 0 <= cx < xs and 0 <= cy < ys and lab[cx + cy * xs]:
                        return lab[cx + cy * xs]
        return None

    def _region(self, m, key):
        return self.regions.get(m, {}).get(key)

    # ------------------------------------------------------------------ routes between maps

    def route(self, src_map, sx, sy, dst_map, dst=None, max_maps=2000):
        """Portals to take from (src_map, sx, sy) to dst_map (and the region of dst there, if given):
        [{"map", "x", "y", "span", "to"} ...], ending with {"map": dst_map, "x", "y"}; None if no route."""
        start_region = self.region_at(src_map, sx, sy)
        target_region = None
        if dst is not None and dst_map == src_map:
            target_region = self.region_at(dst_map, *dst)
        elif dst is not None:
            key = next((f"n{i}" for i, n in enumerate(self.npcs.get(dst_map, [])) if (n.x, n.y) == tuple(dst)), None)
            target_region = self._region(dst_map, key) if key else None
        start = (src_map, sx, sy, start_region)
        dist = {start: 0}
        prev = {}
        heap = [(0, 0, start)]
        counter = 0
        while heap:
            cost, _, node = heapq.heappop(heap)
            m, x, y, reg = node
            if cost > dist.get(node, 1 << 30):
                continue
            if m == dst_map and (target_region is None or reg is None or reg == target_region):
                steps = [{"map": dst_map, "x": dst[0] if dst else x, "y": dst[1] if dst else y}]
                while node in prev:
                    node, w = prev[node]
                    # the portal fires inside x +- sx, y +- sy: a square of the smaller side is always inside it
                    steps.append({"map": w.map, "x": w.x, "y": w.y, "span": min(w.sx, w.sy), "to": w.to_map})
                return steps[::-1]
            counter += 1
            if counter > max_maps * 20:
                break
            for i, w in enumerate(self.warps.get(m, [])):
                wr = self._region(m, f"w{i}")
                if reg is not None and wr is not None and wr != reg:
                    continue  # that portal is on a part of the map she cannot walk to from here
                if w.to_map not in self.cache_index:
                    continue
                walk = max(abs(w.x - x), abs(w.y - y))
                nxt = (w.to_map, w.to_x, w.to_y, self._region(w.to_map, f"d{w.to_x},{w.to_y}"))
                nc = cost + walk + 30  # each portal costs a little: prefer fewer maps
                if nc < dist.get(nxt, 1 << 30):
                    dist[nxt] = nc
                    prev[nxt] = (node, w)
                    counter += 1
                    heapq.heappush(heap, (nc, counter, nxt))
        return None

    # ------------------------------------------------------------------ NPC knowledge

    def find_npcs(self, query, here=None, limit=8, pos=None):
        """NPCs whose name contains query (case-insensitive), nearest maps first (portals to cross), exact names first."""
        q = query.strip().lower()
        if not q:
            return []
        hops = self.map_hops(here) if here else {}
        found, seen = [], set()
        for m, npcs in self.npcs.items():
            for n in npcs:
                if q in n.name.lower() and (n.name, m, n.x, n.y) not in seen:
                    seen.add((n.name, m, n.x, n.y))
                    near = max(abs(n.x - pos[0]), abs(n.y - pos[1])) if pos and m == here else 0
                    found.append((hops.get(m, 999), n.name.lower() != q, m, near, n))
        found.sort(key=lambda t: t[:4])
        return [t[-1] for t in found[:limit]]

    def map_hops(self, start):
        """Portals to cross from start to every reachable map (breadth-first over the portal graph)."""
        hops = {start: 0}
        queue = deque([start])
        while queue:
            m = queue.popleft()
            for w in self.warps.get(m, ()):
                if w.to_map not in hops:
                    hops[w.to_map] = hops[m] + 1
                    queue.append(w.to_map)
        return hops

    def exits(self, m):
        return [(w.x, w.y, w.to_map) for w in self.warps.get(m, [])]
