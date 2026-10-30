import io

import pytest
from PIL import Image

from app.core.universal.backdrop_skeleton import public_sketch, render_skeleton, skeleton_size


def sketch(**over):
    base = {
        "shape": "open",
        "cols": 10,
        "rows": 8,
        "party": [3, 3],
        "walls": [[0, 0]],
        "mask": None,
        "edges": [{"side": "n", "start": 0, "length": 10, "meaning": "boundary"}],
        "terrain": [{"kind": "road", "cells": [[4, 0, 4, 7]]}],
        "material": "grass",
        "environment": "outdoor",
        "exits": [
            {"name": "Дверь", "side": "n", "at": 5, "kind": "door", "state": None, "width": 1,
             "to": "SECRET-ROOM", "room_ref": "r1", "cells": [[5, 0]], "passage_ref": "p1", "route_ref": "x"},
            {"name": "Тайный ход", "side": "w", "at": 2, "kind": "door", "hidden": True},
        ],
        "features": [{"name": "SECRET-TRAP", "kind": "object", "cells": [[2, 2, 2, 2]], "hidden": True}],
        "unplaced_exits": [{"name": "SECRET-UNPLACED"}],
        "edit_rev": 4,
    }
    return {**base, **over}


def test_public_sketch_drops_hidden_and_private_fields():
    result = public_sketch(sketch())
    text = str(result)
    assert "SECRET" not in text and "Тайный ход" not in text
    assert "features" not in result and "unplaced_exits" not in result and "party" not in result
    assert result["exits"] == [{"name": "Дверь", "side": "n", "at": 5, "kind": "door", "state": None, "width": 1}]
    assert result["cols"] == 10 and result["terrain"][0]["kind"] == "road"


@pytest.mark.parametrize(
    ("cols", "rows", "size"), [(1, 8, (384, 768)), (40, 3, (768, 384)), (10, 10, (768, 768)), (12, 8, (768, 512))]
)
def test_skeleton_size(cols, rows, size):
    assert skeleton_size(cols, rows) == size
    assert all(side % 64 == 0 for side in size)


def decode(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_render_is_deterministic_and_has_requested_size():
    public = public_sketch(sketch())
    first, second = render_skeleton(public), render_skeleton(public)
    assert first == second
    assert decode(first).size == skeleton_size(10, 8)


def test_wall_and_floor_colors_differ():
    image = decode(render_skeleton(public_sketch(sketch(edges=[], terrain=[], exits=[]))))
    cell = 768 / 10
    wall = image.getpixel((int(cell * 0.5), int(cell * 0.5)))
    floor = image.getpixel((int(cell * 6.5), int(cell * 4.5)))
    assert wall != floor


def test_mask_marks_non_floor_dark():
    mask = ["#" * 10] + ["." * 10] * 7
    image = decode(render_skeleton(public_sketch(sketch(mask=mask, walls=[], edges=[], terrain=[], exits=[]))))
    cell = 768 / 10
    assert image.getpixel((int(cell * 5.5), int(cell * 0.5))) != image.getpixel((int(cell * 5.5), int(cell * 3.5)))


def test_passage_exits_get_a_path_towards_the_centre():
    exits = [{"name": "Колея", "side": "w", "at": 5, "kind": "passage", "width": 2}]
    plain = decode(render_skeleton(public_sketch(sketch(edges=[], terrain=[], exits=[], party=[5, 4]))))
    with_path = decode(render_skeleton(public_sketch(sketch(edges=[], terrain=[], exits=exits))))
    cell_w, cell_h = 768 / 10, 640 / 8
    point = (int(cell_w * 2.5), int(cell_h * 5.5))  # between the west edge and the centre, on the exit's row
    assert plain.getpixel(point) != with_path.getpixel(point)
    corner = (int(cell_w * 8.5), int(cell_h * 0.5))
    assert plain.getpixel(corner) == with_path.getpixel(corner)
