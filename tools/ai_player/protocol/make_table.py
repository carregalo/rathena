"""Builds packet_table.json for the bot from this rAthena build's own headers.

Run from this folder on Windows with the VS Build Tools installed:
    python make_table.py
It compiles three small dump tools (build.bat / preprocess.bat) and combines their output:
  - dump_packetdb: the map-server packet_db exactly as packetdb_readdb() fills it (last registration wins)
  - struct sizes of every packet struct in src/common/packets.hpp and src/map/packets.hpp
Lengths: -1 means variable (length in bytes 2-3). Struct sizes win over legacy packet_db entries for
server->client packets, because the server sends the structs.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ai_player_proto_")


def run_bat(bat, *args):
    subprocess.run(["cmd", "/c", os.path.join(HERE, bat), *args], check=True, stdout=subprocess.DEVNULL)


def exe_lines(cpp, name):
    exe = os.path.join(TMP, name + ".exe")
    run_bat("build.bat", cpp, exe)
    return subprocess.run([exe], check=True, capture_output=True, text=True).stdout.splitlines()


def struct_sizes(header, tag):
    src = os.path.join(TMP, f"pp_{tag}.cpp")
    with open(src, "w") as f:
        f.write(f'#include "common/cbasetypes.hpp"\n#include "common/mmo.hpp"\n#include "{header}"\n')
    pre = os.path.join(TMP, f"pp_{tag}.i")
    run_bat("preprocess.bat", src, pre)
    dump_cpp = os.path.join(TMP, f"dump_{tag}.cpp")
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "gen_struct_dump.py"), pre, dump_cpp, header],
                   check=True, stdout=subprocess.DEVNULL)
    text = open(pre, encoding="latin1").read()
    sizes = {}
    for line in exe_lines(dump_cpp, f"dump_{tag}"):
        parts = line.split()
        pid, size, var, name = parts[:4]
        if size == "?":
            print(f"  unresolved {tag} packet {pid} {name}")
            continue
        struct_name = parts[4]
        # A size field in the second member or a flexible array means the length is in bytes 2-3.
        body = re.search(r"struct\s+" + re.escape(struct_name) + r"\s*\{(.*?)\}", text, re.S)
        fields = [x.strip() for x in body.group(1).split(";") if x.strip()] if body else []
        second = fields[1] if len(fields) > 1 else ""
        flexible = body is not None and "[]" in body.group(1)
        sized = re.search(r"\b(packetLength|packetLen|PacketLength|PacketLen|packetSize|length)\b", second)
        sizes[int(pid, 16)] = (-1 if var == "1" or flexible or sized else int(size), name)
    return sizes


def main():
    packetdb = {}
    version = None
    for line in exe_lines(os.path.join(HERE, "dump_packetdb.cpp"), "dump_packetdb"):
        if line.startswith("# PACKETVER"):
            version = int(line.split()[2])
            continue
        if line.startswith("#"):
            continue
        parts = line.split(None, 3)
        packetdb[int(parts[0], 16)] = (int(parts[1]), parts[2], parts[3] if len(parts) > 3 else "")

    common = struct_sizes("common/packets.hpp", "common")
    zone = struct_sizes("map/packets.hpp", "map")

    def merged(structs):
        table = {pid: length for pid, (length, _, _) in packetdb.items()}
        for pid, (length, _) in structs.items():
            table[pid] = length
        return {f"0x{pid:04x}": length for pid, length in sorted(table.items())}

    handlers = {}
    for pid, (length, func, pos) in packetdb.items():
        if func != "nullptr":
            handlers.setdefault(func.replace("clif_parse_", ""), []).append(
                {"id": f"0x{pid:04x}", "len": length, "pos": [int(p) for p in pos.split(",") if p.strip() not in ("", "0")]})

    out = {"packetver": version, "char": merged(common), "zone": merged(zone), "handlers": handlers}
    with open(os.path.join(HERE, "..", "packet_table.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"PACKETVER {version}: {len(out['zone'])} zone ids, {len(out['char'])} char ids, {len(handlers)} handlers")


if __name__ == "__main__":
    main()
