"""Public outline of an area for the map backdrop: no hidden exits, objects or party position."""

import io
from copy import deepcopy

from PIL import Image, ImageChops, ImageDraw, ImageFilter

LONG_SIDE = 768
MIN_SIDE = 384
PUBLIC_KEYS = ("shape", "cols", "rows", "walls", "mask", "edges", "terrain", "material", "environment")
EXIT_KEYS = ("name", "side", "at", "kind", "state", "width")
FLOOR, VOID, WALL = (176, 190, 150), (28, 28, 30), (24, 24, 26)
TERRAIN = {"road": (196, 170, 112), "path": (196, 170, 112), "stream": (96, 140, 190), "bridge": (120, 84, 52)}
EXIT = (255, 196, 0)
INDOOR_FLOOR, ROOF = (150, 120, 80), (96, 70, 50)
ROOM_INSET = 0.6  # cells between the grid edge and the walls of a room


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


def _building_rect(exit, cols, rows):
    """Cell edges (x0, y0, x1, y1), end exclusive, of the roof of the building whose entrance is this exit."""
    side, at = exit["side"], exit["at"]
    length, depth_length = (cols, rows) if side in ("n", "s") else (rows, cols)
    along = min(6, max(3, length // 3))
    depth = min(4, max(2, depth_length // 3))
    start = min(max(at - along // 2, 0), length - along)
    if side == "n":
        return (start, 0, start + along, depth)
    if side == "s":
        return (start, rows - depth, start + along, rows)
    if side == "w":
        return (0, start, depth, start + along)
    return (cols - depth, start, cols, start + along)


def _is_indoor(public: dict) -> bool:
    return public.get("environment") == "indoor"


def render_skeleton(public: dict) -> bytes:
    cols, rows = public["cols"], public["rows"]
    width, height = skeleton_size(cols, rows)
    sx, sy = width / cols, height / rows
    image = Image.new("RGB", (width, height), INDOOR_FLOOR if _is_indoor(public) else FLOOR)
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
        if exit.get("kind") == "entrance":
            x0, y0, x1, y1 = _building_rect(exit, cols, rows)
            fill(x0, y0, x1 - 1, y1 - 1, ROOF)
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
        if exit.get("kind") in ("passage", "entrance"):
            continue  # a path or a building marks it; a bright bar would bleed into the picture
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


CONTROL_LINE = 7  # contour thickness in pixels


def render_control(public: dict) -> bytes | None:
    """Scribble for ControlNet: white contour of the road network (passage paths, stored roads and streams) on black.

    Two parallel edges tell the model "a road runs between", which a single thin line does not. Entrances of buildings are
    closed rectangles (roofs). An indoor area is the outline of its walls. None if there is nothing to draw."""
    cols, rows = public["cols"], public["rows"]
    width, height = skeleton_size(cols, rows)
    sx, sy = width / cols, height / rows
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    if _is_indoor(public):
        draw.rectangle([ROOM_INSET * sx, ROOM_INSET * sy, (cols - ROOM_INSET) * sx - 1, (rows - ROOM_INSET) * sy - 1], fill=255)
    else:
        rects = []  # inclusive cell rectangles
        for exit in public.get("exits") or []:
            if exit.get("kind") == "passage":
                rects += _passage_path(exit, cols, rows, (cols // 2, rows // 2))
            elif exit.get("kind") == "entrance":
                x0, y0, x1, y1 = _building_rect(exit, cols, rows)
                rects.append((x0, y0, x1 - 1, y1 - 1))
        for terrain in public.get("terrain") or []:
            if terrain["kind"] in ("road", "path", "stream"):
                rects += list(_rects(terrain["cells"]))
        if not rects:
            return None
        for x0, y0, x1, y1 in rects:
            draw.rectangle([x0 * sx, y0 * sy, (x1 + 1) * sx - 1, (y1 + 1) * sy - 1], fill=255)
    edge = ImageChops.difference(mask.filter(ImageFilter.MaxFilter(CONTROL_LINE)), mask.filter(ImageFilter.MinFilter(CONTROL_LINE)))
    if not _is_indoor(public):
        ridge = ImageDraw.Draw(edge)  # a ridge line along the long axis makes a closed rectangle read as a gabled roof
        for exit in public.get("exits") or []:
            if exit.get("kind") == "entrance":
                x0, y0, x1, y1 = (v * k for v, k in zip(_building_rect(exit, cols, rows), (sx, sy, sx, sy), strict=True))
                if x1 - x0 >= y1 - y0:
                    ridge.line([(x0 + sx * 0.4, (y0 + y1) / 2), (x1 - sx * 0.4, (y0 + y1) / 2)], fill=255, width=CONTROL_LINE)
                else:
                    ridge.line([((x0 + x1) / 2, y0 + sy * 0.4), ((x0 + x1) / 2, y1 - sy * 0.4)], fill=255, width=CONTROL_LINE)
    out = io.BytesIO()
    edge.point(lambda v: 255 if v else 0).convert("RGB").save(out, format="PNG")
    return out.getvalue()
