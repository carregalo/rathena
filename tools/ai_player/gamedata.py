"""Game data read from the server's files (item and class names), and small text helpers."""
import glob
import os
import re
import unicodedata

import config

def to_game_text(text, limit=100):
    """ASCII only: the game client does not render UTF-8."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ascii_text = "".join(c for c in ascii_text if c.isprintable()).replace("^", "")
    return ascii_text.strip()[:limit]


def load_job_names():
    """Class names from enum e_job in src/common/mmo.hpp, e.g. 4057 -> 'Arch Bishop'."""
    names, value = {}, -1
    try:
        src = open(os.path.join(config.HERE, "..", "..", "src", "common", "mmo.hpp"), encoding="utf-8").read()
    except OSError:
        return names
    body = re.search(r"enum e_job \{(.*?)\};", src, re.S)
    for line in (body.group(1).splitlines() if body else []):
        m = re.match(r"\s*JOB_([A-Z0-9_]+)\s*(?:=\s*([0-9xa-fA-F]+))?\s*,", line)
        if m:
            value = int(m.group(2), 0) if m.group(2) else value + 1
            names.setdefault(value, m.group(1).replace("_", " ").title())
    return names


JOB_NAMES = load_job_names()


def load_item_names():
    names = {}
    for path in glob.glob(config.ITEM_DB_GLOB):
        item_id = None
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*-\s*Id:\s*(\d+)", line)
            if m:
                item_id = int(m.group(1))
                continue
            m = re.match(r"\s*Name:\s*(.+)", line)
            if m and item_id is not None:
                names[item_id] = m.group(1).strip()
                item_id = None
    return names


def find_item(w, item_names, name, worn=None):
    """Inventory item whose name matches (case-insensitive); worn=True/False restricts to worn or not worn."""
    want = name.strip().lower()
    for i in w.inventory.values():
        if item_names.get(i.item_id, "").lower() == want and (worn is None or bool(i.worn) == worn):
            return i
    return None
