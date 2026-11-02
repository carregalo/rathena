"""Generates a C++ program that prints id, sizeof and a 'variable length' flag for every packet
struct defined by the preprocessed rAthena headers of this build.

Usage: gen_struct_dump.py <preprocessed.i> <out.cpp> <header to include>
Two declaration styles are covered:
  const int16 HEADER_<NAME> = <id>;      with struct PACKET_<NAME>
  enum packet_headers { <name>Type = <id> }  with struct packet_<name>
"""
import os
import re
import sys

pre_path, out_path, include = sys.argv[1:4]
pre = open(pre_path, encoding="latin1").read()


def struct_variable(name):
    m = re.search(r"struct\s+" + re.escape(name) + r"\s*\{(.*?)\}\s*(?:__attribute__\s*\(\(packed\)\))?\s*;", pre, re.S)
    if not m:
        return None
    fields = [f.strip() for f in m.group(1).split(";") if f.strip()]
    second = fields[1] if len(fields) > 1 else ""
    return bool(re.search(r"\b(packetLength|packetLen|PacketLength|PacketLen)\b", second))


def enum_struct_map(source_path):
    """<name>Type ids whose struct has another name: read 'X var; var.packetType = nameType' in clif.cpp."""
    mapping = {}
    src = open(source_path, encoding="latin1").read()
    for m in re.finditer(r"\b(\w+)\s*(?:\.|->)\s*(?:packetType|PacketType|packet_id|packetId)\s*=\s*(\w+)Type\s*;", src):
        var, enum_name = m.group(1), m.group(2)
        before = src[max(0, m.start() - 3000):m.start()]
        decls = re.findall(r"\b(PACKET_\w+|packet_\w+)\s*\*?\s*(?:&\s*)?" + re.escape(var) + r"\b", before)
        if decls:
            mapping.setdefault(enum_name, decls[-1])
    return mapping


entries = []
for name, _ in re.findall(r"const\s+int16\s+HEADER_(\w+)\s*=\s*([0-9A-Fa-fx]+)\s*;", pre):
    entries.append((f"HEADER_{name}", f"PACKET_{name}", name))
enum = re.search(r"enum\s+packet_headers\s*\{(.*?)\}", pre, re.S)
if enum:
    clif = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src", "map", "clif.cpp")
    renamed = enum_struct_map(clif) if os.path.exists(clif) else {}
    for name in re.findall(r"(\w+)Type\s*=", enum.group(1)):
        struct_name = f"packet_{name}" if re.search(r"struct\s+packet_" + name + r"\b", pre) else renamed.get(name, f"packet_{name}")
        entries.append((f"{name}Type", struct_name, name))

out = ["#include <cstdio>", '#include "common/cbasetypes.hpp"', '#include "common/mmo.hpp"', f'#include "{include}"', "int main(){"]
seen = set()
for id_expr, struct, name in entries:
    if name in seen:
        continue
    seen.add(name)
    var = struct_variable(struct)
    if var is None:
        out.append(f'\tstd::printf("0x%04x ? 0 {name}\\n", (unsigned)(uint16){id_expr});')
    else:
        # The struct name is printed too, so the caller can inspect the right body.
        out.append(f'\tstd::printf("0x%04x %d {int(var)} {name} {struct}\\n", (unsigned)(uint16){id_expr}, (int)sizeof({struct}));')
out.append("\treturn 0;\n}")
open(out_path, "w").write("\n".join(out) + "\n")
print(f"{len(seen)} packet ids")
