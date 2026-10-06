# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Готовые приключения: проверки сдачи переводчика, разбор книги с повтором, карты, публикация пакетом."""

import dataclasses
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.content.catalog import load_catalog
from app.core import modules
from app.db.models import LlmCall
from app.main import create_app
from tests.game import QueueDice, import_base, ok, run
from tests.module_sample import sample
from tests.test_api import login

ROOT = Path(__file__).resolve().parents[1] / "content"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


def check(raw):
    return modules.check(raw, ROOT)


def test_sample_module_passes_and_keeps_book_measure():
    draft, errors, warnings = check(sample())
    assert errors == [] and warnings == []
    plan = draft["plot"]
    # у книги своя мера: три шага угрозы, одна зацепка, два акта с уровнями по этапам
    assert len(plan["antagonists"][0]["threat"]) == 3 and plan["acts"][1]["milestone_level"] == 3
    assert plan["acts"][0]["status"] == "active" and plan["locations"][0]["status"] == "sketch"
    s = modules.summary(draft)
    assert s["counts"] == {"locations": 2, "rooms": 3, "creatures": 1, "items": 1, "hooks": 2, "acts": 2}
    assert modules.room_numbers(draft) == {"location.davos_crypt": ["1", "2"], "location.davos_temple": ["1"]}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda m: m["locations"][0]["rooms"][0].update(exits=["r9"]), "выходы в неизвестные комнаты ['r9']"),
        (lambda m: m["creatures"][0].update(id="creature.skeleton"), "id совпадают с записями SRD"),
        (lambda m: m["creatures"][0].update(base_ref="creature.nope"), "нет такого существа SRD"),
        (lambda m: m["creatures"][0]["changes"].update(actions=[]), "в changes нельзя менять actions"),
        (lambda m: m["items"][0].update(modifiers=[{"op": "custom"}]), "op: custom нельзя"),
        (lambda m: m["items"][0].update(modifiers=[{"op": "teleport"}]), "движок не умеет op 'teleport'"),
        (lambda m: m["locations"][0]["rooms"][0]["checks"][0].update(skill="lockpicking"), "нет навыка"),
        (lambda m: m["locations"][0]["rooms"][0]["checks"][0].update(dc=45), "сложность проверки"),
        (lambda m: m["locations"][0]["rooms"][1].update(number="1"), "номер 1 у двух комнат"),
        (
            lambda m: m["locations"][1]["rooms"][0]["encounters"][0].update(creature_ref="creature.ghost_x"),
            "creature.ghost_x",
        ),
        (lambda m: m["plot"]["locations"][0].update(template_id="location.nowhere"), "каркас: локация crypt"),
        (lambda m: m.update(slug="Неспокойные"), "slug"),
        (lambda m: m.update(hooks=[]), "зацепка"),
    ],
)
def test_server_returns_errors_to_the_translator(change, expected):
    raw = sample()
    change(raw)
    draft, errors, _ = check(raw)
    assert draft is None
    assert any(expected in e for e in errors), errors


def test_map_marks_are_checked_against_rooms():
    draft, _, _ = check(sample())
    good = {"location_id": "location.davos_crypt", "marks": [{"number": "1", "x": 0.2, "y": 0.5}]}
    result, errors = modules.check_marks(good, draft)
    assert errors == [] and result["missing"] == ["2"]
    bad = {"location_id": "location.davos_crypt", "marks": [{"number": "7", "x": 0.2, "y": 0.5}]}
    assert "нет комнаты с номером '7'" in modules.check_marks(bad, draft)[1][0]
    off = {"location_id": "location.davos_crypt", "marks": [{"number": "1", "x": 1.5, "y": 0.5}]}
    assert "доли от 0 до 1" in modules.check_marks(off, draft)[1][0]
    assert "нет места" in modules.check_marks({"location_id": "location.x", "marks": []}, draft)[1][0]


