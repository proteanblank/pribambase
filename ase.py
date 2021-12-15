"""Work woth .ase files directly"""

import struct
import enum
from typing import Tuple

class ColorMode(enum.Enum):
    RGBA = 32
    GRAYSCALE = 16
    INDEXED = 8


def info(filepath) -> Tuple[Tuple[int, int], ColorMode]:
    """read and parse ase file header. return (size, color_mode)"""
    with open(filepath, "rb") as f:
        header = f.read(struct.calcsize("<I5H"))
        _, magic, _, w, h, cmode = struct.unpack("<I5H", header)
        assert magic == 0xA5E0, "Not a valid .ase file"
        return (w, h), ColorMode(cmode)