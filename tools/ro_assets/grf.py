"""Reads Ragnarok Online .grf archives (version 0x200): list entries and extract files.

Layout (Ragnarok Research Lab, "GRF"): a 46-byte header ("Master of Magic", key, table offset, seed,
file count, version); at 46 + table offset, the compressed and real sizes of the file table followed by the
zlib-compressed table. Each table entry: name (NUL-terminated, CP949), compressed size, aligned size, real
size, flags (1 = file, 2 = mixed DES, 4 = DES on the first block only) and data offset (from byte 46).
Encrypted entries (most sprites) are decoded by grf_des.py, a port of the server's own grfio.
"""
import os
import struct
import zlib
from dataclasses import dataclass

import grf_des

HEADER = b"Master of Magic\0"
FLAG_FILE, FLAG_MIXED, FLAG_DES = 0x01, 0x02, 0x04


@dataclass
class Entry:
    name: str           # path inside the archive, e.g. data\sprite\...\x.spr (backslashes, CP949-decoded)
    packed: int
    aligned: int
    size: int
    flags: int
    offset: int

    @property
    def encrypted(self):
        return bool(self.flags & (FLAG_MIXED | FLAG_DES))


class Grf:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        head = self.f.read(46)
        if head[:16] != HEADER:
            raise ValueError(f"{path}: not a GRF archive")
        table_offset, seed, count, version = struct.unpack_from("<IIII", head, 30)
        if version != 0x200:
            raise ValueError(f"{path}: GRF version 0x{version:x} is not supported (only 0x200)")
        self.f.seek(46 + table_offset)
        packed, real = struct.unpack("<II", self.f.read(8))
        table = zlib.decompress(self.f.read(packed))
        assert len(table) == real
        self.entries = {}
        pos = 0
        for _ in range(count - seed - 7):
            end = table.index(b"\0", pos)
            name = table[pos:end].decode("cp949", "replace")
            packed, aligned, size, flags, offset = struct.unpack_from("<IIIBI", table, end + 1)
            pos = end + 1 + 17
            if flags & FLAG_FILE:
                self.entries[name.lower()] = Entry(name, packed, aligned, size, flags, offset)

    def find(self, pattern):
        """Entries whose path contains pattern (case-insensitive, / or \\ accepted)."""
        p = pattern.lower().replace("/", "\\")
        return [e for k, e in self.entries.items() if p in k]

    def read(self, name):
        e = self.entries[name.lower().replace("/", "\\")]
        self.f.seek(46 + e.offset)
        raw = self.f.read(e.aligned)
        if e.encrypted:
            raw = grf_des.decode(raw, e.flags, e.packed)
        data = zlib.decompressobj().decompress(raw)
        assert len(data) == e.size, e.name
        return data

    def extract(self, name, out_dir):
        """Writes the file under out_dir keeping its archive path; returns the written path."""
        e = self.entries[name.lower().replace("/", "\\")]
        target = os.path.join(out_dir, *e.name.split("\\"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(self.read(name))
        return target
