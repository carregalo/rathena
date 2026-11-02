"""Installs modified files into the client's data folder, which the client reads before the .grf archives
(the DataFolderFirst patch), and removes them to go back to the original.

The client asks Windows for paths as CP949 bytes, and Windows reads those bytes with the system's ANSI code
page (1252 on Portuguese and English systems). A Korean folder such as 유저인터페이스 therefore has to exist on
disk as "À¯ÀúÀÎÅÍÆäÀÌ½º": the CP949 bytes read as CP1252. Bytes undefined in CP1252 keep their own value.
"""
import os

CLIENT = r"C:\Gravity\Ragnarok"
ANSI = "cp1252"
_BYTE = []
for _b in range(256):
    try:
        _BYTE.append(bytes([_b]).decode(ANSI))
    except UnicodeDecodeError:
        _BYTE.append(chr(_b))


def disk_path(name, client=CLIENT):
    """Where the client looks on disk for an archive path such as data\\sprite\\인간족\\...\\x.spr."""
    raw = name.replace("/", "\\").encode("cp949")
    return os.path.join(client, "".join(_BYTE[b] for b in raw))


def install(name, data, client=CLIENT):
    path = disk_path(name, client)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def remove(name, client=CLIENT):
    """Deletes an installed override (and the folders it leaves empty); the client falls back to the .grf."""
    path = disk_path(name, client)
    if os.path.exists(path):
        os.remove(path)
    folder = os.path.dirname(path)
    root = os.path.join(client, "data")
    while folder.startswith(root) and folder != root and not os.listdir(folder):
        os.rmdir(folder)
        folder = os.path.dirname(folder)
    return path
