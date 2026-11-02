"""Builds the length of every packet the servers send to the client, for this build's PACKETVER, so a client can
split the byte stream into packets. Writes re/spec/protocol/lengths.json:
  {"map": {"0x02eb": 13, "0x0b72": -1, ...}, "char": {...}}   (-1 = variable: uint16 length at offset 2)

Sources, all from the server's own code:
  1. the map packet table (map.json, from dump_protocol), for packets without a struct;
  2. every DEFINE_PACKET_HEADER(NAME, id) that survives preprocessing with the server's settings, paired with
     struct PACKET_NAME: a generated C++ program prints sizeof() of each, compiled with the same headers;
  3. packet ids declared as enum entries (e.g. inventorylistnormalType): the struct is the type of the variable
     whose packet type is set to that entry in clif.cpp.
A struct is variable-length when its second member is its length (packetLength / PacketLength).

Run from re/tools/protocol after build.bat:  python gen_lengths.py
"""
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.normpath(os.path.join(HERE, "..", "..", "..", "server"))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "spec", "protocol"))
WORK = os.path.join(HERE, "out")
VCVARS = r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
INCLUDES = [r"src", r"3rdparty\rapidyaml\src", r"3rdparty\rapidyaml\ext\c4core\src", r"3rdparty\pcre\include",
            r"3rdparty\libconfig", r"3rdparty\mysql\include"]
FLAGS = "/nologo /std:c++17 /EHsc /W0 /D WIN32 /D FD_SETSIZE=4096 /D PCRE_SUPPORT /D _CRT_SECURE_NO_DEPRECATE " \
        "/D _WINSOCK_DEPRECATED_NO_WARNINGS /D LIBCONFIG_STATIC " + " ".join(f'/I "{os.path.join(SRV, i)}"' for i in INCLUDES)
LENGTH_FIELD = re.compile(r"^\s*u?int16\s+(packetLength|PacketLength|packetLen|PacketLen|length)\s*;")


def run_cl(args):
    bat = os.path.join(WORK, "run_cl.bat")  # through a .bat: cmd /c mangles the quoted Visual Studio path
    with open(bat, "w") as f:
        f.write(f'@call "{VCVARS}" >nul\n@cl {FLAGS} {args}\n')
    return subprocess.run([bat], cwd=WORK, capture_output=True, text=True, errors="replace")


def preprocess(headers, name):
    src = os.path.join(WORK, f"pp_{name}.cpp")
    with open(src, "w") as f:
        f.write("#include <common/cbasetypes.hpp>\n#include <common/mmo.hpp>\n")
        f.writelines(f"#include <{h}>\n" for h in headers)
    r = run_cl(f'/EP "{src}"')
    if not r.stdout:
        raise SystemExit(f"preprocessing {name} failed:\n{r.stderr[-2000:]}")
    return r.stdout


def struct_bodies(text):
    """struct NAME { ... } bodies of the preprocessed text (first definition wins: only one survives #if)."""
    bodies = {}
    for m in re.finditer(r"struct\s+(\w+)\s*\{", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        bodies.setdefault(m.group(1), text[m.end():i - 1])
    return bodies


def variable(body):
    members = [l for l in body.splitlines() if l.strip() and not l.strip().startswith(("//", "#"))]
    return len(members) > 1 and bool(LENGTH_FIELD.match(members[1]))


def enum_structs(text, enum_names):
    """Struct type of the variable that gets packet type <enum entry> in clif.cpp."""
    clif = open(os.path.join(SRV, r"src\map\clif.cpp"), encoding="utf-8", errors="replace").read().splitlines()
    found = {}
    for n, line in enumerate(clif):
        m = re.search(r"(\w+)(?:\.|->)(?:packetType|PacketType)\s*=\s*(\w+Type)\b", line)
        if not m or m.group(2) not in enum_names:
            continue
        var = m.group(1)
        for back in range(n, max(0, n - 120), -1):
            d = re.search(rf"(?:struct\s+)?(\w+)\s*[\*&]?\s*\b{var}\b\s*(?:=|;|\{{|\[)", clif[back])
            if d and d.group(1) not in ("return", "static", "const", "auto"):
                found.setdefault(m.group(2), d.group(1))
                break
            d = re.search(rf"\b{var}\s*=\s*\(?\s*(?:struct\s+)?(\w+)\s*\*\)", clif[back])
            if d:
                found.setdefault(m.group(2), d.group(1))
                break
    return found


def sizes_of(headers, structs, name):
    """Compiles a program printing sizeof() of each struct; returns {struct: size}."""
    src = os.path.join(WORK, f"sizes_{name}.cpp")
    with open(src, "w") as f:
        f.write("#include <cstdio>\n#include <common/cbasetypes.hpp>\n#include <common/mmo.hpp>\n")
        f.writelines(f"#include <{h}>\n" for h in headers)
        f.write("int main(){\n")
        f.writelines(f'\tstd::printf("{s} %d\\n", (int)sizeof(struct {s}));\n' for s in structs)
        f.write("\treturn 0;\n}\n")
    exe = os.path.join(WORK, f"sizes_{name}.exe")
    r = run_cl(f'"{src}" /Fe"{exe}" /Fo"{WORK}\\\\"')
    if r.returncode:
        raise SystemExit(f"compiling sizes_{name} failed:\n{r.stdout[-3000:]}")
    out = subprocess.run([exe], capture_output=True, text=True).stdout
    return {line.split()[0]: int(line.split()[1]) for line in out.splitlines() if line.strip()}


def lengths_for(headers, name, table=None):
    text = preprocess(headers, name)
    bodies = struct_bodies(text)
    headers_ids = {m.group(1): int(m.group(2), 0)
                   for m in re.finditer(r"const int16 HEADER_(\w+) = (0x[0-9a-fA-F]+|\d+);", text)}
    pairs = {f"PACKET_{h}": pid for h, pid in headers_ids.items() if f"PACKET_{h}" in bodies}
    if name == "map":
        enums = {m.group(1): int(m.group(2), 0) for m in re.finditer(r"\b(\w+Type) = (0x[0-9a-fA-F]+)", text)}
        for entry, struct in enum_structs(text, set(enums)).items():
            if struct in bodies:
                pairs.setdefault(struct, enums[entry])
    sizes = sizes_of(headers, sorted(pairs), name)
    lengths = {}
    if table:  # packets without a struct: lengths from the packet table (last entry wins, as in the server)
        for p in table:
            lengths[p["id"]] = p["length"]
    for struct, pid in pairs.items():
        lengths[f"0x{pid:04x}"] = -1 if variable(bodies[struct]) else sizes[struct]
    return lengths, len(pairs)


def main():
    os.makedirs(WORK, exist_ok=True)
    table = json.load(open(os.path.join(OUT, "map.json")))["packets"]
    map_lengths, n_map = lengths_for(["map/packets.hpp"], "map", table)
    char_lengths, n_char = lengths_for(["common/packets.hpp"], "char")
    with open(os.path.join(OUT, "lengths.json"), "w") as f:
        json.dump({"packetver": json.load(open(os.path.join(OUT, "map.json")))["packetver"],
                   "note": "-1 = variable length: uint16 at offset 2. The char server also sends the account id "
                           "as 4 raw bytes, without a packet id, right after CH_ENTER (chclif_parse_reqtoconnect).",
                   "map": dict(sorted(map_lengths.items())), "char": dict(sorted(char_lengths.items()))}, f, indent=1)
    print(f"map: {len(map_lengths)} ids ({n_map} from structs); char: {len(char_lengths)} ids ({n_char} from structs)")


if __name__ == "__main__":
    main()