GRID = {"cols": 10, "rows": 8, "left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}


def test_room_cells_and_obstacles_are_checked():
    draft, _, _ = check(sample())
    room = {"number": "1", "x": 0.2, "y": 0.2, "cells": [[0, 0, 3, 2]], "blocked": [[1, 1]]}
    result, errors = modules.check_marks({"location_id": "location.davos_crypt", "grid": GRID, "marks": [room]}, draft)
    assert errors == [] and result["grid"] == GRID and result["marks"][0]["blocked"] == [[1, 1]]

    def errs(**mark):
        raw = {"location_id": "location.davos_crypt", "grid": GRID, "marks": [{**room, **mark}]}
        return " ".join(modules.check_marks(raw, draft)[1])

    assert "внутри сетки" in errs(cells=[[0, 0, 12, 2]])
    assert "вне комнаты" in errs(blocked=[[7, 7]])
    assert "не осталось свободных клеток" in errs(cells=[[0, 0, 0, 0]], blocked=[[0, 0]])
    no_grid = {"location_id": "location.davos_crypt", "marks": [room]}
    assert "клетки без сетки" in modules.check_marks(no_grid, draft)[1][0]
    bad_grid = {"location_id": "location.davos_crypt", "grid": {**GRID, "left": 0.9, "right": 0.1}, "marks": []}
    assert "left < right" in modules.check_marks(bad_grid, draft)[1][0]


def test_heroes_stand_on_free_cells_near_their_positions():
    # комната 5×3 клетки, посередине колонна
    mark = {"cells": [[0, 0, 4, 2]], "blocked": [[2, 1]]}
    spots = modules.place_tokens(GRID, mark, [("a", 0, 0), ("b", 0, 0), ("c", 10, 0), ("d", 0, 10)])
    assert (2, 1) not in spots.values()  # на колонну никто не встал
    assert len(set(spots.values())) == 4  # двое в одной точке встали в разные клетки
    assert spots["c"] == (4, 1)  # 10 футов на восток — две клетки вправо
    assert spots["d"][1] == 0  # на север — вверх
    assert modules.cell_center(GRID, 4, 1) == (0.45, 0.1875)
    assert modules.place_tokens(GRID, {"cells": []}, [("a", 0, 0)]) == {}


@pytest.fixture
def mod_llm():
    return ScriptedLLM([])


@pytest.fixture
def mod_client(settings, mod_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(modules, "extract_text", lambda path: ("Неспокойные мертвецы. Склеп Давоса…" * 20, 8))
    s = dataclasses.replace(settings, media_dir=tmp_path / "media")
    import_base(s)
    with TestClient(create_app(s, llm=mod_llm, dice_factory=lambda: QueueDice([]))) as c:
        yield c


@pytest.fixture
def admin_m(mod_client):
    root = login(mod_client, "root", "rootpass")
    r = mod_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(mod_client, "Arty", "secret1")


def idle(client):
    client.portal.call(client.app.state.master.wait_idle, None)


def module_call(raw):
    return {"tool_calls": [(modules.TOOL, raw)]}


def map_call(location_id, marks, grid=None):
    return {"tool_calls": [(modules.MAP_TOOL, {"location_id": location_id, "marks": marks, "grid": grid})]}


def test_import_retries_reads_maps_and_publishes_a_pack(mod_client, admin_m, mod_llm, settings):
    client = mod_client
    bad = sample()
    bad["creatures"][0]["base_ref"] = "creature.nope"
    marks = [
        {"number": "1", "x": 0.3, "y": 0.4, "cells": [[0, 0, 4, 7]], "blocked": [[2, 3]]},
        {"number": "2", "x": 0.7, "y": 0.4},
    ]
    mod_llm.replies += [module_call(bad), module_call(sample()), map_call("location.davos_crypt", marks, GRID)]

    m = ok(client.post("/api/admin/modules?name=the-unquiet-dead.pdf", content=b"%PDF-1.4 book", headers=admin_m), 201)
    assert m["title"] == "the-unquiet-dead" and m["status"] == "reading"
    idle(client)
    # карта пришла после разбора книги: модель ищет номера сразу
    ok(client.post(f"/api/admin/modules/{m['id']}/maps?name=crypt.png", content=PNG, headers=admin_m), 201)
    idle(client)
    m = ok(client.get(f"/api/admin/modules/{m['id']}", headers=admin_m))
    assert m["status"] == "review" and m["title"] == "Неспокойные мертвецы", m
    assert m["draft"]["notes"] == ["Аристократу дано имя не из книги."]
    assert m["map_list"][0]["location_id"] == "location.davos_crypt" and m["map_list"][0]["status"] == "ok"

    # вторая попытка переводчика получила ошибки первой, карта ушла картинкой
    tool_msg = mod_llm.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "creature.nope" in tool_msg["content"]
    assert mod_llm.requests[0]["tool_choice"] == "required"
    image = mod_llm.requests[2]["messages"][1]["content"][1]
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    purposes = run(settings, lambda s: _purposes(s))
    assert purposes == ["module_import", "module_import", "module_map"]

    # админ поправил отметку руками; номер не из этого места — отказ с причиной
    url = f"/api/admin/modules/{m['id']}/maps/{m['map_list'][0]['id']}"
    r = client.put(
        url,
        json={"location_id": "location.davos_crypt", "marks": [{"number": "9", "x": 0.1, "y": 0.1}]},
        headers=admin_m,
    )
    assert r.status_code == 409 and "нет комнаты с номером '9'" in r.json()["detail"]
    assert m["map_list"][0]["grid"] == GRID and m["map_list"][0]["marks"][0]["blocked"] == [[2, 3]]
    fixed = [{"number": "1", "x": 0.25, "y": 0.4, "cells": [[0, 0, 4, 7]]}, {"number": "2", "x": 0.7, "y": 0.4}]
    ok(client.put(url, json={"location_id": "location.davos_crypt", "grid": GRID, "marks": fixed}, headers=admin_m))

    m = ok(client.post(f"/api/admin/modules/{m['id']}/publish", headers=admin_m))
    assert m["status"] == "published" and m["pack_id"] == "module-unquiet-dead" and m["pack_version"] == "1.0.0"
    # модуль не попадает в список пакетов мира
    assert all(p["id"] != "module-unquiet-dead" for p in ok(client.get("/api/packs", headers=admin_m)))

    async def catalog(s):
        cat = (await load_catalog(s, [["dnd5e-srd", "0.5.2"], ["module-unquiet-dead", "1.0.0"]])).view(False)
        statue = cat.get("creature.temple_statue")
        adv = cat.get("adventure.unquiet_dead", "adventure")
        return statue.data, adv.data

    statue, adv = run(settings, catalog)
    # существо модуля наследует числа SRD и меняет только то, что сказано в книге
    assert statue["hp"]["average"] == 30 and statue["ac"] == 17 and statue["actions"] and statue["cr"] == 1
    assert adv["maps"][0]["marks"][0] == {"number": "1", "x": 0.25, "y": 0.4, "cells": [[0, 0, 4, 7]], "blocked": []}
    assert adv["maps"][0]["grid"] == GRID
    assert adv["module_id"] == m["id"] and adv["xp"] == "milestone" and adv["plot"]["title"] == "Неспокойные мертвецы"

    img = client.get(f"/api/modules/{m['id']}/maps/{m['map_list'][0]['id']}", headers=admin_m)
    assert img.status_code == 200 and img.content == PNG
    # опубликованное не удаляется: на нём могут идти кампании; повторная публикация — новая версия
    assert client.delete(f"/api/admin/modules/{m['id']}", headers=admin_m).status_code == 409
    assert ok(client.post(f"/api/admin/modules/{m['id']}/publish", headers=admin_m))["pack_version"] == "1.0.1"


async def _purposes(s):
    from sqlalchemy import select

    rows = (await s.scalars(select(LlmCall).order_by(LlmCall.created_at))).all()
    return [r.purpose for r in rows]


def test_failed_import_shows_reason_and_can_be_rerun(mod_client, admin_m, mod_llm):
    client = mod_client
    mod_llm.replies += [{"text": "не буду"}, {"text": "не буду"}, {"text": "всё равно не буду"}]
    m = ok(client.post("/api/admin/modules?name=a.pdf", content=b"%PDF-1.4", headers=admin_m), 201)
    idle(client)
    m = ok(client.get(f"/api/admin/modules/{m['id']}", headers=admin_m))
    assert m["status"] == "failed" and "не вызвала submit_adventure_module" in m["error"]
    assert client.post(f"/api/admin/modules/{m['id']}/publish", headers=admin_m).status_code == 409

    mod_llm.replies += [module_call(sample())]
    ok(client.post(f"/api/admin/modules/{m['id']}/import", json={"note": "только склеп"}, headers=admin_m), 202)
    idle(client)
    m = ok(client.get(f"/api/admin/modules/{m['id']}", headers=admin_m))
    assert m["status"] == "review" and m["note"] == "только склеп"
    assert "Пожелание админа к разбору: только склеп" in mod_llm.requests[-1]["messages"][1]["content"]

    assert client.delete(f"/api/admin/modules/{m['id']}", headers=admin_m).status_code == 204
    assert ok(client.get("/api/admin/modules", headers=admin_m)) == []


def test_only_admin_uploads_and_files_are_checked(mod_client, admin_m):
    client = mod_client
    r = client.post("/api/admin/modules?name=a.txt", content=b"hello", headers=admin_m)
    assert r.status_code == 409 and "это не PDF" in r.json()["detail"]
    from tests.test_api import invite, make_campaign, register

    c = make_campaign(client, admin_m, players=1)
    player = register(client, invite(client, admin_m, c["id"])["token"], "Гимли")
    assert client.get("/api/admin/modules", headers=player).status_code == 403
    assert client.post("/api/admin/modules?name=a.pdf", content=b"%PDF", headers=player).status_code == 403


def test_pdftotext_reads_a_real_pdf(tmp_path):
    if shutil.which("pdftotext") is None:
        pytest.skip("нет pdftotext")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_tiny_pdf("Unquiet dead " * 30))
    text, pages = modules.extract_text(pdf)
    assert pages == 1 and "Unquiet dead" in text


def _tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 8 Tf 10 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2000 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
