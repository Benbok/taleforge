"""Звук сцены (design/audio-mixer.md): библиотека в папке, выбор мастера инструментами, страховка боя, рассылка."""

import dataclasses

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.core import audio
from app.db.models import Campaign
from app.main import create_app
from app.tools.registry import execute, tool_specs
from app.tools.runtime import flush_outbox, open_context
from tests.conftest import login
from tests.game import QueueDice, import_base, ok, party, run
from tests.test_master import act
from tests.test_ws import connect, next_of

OGG = b"OggS-fake-loop"
CARDS = [
    {
        "id": "mel_rest",
        "file": "mel_rest.ogg",
        "layer": "music",
        "title": "Тёплый отсек",
        "hint": "покой",
        "moods": ["calm", "warm"],
        "places": ["tavern"],
        "bpm": 100,
        "bars": 16,
    },
    {"id": "mel_fast", "file": "mel_fast.ogg", "layer": "music", "title": "Спешка", "moods": ["tension"], "bpm": 130},
    {"id": "rhy_war", "file": "rhy_war.ogg", "layer": "rhythm", "title": "Барабаны", "moods": ["battle"], "bpm": 100},
    {"id": "amb_tavern", "file": "amb_tavern.ogg", "layer": "ambience", "title": "Таверна", "places": ["tavern"]},
    {"id": "amb_hold", "file": "amb_hold.ogg", "layer": "ambience", "title": "Трюм", "packs": ["echo-leviathans"]},
    {"id": "sfx_thunder", "file": "sfx_thunder.ogg", "layer": "sfx", "title": "Гром"},
    {"id": "stg_victory", "file": "stg_victory.ogg", "layer": "sfx", "title": "Победа", "cue": "victory"},
]


