"""Creates a flat test map for the new game's server and registers it, without touching the official data:

- db/import/map_cache.dat: the map's cells (every cell walkable, a blocked border), in the map cache format the
  map server reads (map_readfromcache in src/map/map.cpp): a header {uint32 file size, uint16 map count} padded
  to 8 bytes, then per map {char name[12], int16 width, int16 height, int32 length} and the zlib-compressed
  cells, one byte per cell (0 = walkable, 1 = wall);
- db/import/map_index.txt: the map's index;
- conf/import/map_conf.txt: "map: <name>", so the map server loads it.

Run from server/:  python tools/maps/make_flat_map.py [name] [width] [height] [index]
"""
import os
import struct
import sys
import zlib

SERVER = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WALKABLE, WALL = 0, 1


def read_cache(path):
    maps = {}
    if os.path.exists(path) and os.path.getsize(path) >= 8:
        data = open(path, "rb").read()
        count = struct.unpack_from("<H", data, 4)[0]
        off = 8
        for _ in range(count):
            name = data[off:off + 12].split(b"\0", 1)[0].decode("ascii")
            xs, ys, length = struct.unpack_from("<hhi", data, off + 12)
            maps[name] = (xs, ys, data[off + 20:off + 20 + length])
            off += 20 + length
    return maps


def write_cache(path, maps):
    body = b"".join(name.encode("ascii").ljust(12, b"\0") + struct.pack("<hhi", xs, ys, len(cells)) + cells
                    for name, (xs, ys, cells) in maps.items())
    with open(path, "wb") as f:
        f.write(struct.pack("<IHxx", 8 + len(body), len(maps)) + body)


def add_line(path, line, key):
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    if not any(l.split()[:len(key.split())] == key.split() for l in lines if l.strip() and not l.startswith("//")):
        with open(path, "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1].strip() else "") + line + "\n")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "testeplano"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    index = int(sys.argv[4]) if len(sys.argv) > 4 else 1999  # map indexes go up to 2000 (MAX_MAPINDEX)
    assert len(name) <= 11, "map names have at most 11 characters"
    cells = bytes(WALL if x in (0, width - 1) or y in (0, height - 1) else WALKABLE
                  for y in range(height) for x in range(width))  # cell (x, y) is at x + y * width
    cache = os.path.join(SERVER, "db", "import", "map_cache.dat")
    maps = read_cache(cache)
    maps[name] = (width, height, zlib.compress(cells))
    write_cache(cache, maps)
    add_line(os.path.join(SERVER, "db", "import", "map_index.txt"), f"{name}\t{index}", name)
    add_line(os.path.join(SERVER, "conf", "import", "map_conf.txt"), f"map: {name}", f"map: {name}")
    print(f"{name}: {width}x{height}, index {index}; cache has {len(maps)} map(s)")


if __name__ == "__main__":
    main()
