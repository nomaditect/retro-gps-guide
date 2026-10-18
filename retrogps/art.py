"""Pixel art: the eTrex man, satellites, waypoint symbols, weather icons and the maple leaf.
Small bitmaps are drawn as text ('#' = black) so they're easy to tweak by eye."""
import os

from PIL import Image

from .config import ASSETS

_mark = None


def mark_art():
    """The eTrex "mark waypoint" man, traced from the original at its native pixel grid."""
    global _mark
    if _mark is None:
        _mark = Image.open(os.path.join(ASSETS, "mark.png")).convert("1")
    return _mark


MARK_FLAG_TEXT = (66, 54)  # where the waypoint number goes in the flag (centre x, baseline y)


def bitmap(rows):
    return [r for r in rows.strip("\n").split("\n")]


def blit(draw, rows, x, y, scale=1, color=0):
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "#":
                draw.rectangle((x + i * scale, y + j * scale, x + i * scale + scale - 1,
                                y + j * scale + scale - 1), fill=color)


def size(rows):
    return max(len(r) for r in rows), len(rows)


MAN = bitmap("""
..###..
..###..
...#...
.#####.
#.###.#
#.###.#
..###..
..#.#..
..#.#..
.##.##.
""")

SATELLITE = bitmap("""
##..###..##
##.#####.##
###########
##.#####.##
##..###..##
""")

COFFEE = bitmap("""
..#.#....
.#.#.....
.........
#######..
#.....###
#.....#.#
#.....###
.#...#...
#########
""")

FOOD = bitmap("""
#.#.#..#.
#.#.#.##.
#.#.#.##.
#####.##.
.###..##.
..#...##.
..#....#.
..#....#.
..#....#.
""")

BEER = bitmap("""
.#.#.#...
#######..
#.....###
#.#.#.#.#
#.#.#.#.#
#.#.#.###
#.#.#.#..
#.....#..
#######..
""")

BARBELL = bitmap("""
.........
#.......#
##.....##
##.....##
#########
##.....##
##.....##
#.......#
.........
""")

STAR = bitmap("""
....#....
...###...
...###...
#########
.#######.
..#####..
..##.##..
.##...##.
.#.....#.
""")

FLAG = bitmap("""
######.
#######
######.
#......
#......
#......
#......
###....
""")

SYMBOLS = {"coffee": COFFEE, "food": FOOD, "beer": BEER, "todo": STAR, "gym": BARBELL, "wpt": FLAG}

BATTERY_W, BATTERY_H = 9, 14


def _icon16(hexrows):
    return ["".join("#" if v & (0x8000 >> c) else "." for c in range(16)) for v in hexrows]


# 16x16 weather icons (from the Retro Canada Guide)
WEATHER_ICONS = {k: _icon16(v) for k, v in {
    "sun": (0x0180, 0x4182, 0x2004, 0x0000, 0x03C0, 0x04E0, 0x0DF0, 0xCFF3, 0xCFF3, 0x0FF0, 0x07E0,
            0x03C0, 0x0000, 0x2004, 0x4182, 0x0180),
    "partly": (0x0020, 0x0402, 0x0070, 0x00F8, 0x01FC, 0x01FD, 0x001C, 0x03C8, 0x07E0, 0x7670, 0xFDF9,
               0xFFFC, 0xFFFE, 0xFFFE, 0xFFFC, 0x0000),
    "cloudy": (0x0000, 0x0000, 0x0000, 0x0000, 0x01E0, 0x03F0, 0x3B38, 0x7EFC, 0x7FFE, 0xFFFF, 0xFFFF,
               0x7FFE, 0x0000, 0x0000, 0x0000, 0x0000),
    "fog": (0x0000, 0x0000, 0x0000, 0x3FF0, 0x3FF0, 0x0000, 0x07FE, 0x07FE, 0x0000, 0x7FE0, 0x7FE0,
            0x0000, 0x0FFC, 0x0FFC, 0x0000, 0x0000),
    "drizzle": (0x0000, 0x01E0, 0x03F0, 0x3B38, 0x7EFC, 0x7FFE, 0xFFFF, 0xFFFF, 0x7FFE, 0x0000, 0x0000,
                0x1110, 0x0000, 0x0000, 0x0444, 0x0000),
    "rain": (0x0000, 0x01E0, 0x03F0, 0x3B38, 0x7EFC, 0x7FFE, 0xFFFF, 0xFFFF, 0x7FFE, 0x0000, 0x0888,
             0x0888, 0x1110, 0x1110, 0x2220, 0x2220),
    "snow": (0x0000, 0x01E0, 0x03F0, 0x3B38, 0x7EFC, 0x7FFE, 0xFFFF, 0xFFFF, 0x7FFE, 0x0000, 0x0000,
             0x1004, 0x388E, 0x11C4, 0x0080, 0x0000),
    "storm": (0x01E0, 0x03F0, 0x3B38, 0x7EFC, 0x7FFE, 0xFFFF, 0xFFFF, 0x7CCE, 0x0180, 0x0300, 0x07E0,
              0x00C0, 0x0180, 0x0300, 0x0200, 0x0000),
}.items()}


def weather_icon(code):
    if code <= 1:
        return WEATHER_ICONS["sun"]
    if code == 2:
        return WEATHER_ICONS["partly"]
    if code == 3:
        return WEATHER_ICONS["cloudy"]
    if code in (45, 48):
        return WEATHER_ICONS["fog"]
    if 51 <= code <= 57:
        return WEATHER_ICONS["drizzle"]
    if 71 <= code <= 77 or code in (85, 86):
        return WEATHER_ICONS["snow"]
    if code >= 95:
        return WEATHER_ICONS["storm"]
    return WEATHER_ICONS["rain"]


# 24x24 maple leaf from the Canadian flag's outline, drawn at 2x
_LEAF = (0x000000, 0x001800, 0x001800, 0x00BD00, 0x00FF00, 0x00FF00, 0x00FF00, 0x04FF20,
         0x7E7E7E, 0x3FFFFC, 0x3FFFFC, 0x3FFFFC, 0x7FFFFE, 0x3FFFFC, 0x0FFFF0, 0x07FFE0,
         0x03FFC0, 0x03FFC0, 0x03DBC0, 0x001800, 0x001800, 0x001800, 0x001800, 0x001800)
LEAF = ["".join("#" if v & (0x800000 >> c) else "." for c in range(24)) for v in _LEAF]