def fill(folder, cards=CARDS):
    folder.mkdir(parents=True, exist_ok=True)
    for c in cards:
        (folder / c["file"]).write_bytes(OGG)
    (folder / "tracks.yaml").write_text(yaml.safe_dump(cards, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def client(settings, tmp_path, llm):
    import_base(settings)
    fill(tmp_path / "audio")
    settings = dataclasses.replace(settings, audio_dir=tmp_path / "audio")
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        yield c


@pytest.fixture
def admin(client):
    root = login(client, "root", "rootpass")
    ok(client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
    return login(client, "Arty", "secret1")


@pytest.fixture
def game(client, admin, settings):
    c, heads, ch = party(client, admin)
    ok(client.patch(f"/api/campaigns/{c['id']}", json={"audio_enabled": True}, headers=admin))
    return settings, c["id"], ch["id"], heads


def play(settings, cid, fn):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


# --- библиотека ---


def test_library_reads_cards_and_unsorted(tmp_path):
    fill(tmp_path)
    (tmp_path / "new_loop.ogg").write_bytes(OGG)
    (tmp_path / "tracks.yaml").write_text(
        yaml.safe_dump([*CARDS, {"id": "bad", "file": "x.ogg", "layer": "noise"}]), encoding="utf-8"
    )
    lib = audio.Library(tmp_path)
    assert {t.id for t in lib.all()} == {c["id"] for c in CARDS}
    assert lib.unsorted() == ["new_loop.ogg"]
    assert any("noise" in e for e in lib.errors())
    # мир кампании: сначала его треки, потом общие; треки чужих миров не видны
    assert [t.id for t in lib.for_pack("echo-leviathans") if t.layer == "ambience"] == ["amb_hold", "amb_tavern"]
    assert [t.id for t in lib.for_pack("other") if t.layer == "ambience"] == ["amb_tavern"]


def test_tempo_fits():
    a, b = audio.parse_card(CARDS[0]), audio.parse_card(CARDS[2])
    fast = audio.parse_card(CARDS[1])
    free = audio.parse_card({"id": "x", "file": "x.ogg", "layer": "rhythm", "title": "x"})
    half = audio.parse_card({**CARDS[2], "id": "h", "bpm": 50})
    assert audio.tempo_fits(a, b) and audio.tempo_fits(a, half) and audio.tempo_fits(fast, free)
    assert not audio.tempo_fits(fast, b)


def test_admin_uploads_into_folder(client, admin, tmp_path):
    data = ok(client.get("/api/admin/audio", headers=admin))
    assert len(data["tracks"]) == len(CARDS) and "battle" in data["moods"]
    r = client.post("/api/admin/audio/files?name=Гроза Ночь.ogg", content=b"OggS-new", headers=admin)
    name = ok(r, 201)["file"]
    assert (tmp_path / "audio" / name).is_file()
    assert name in ok(client.get("/api/admin/audio", headers=admin))["unsorted"]
    bad = client.put("/api/admin/audio/tracks/storm", json={"file": name, "layer": "noise"}, headers=admin)
    assert bad.status_code == 409 and "слой" in bad.json()["detail"]
    card = {"file": name, "layer": "ambience", "title": "Гроза", "packs": ["echo-leviathans"]}
    ok(client.put("/api/admin/audio/tracks/storm", json=card, headers=admin))
    saved = yaml.safe_load((tmp_path / "audio" / "tracks.yaml").read_text(encoding="utf-8"))
    assert saved[-1]["id"] == "storm" and saved[-1]["packs"] == ["echo-leviathans"]
    assert client.get("/api/audio/storm", headers=admin).content == b"OggS-new"
    assert client.delete("/api/admin/audio/tracks/storm?delete_file=true", headers=admin).status_code == 204
    assert not (tmp_path / "audio" / name).exists()
    wrong = client.post("/api/admin/audio/files?name=song.flac", content=b"x", headers=admin)
    assert wrong.status_code == 409 and "OGG" in wrong.json()["detail"]


def test_player_cannot_manage_library(client, admin, game):
    _, _, _, (p1,) = game
    assert client.get("/api/admin/audio", headers=p1).status_code == 403
    assert client.get("/api/audio/mel_rest", headers=p1).content == OGG


# --- инструменты мастера ---


def test_soundscape_tool(game):
    settings, cid, hero, _ = game

    async def fn(ctx):
        r1 = await execute(ctx, "set_soundscape", {"music": "mel_rest", "ambience": "amb_tavern", "reason": "отдых"})
        r2 = await execute(ctx, "set_soundscape", {"rhythm": "rhy_war", "reason": "драка"})
        r3 = await execute(ctx, "set_soundscape", {"music": "mel_fast", "rhythm": "off", "reason": "спешка"})
        r4 = await execute(ctx, "set_soundscape", {"ambience": "amb_hold", "reason": "чужой мир"})
        r5 = await execute(ctx, "play_sfx", {"sfx": "sfx_thunder"})
        return r1, r2, r3, r4, r5, audio.public_state(ctx.campaign, ctx.world.scene), list(ctx.audio)

    r1, r2, r3, r4, r5, state, cues = play(settings, cid, fn)
    assert r1["ok"] and r1["result"]["playing"] == {"music": "mel_rest", "rhythm": "off", "ambience": "amb_tavern"}
    assert r2["ok"]
    assert not r3["ok"] and "сменилась" in r3["error"]  # мелодия не дёргается чаще раза в минуту
    assert not r4["ok"]  # трек другого мира кампании недоступен
    assert r5["ok"] and cues[0]["id"] == "sfx_thunder"
    assert state["enabled"] and state["layers"]["music"]["id"] == "mel_rest"
    assert state["layers"]["rhythm"]["url"].startswith("/api/audio/rhy_war?v=")


def test_tempo_mismatch_refused(game):
    settings, cid, _, _ = game

    async def fn(ctx):
        return await execute(ctx, "set_soundscape", {"music": "mel_fast", "rhythm": "rhy_war", "reason": "бой"})

    r = play(settings, cid, fn)
    assert not r["ok"] and "не ложится" in r["error"]


def test_combat_safety_net_and_victory(game):
    settings, cid, hero, _ = game

    async def fn(ctx):
        await execute(ctx, "set_soundscape", {"music": "mel_rest", "reason": "отдых"})
        await execute(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero]})
        on = audio.mixer(ctx.world.scene)["rhythm"]
        await execute(ctx, "set_scene_mode", {"mode": "free"})
        return on, audio.mixer(ctx.world.scene)["rhythm"], list(ctx.audio)

    on, off, cues = play(settings, cid, fn)
    assert on["track"] == "rhy_war" and off is None
    assert [c["id"] for c in cues] == ["stg_victory"]


def test_disabled_campaign_hides_tools(client, admin, game):
    settings, cid, _, _ = game
    ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": False}, headers=admin))

    async def fn(ctx):
        from app.agents.master import decision_tools

        names = decision_tools(ctx)
        r = await execute(ctx, "set_soundscape", {"music": "mel_rest", "reason": "x"})
        return names, r, audio.prompt_block(ctx.campaign, ctx.world.scene)

    names, r, block = play(settings, cid, fn)
    assert "set_soundscape" not in names and "play_sfx" not in names
    assert not r["ok"] and block == ""


def test_specs_list_tracks(game):
    settings, cid, _, _ = game

    async def fn(ctx):
        return tool_specs(ctx.world, ["set_soundscape", "play_sfx"]), audio.prompt_block(ctx.campaign, ctx.world.scene)

    specs, block = play(settings, cid, fn)
    music = specs[0]["function"]["parameters"]["properties"]["music"]
    assert music["enum"] == ["mel_rest", "mel_fast", "off"]
    assert specs[1]["function"]["parameters"]["properties"]["sfx"]["enum"] == ["sfx_thunder"]  # фразы — не мастеру
    assert "mel_rest — покой [calm, warm; tavern] 100 bpm" in block and "amb_hold" not in block


# --- сокет и ход ИИ-мастера ---


def test_snapshot_and_broadcast(client, admin, game, llm):
    _, cid, hero, (p1,) = game
    llm.replies += [
        {
            "tool_calls": [
                ("set_soundscape", {"music": "mel_rest", "reason": "отдых"}),
                ("play_sfx", {"sfx": "sfx_thunder"}),
            ]
        },
        {"tool_calls": [("auto_success", {"character_id": hero, "reason": "садится"})]},
        {"text": "готово"},
        {"text": "За окном гремит гром."},
    ]
    with connect(client, p1, cid) as (ws, snap):
        assert snap["payload"]["audio"]["enabled"] and snap["payload"]["audio"]["layers"]["music"] is None
    n = act(client, p1, cid, "Сажусь у огня")
    assert n["kind"] == "narration"
    decide = llm.requests[0]
    assert "Звук." in decide["messages"][0]["content"] and "mel_rest" in decide["messages"][0]["content"]
    with connect(client, p1, cid) as (ws, snap):
        assert snap["payload"]["audio"]["layers"]["music"]["id"] == "mel_rest"
        ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": False}, headers=admin))
        e = next_of(ws, "audio.state")
        assert not e["payload"]["enabled"] and e["payload"]["layers"]["music"] is None
