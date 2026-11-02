"""Pipeline test: recolours the Novice body sprites (male and female) and installs them in the client's data
folder, to check in game that a sprite written by these tools replaces the original.

    python test_override.py install    # writes the recoloured sprites (and preview PNGs in work/)
    python test_override.py remove     # deletes them: the client goes back to the .grf originals
"""
import colorsys
import os
import sys

import datafolder
from grf import Grf
from spr import Sprite

SPRITES = [r"data\sprite\인간족\몸통\남\초보자_남.spr", r"data\sprite\인간족\몸통\여\초보자_여.spr"]


def recolour(palette, hue_from=(0.02, 0.14), hue_to=0.28):
    """Moves the orange/tan colours (the Novice's clothes) to green, keeping brightness and saturation."""
    out = bytearray(palette)
    for i in range(1, 256):
        r, g, b = (c / 255 for c in palette[i * 4:i * 4 + 3])
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if hue_from[0] <= h <= hue_from[1] and s > 0.25:
            r, g, b = colorsys.hsv_to_rgb(hue_to + (h - hue_from[0]) * 0.5, s * 0.9, v)
            out[i * 4:i * 4 + 3] = bytes(round(c * 255) for c in (r, g, b))
    return bytes(out)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    if action == "remove":
        for name in SPRITES:
            print("removed", datafolder.remove(name))
        return
    g = Grf(os.path.join(datafolder.CLIENT, "data.grf"))
    os.makedirs("work", exist_ok=True)
    for name in SPRITES:
        s = Sprite.load(g.read(name))
        s.palette = recolour(s.palette)
        tag = "m" if "\\남\\" in name else "f"
        s.sheet(scale=2, columns=16).save(f"work/test_novice_{tag}.png")
        print("installed", datafolder.install(name, s.save()))


if __name__ == "__main__":
    main()
