"""Decryption of encrypted .grf entries: the client's modified DES (one round, custom S-boxes) plus the block
shuffle and byte substitution. A Python port of src/common/des.cpp and grf_decode in src/common/grfio.cpp
(rAthena, GPL), applied to the aligned compressed data before zlib."""

MASK = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)
IP_TABLE = (58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6,
            64, 56, 48, 40, 32, 24, 16, 8, 57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
            61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7)
FP_TABLE = (40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30,
            37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
            34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25)
TP_TABLE = (16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
            2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25)
S_TABLE = (
    bytes.fromhex("ef0341fdd8741e4726effb22b3d8841e39aca76062c1cdba5c969059053b7a85"
                  "40fd1ec8e78a8b21da43649f2d14b172f55bc8b69c3776ec39a0a305526e0fd9"),
    bytes.fromhex("a7dd0d789e0be3956036364ff9605aa31124d287c85275ecbbc14cba24fe8f19"
                  "da1366af49d090068c6afb91378d0d78bf4911f423e5ce3b55bca257e82274ce"),
    bytes.fromhex("2ceac1bf4a241fc27947a27cb6d9681580565d0133fdf4aede30079be5839b68"
                  "49b42e831fc2b57ca219d8e57c2f83daf76b90fec4015a9761a63d400b58e63d"),
    bytes.fromhex("4dd1b20f28bde478f64a0f938b17d1a43aecc93593567ecb5520a0fe6c891762"
                  "17624bb1b4ded187c9143c4a7ea8e27da09ff65c6a098df00fe35325953628cb"),
)
SUBSTITUTION = {0x00: 0x2B, 0x2B: 0x00, 0x6C: 0x80, 0x01: 0x68, 0x68: 0x01, 0x48: 0x77, 0x60: 0xFF, 0x77: 0x48,
                0xB9: 0xC0, 0xC0: 0xB9, 0xFE: 0xEB, 0xEB: 0xFE, 0x80: 0x6C, 0xFF: 0x60}


def _permute(b, table):
    out = bytearray(8)
    for i, t in enumerate(table):
        j = t - 1
        if b[(j >> 3) & 7] & MASK[j & 7]:
            out[(i >> 3) & 7] |= MASK[i & 7]
    return out


def _round(b):
    e = bytearray(8)  # expansion of the upper 32 bits into eight 6-bit groups
    e[0] = ((b[7] << 5) | (b[4] >> 3)) & 0x3f
    e[1] = ((b[4] << 1) | (b[5] >> 7)) & 0x3f
    e[2] = ((b[4] << 5) | (b[5] >> 3)) & 0x3f
    e[3] = ((b[5] << 1) | (b[6] >> 7)) & 0x3f
    e[4] = ((b[5] << 5) | (b[6] >> 3)) & 0x3f
    e[5] = ((b[6] << 1) | (b[7] >> 7)) & 0x3f
    e[6] = ((b[6] << 5) | (b[7] >> 3)) & 0x3f
    e[7] = ((b[7] << 1) | (b[4] >> 7)) & 0x3f
    s = bytearray(8)
    for i in range(4):
        s[i] = (S_TABLE[i][e[i * 2]] & 0xf0) | (S_TABLE[i][e[i * 2 + 1]] & 0x0f)
    t = bytearray(8)
    for i, v in enumerate(TP_TABLE):
        j = v - 1
        if s[j >> 3] & MASK[j & 7]:
            t[(i >> 3) + 4] |= MASK[i & 7]
    for i in range(4):
        b[i] ^= t[4 + i]


def _decrypt_block(buf, off):
    b = _permute(buf[off:off + 8], IP_TABLE)
    _round(b)
    buf[off:off + 8] = _permute(b, FP_TABLE)


def _shuffle_dec(buf, off):
    s = buf[off:off + 8]
    buf[off:off + 8] = bytes((s[3], s[4], s[6], s[0], s[1], s[2], s[5], SUBSTITUTION.get(s[7], s[7])))


def decode(data, flags, packed_size):
    """Decrypts an entry's aligned data in place semantics; returns the decoded bytes."""
    buf = bytearray(data)
    blocks = len(buf) // 8
    if flags & 0x02:  # mixed: DES on the first 20 blocks, then periodically; some others shuffled
        digits = len(str(packed_size))
        cycle = 1 if digits < 3 else digits + 1 if digits < 5 else digits + 9 if digits < 7 else digits + 15
        for i in range(min(20, blocks)):
            _decrypt_block(buf, i * 8)
        j = -1
        for i in range(20, blocks):
            if i % cycle == 0:
                _decrypt_block(buf, i * 8)
                continue
            j += 1
            if j % 7 == 0 and j != 0:
                _shuffle_dec(buf, i * 8)
    elif flags & 0x04:  # header only: DES on the first 20 blocks
        for i in range(min(20, blocks)):
            _decrypt_block(buf, i * 8)
    return bytes(buf)
