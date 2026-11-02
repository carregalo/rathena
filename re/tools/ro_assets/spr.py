"""Ragnarok Online sprite images (.spr): read, write, and convert to and from PNG.

Layout (Ragnarok Research Lab, "SPR"), version 2.1 as used by this client:
  "SP", minor version, major version, indexed frame count (u16), RGBA frame count (u16);
  indexed frames: width (u16), height (u16), RLE size (u16), RLE data where a 0 byte is followed by how many
  transparent (index 0) pixels follow; RGBA frames: width, height, width*height*4 bytes (A, B, G, R order,
  rows bottom-up); then a 256-colour palette (4 bytes per colour, R G B and an unused byte).
Palette index 0 is transparent.
"""
import struct
from dataclasses import dataclass, field

from PIL import Image


@dataclass
class Frame:
    width: int
    height: int
    pixels: bytes          # palette indices, row by row (width * height)


@dataclass
class Sprite:
    frames: list = field(default_factory=list)       # indexed (palette) frames
    rgba_frames: list = field(default_factory=list)  # (width, height, raw bytes) kept as they are
    palette: bytes = bytes(1024)
    version: tuple = (2, 1)

    # ------------------------------------------------------------------ binary

    @classmethod
    def load(cls, data):
        if data[:2] != b"SP":
            raise ValueError("not a sprite")
        minor, major = data[2], data[3]
        indexed, rgba = struct.unpack_from("<HH", data, 4)
        off = 8
        s = cls(version=(major, minor))
        for _ in range(indexed):
            w, h = struct.unpack_from("<HH", data, off)
            off += 4
            if (major, minor) >= (2, 1):
                size = struct.unpack_from("<H", data, off)[0]
                off += 2
                s.frames.append(Frame(w, h, _rle_decode(data[off:off + size], w * h)))
                off += size
            else:
                s.frames.append(Frame(w, h, bytes(data[off:off + w * h])))
                off += w * h
        for _ in range(rgba):
            w, h = struct.unpack_from("<HH", data, off)
            s.rgba_frames.append((w, h, bytes(data[off + 4:off + 4 + w * h * 4])))
            off += 4 + w * h * 4
        s.palette = bytes(data[-1024:])
        return s

    def save(self):
        out = bytearray(b"SP" + bytes((1, 2)) + struct.pack("<HH", len(self.frames), len(self.rgba_frames)))
        for f in self.frames:
            rle = _rle_encode(f.pixels)
            out += struct.pack("<HHH", f.width, f.height, len(rle)) + rle
        for w, h, raw in self.rgba_frames:
            out += struct.pack("<HH", w, h) + raw
        out += self.palette
        return bytes(out)

    # ------------------------------------------------------------------ images

    def colors(self):
        return [tuple(self.palette[i * 4:i * 4 + 3]) for i in range(256)]

    def frame_image(self, i, palette=None):
        """An RGBA image of indexed frame i (index 0 transparent), optionally with another palette."""
        f = self.frames[i]
        img = Image.frombytes("P", (f.width, f.height), f.pixels)
        pal = palette or self.palette
        img.putpalette(b"".join(pal[k * 4:k * 4 + 3] for k in range(256)))
        img.info["transparency"] = 0
        return img.convert("RGBA")

    def sheet(self, scale=2, columns=12, palette=None):
        """All indexed frames side by side on a checkered background, for looking at a whole sprite."""
        cell_w = max(f.width for f in self.frames) * scale
        cell_h = max(f.height for f in self.frames) * scale
        rows = (len(self.frames) + columns - 1) // columns
        sheet = Image.new("RGBA", (cell_w * columns, cell_h * rows), (200, 200, 210, 255))
        for i in range(len(self.frames)):
            img = self.frame_image(i, palette).resize(
                (self.frames[i].width * scale, self.frames[i].height * scale), Image.NEAREST)
            x, y = (i % columns) * cell_w, (i // columns) * cell_h
            if ((i % columns) + (i // columns)) % 2:
                sheet.paste((185, 185, 198, 255), (x, y, x + cell_w, y + cell_h))
            sheet.alpha_composite(img, (x + (cell_w - img.width) // 2, y + (cell_h - img.height) // 2))
        return sheet


def _rle_decode(rle, size):
    out = bytearray()
    i = 0
    while i < len(rle) and len(out) < size:
        c = rle[i]
        i += 1
        if c == 0:
            out += bytes(rle[i] if i < len(rle) else 0)
            i += 1
        else:
            out.append(c)
    return bytes(out[:size].ljust(size, b"\0"))


def _rle_encode(pixels):
    out = bytearray()
    i = 0
    while i < len(pixels):
        if pixels[i] == 0:
            run = 1
            while i + run < len(pixels) and pixels[i + run] == 0 and run < 255:
                run += 1
            out += bytes((0, run))
            i += run
        else:
            out.append(pixels[i])
            i += 1
    return bytes(out)
