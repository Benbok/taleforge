"""Public outline of an area for the map backdrop: no hidden exits, objects or party position."""

import io
from copy import deepcopy

from PIL import Image, ImageDraw

LONG_SIDE = 768
MIN_SIDE = 384
PUBLIC_KEYS = ("shape", "cols", "rows", "walls", "mask", "edges", "terrain", "material", "environment")
EXIT_KEYS = ("name", "side", "at", "kind", "state", "width")
FLOOR, VOID, WALL = (176, 190, 150), (28, 28, 30), (24, 24, 26)
TERRAIN = {"road": (196, 170, 112), "path": (196, 170, 112), "stream": (96, 140, 190), "bridge": (120, 84, 52)}
EXIT = (255, 196, 0)


def public_sketch(sketch: dict) -> dict:
    result = {key: deepcopy(sketch.get(key)) for key in PUBLIC_KEYS if key in sketch}
    result["exits"] = [
        {key: exit.get(key) for key in EXIT_KEYS if key in exit} for exit in sketch.get("exits", []) if not exit.get("hidden")
    ]
    return result


def skeleton_size(cols: int, rows: int) -> tuple[int, int]:
    long, short = max(cols, rows), min(cols, rows)
    side = min(LONG_SIDE, max(MIN_SIDE, round(LONG_SIDE * short / long / 64) * 64))
    return (LONG_SIDE, side) if cols >= rows else (side, LONG_SIDE)


def _rects(cells):
    for x0, y0, *rest in cells:
        x1, y1 = rest[:2] if len(rest) >= 2 else (x0, y0)
        yield x0, y0, x1, y1


def _passage_path(exit, cols, rows, centre):
    """Cell rectangles of a path from an exit on the grid edge to the grid centre, so the picture connects them."""
    at, span = exit["at"], max(1, exit.get("width") or 1)
    cx, cy = centre
    side = exit["side"]
    if side in ("w", "e"):
        x0, x1 = (0, cx) if side == "w" else (cx, cols - 1)
        return [(x0, at, x1, at + span - 1), (cx, min(at, cy), cx + span - 1, max(at, cy))]
    y0, y1 = (0, cy) if side == "n" else (cy, rows - 1)
    return [(at, y0, at + span - 1, y1), (min(at, cx), cy, max(at, cx), cy + span - 1)]


def render_skeleton(public: dict) -> bytes:
    cols, rows = public["cols"], public["rows"]
    width, height = skeleton_size(cols, rows)
    sx, sy = width / cols, height / rows
    image = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(image)

    def fill(x0, y0, x1, y1, color):
        draw.rectangle([x0 * sx, y0 * sy, (x1 + 1) * sx - 1, (y1 + 1) * sy - 1], fill=color)

    for y, line in enumerate(public.get("mask") or []):
        for x, char in enumerate(line):
            if char != ".":
                fill(x, y, x, y, VOID)
    for terrain in public.get("terrain") or []:
        for rect in _rects(terrain["cells"]):
            fill(*rect, TERRAIN.get(terrain["kind"], FLOOR))
    centre = (cols // 2, rows // 2)
    for exit in public.get("exits") or []:
        if exit.get("kind") == "passage":
            for rect in _passage_path(exit, cols, rows, centre):
                fill(*rect, TERRAIN["path"])
    for x, y in public.get("walls") or []:
        fill(x, y, x, y, WALL)
    for edge in public.get("edges") or []:
        if edge["meaning"] != "obstacle":
            continue
        a, b = edge["start"], edge["start"] + edge["length"]
        side = edge["side"]
        box = {
            "n": [a * sx, 0, b * sx, sy * 0.3],
            "s": [a * sx, height - sy * 0.3, b * sx, height],
            "w": [0, a * sy, sx * 0.3, b * sy],
            "e": [width - sx * 0.3, a * sy, width, b * sy],
        }[side]
        draw.rectangle(box, fill=WALL)
    for exit in public.get("exits") or []:
        if exit.get("kind") == "passage":
            continue  # a path leads to it; a bright bar would bleed into the picture
        at, span = exit["at"], max(1, exit.get("width") or 1)
        box = {
            "n": [at * sx, 0, (at + span) * sx, sy * 0.45],
            "s": [at * sx, height - sy * 0.45, (at + span) * sx, height],
            "w": [0, at * sy, sx * 0.45, (at + span) * sy],
            "e": [width - sx * 0.45, at * sy, width, (at + span) * sy],
        }[exit["side"]]
        draw.rectangle(box, fill=EXIT)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
