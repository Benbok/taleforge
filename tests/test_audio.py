"""Звук сцены (design/audio-mixer.md): библиотека в папке, музыка по настроению, эффекты на события, рассылка."""

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
        "bpm": 100,  # поле старого микшера: читается без ошибки
    },
    {"id": "mel_fast", "file": "mel_fast.ogg", "layer": "music", "title": "Спешка", "moods": ["tension"]},
    {"id": "mel_fast2", "file": "mel_fast2.ogg", "layer": "music", "title": "Бег", "moods": ["tension"]},
    {"id": "rhy_war", "file": "rhy_war.ogg", "layer": "rhythm", "title": "Барабаны", "moods": ["battle"]},
    {
        "id": "mel_hold",
        "file": "mel_hold.ogg",
        "layer": "music",
        "title": "Трюм",
        "moods": ["dread"],
        "packs": ["echo-leviathans"],
    },
    {"id": "sfx_thunder", "file": "sfx_thunder.ogg", "layer": "sfx", "title": "Гром"},
    {"id": "stg_victory", "file": "stg_victory.ogg", "layer": "sfx", "title": "Победа", "cue": "victory"},
    {"id": "sfx_bell", "file": "sfx_bell.ogg", "layer": "sfx", "title": "Набат", "cue": ["combat", "death"]},
    {"id": "sfx_crit", "file": "sfx_crit.ogg", "layer": "sfx", "title": "Хруст", "cue": "crit"},
    {"id": "stg_act", "file": "stg_act.ogg", "layer": "sfx", "title": "Заставка", "cue": ["act", "place"]},
    {"id": "sfx_secret", "file": "sfx_secret.ogg", "layer": "sfx", "title": "Тайна", "cue": "secret"},
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
    assert lib.get("rhy_war").layer == "music"  # ритм старого микшера — просто музыка
    assert lib.get("sfx_bell").cues == ["combat", "death"]
    # мир кампании: сначала его треки, потом общие; треки чужих миров не видны
    assert [t.id for t in lib.for_pack("echo-leviathans") if t.layer == "music"][0] == "mel_hold"
    assert "mel_hold" not in [t.id for t in lib.for_pack("other")]


def test_cue_only_for_effects():
    with pytest.raises(Exception, match="только у эффектов"):
        audio.parse_card({"id": "x", "file": "x.ogg", "layer": "music", "title": "x", "cue": "crit"})
    with pytest.raises(Exception, match="неизвестные события"):
        audio.parse_card({"id": "x", "file": "x.ogg", "layer": "sfx", "title": "x", "cue": "boom"})


def test_admin_uploads_into_folder(client, admin, tmp_path):
    data = ok(client.get("/api/admin/audio", headers=admin))
    assert len(data["tracks"]) == len(CARDS) and "battle" in data["moods"]
    r = client.post("/api/admin/audio/files?name=Гроза Ночь.ogg", content=b"OggS-new", headers=admin)
    name = ok(r, 201)["file"]
    assert (tmp_path / "audio" / name).is_file()
    assert name in ok(client.get("/api/admin/audio", headers=admin))["unsorted"]
    bad = client.put("/api/admin/audio/tracks/storm", json={"file": name, "layer": "noise"}, headers=admin)
    assert bad.status_code == 409 and "вид" in bad.json()["detail"]
    card = {"file": name, "layer": "sfx", "title": "Гроза", "cue": ["hazard"], "packs": ["echo-leviathans"]}
    ok(client.put("/api/admin/audio/tracks/storm", json=card, headers=admin))
    saved = yaml.safe_load((tmp_path / "audio" / "tracks.yaml").read_text(encoding="utf-8"))
    assert saved[-1]["id"] == "storm" and saved[-1]["packs"] == ["echo-leviathans"] and saved[-1]["cue"] == "hazard"
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


def test_music_tool_picks_track_by_mood(game):
    settings, cid, hero, _ = game

    async def fn(ctx):
        r1 = await execute(ctx, "set_music", {"mood": "calm", "reason": "отдых"})
        r2 = await execute(ctx, "set_music", {"mood": "warm", "reason": "тот же трек"})  # трек подходит — не меняется
        r3 = await execute(ctx, "set_music", {"mood": "tension", "reason": "спешка"})
        r4 = await execute(ctx, "set_music", {"mood": "dread", "reason": "чужой мир"})
        r5 = await execute(ctx, "play_sfx", {"sfx": "sfx_thunder"})
        r6 = await execute(ctx, "play_sfx", {"sfx": "sfx_crit"})  # эффект события играет движок
        return r1, r2, r3, r4, r5, r6, audio.public_state(ctx.campaign, ctx.world.scene), list(ctx.audio)

    r1, r2, r3, r4, r5, r6, state, cues = play(settings, cid, fn)
    assert r1["ok"] and r1["result"]["playing"] == "Тёплый отсек"
    assert r2["ok"]
    assert not r3["ok"] and "сменилась" in r3["error"]  # музыка не дёргается чаще раза в минуту
    assert not r4["ok"] and "dread" in r4["error"]  # музыка другого мира кампании недоступна
    assert r5["ok"] and cues[0]["id"] == "sfx_thunder"
    assert not r6["ok"]
    assert state["enabled"] and state["music"]["id"] == "mel_rest" and state["music"]["mood"] == "warm"
    assert state["music"]["url"].startswith("/api/audio/mel_rest?v=")


def test_combat_music_and_cues(game):
    settings, cid, hero, _ = game

    async def fn(ctx):
        await execute(ctx, "set_music", {"mood": "calm", "reason": "отдых"})
        await execute(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero]})
        fight = audio.mixer(ctx.world.scene)["music"]
        audio.finalize(ctx)
        start = [c["id"] for c in ctx.audio]
        ctx.audio.clear()
        await execute(ctx, "set_scene_mode", {"mode": "free"})
        audio.finalize(ctx)
        return fight, start, audio.mixer(ctx.world.scene)["music"], [c["id"] for c in ctx.audio]

    fight, start, after, end = play(settings, cid, fn)
    assert fight["track"] == "rhy_war" and fight["mood"] == "battle"
    assert start == ["sfx_bell"]  # начало боя
    assert after["track"] == "mel_rest"  # бой кончился — музыка места
    assert end == ["stg_victory"]


def test_event_cues_by_priority(game):
    """Эффекты на события хода: важные первыми, не больше двух; скрытые броски не звучат."""
    settings, cid, hero, _ = game

    async def fn(ctx):
        await ctx.record("resolve_attack", payload={"hit": True, "critical": True})
        await ctx.record("roll_check", payload={"critical": "success"}, hidden=True)
        audio.finalize(ctx)
        return [c["id"] for c in ctx.audio]

    assert play(settings, cid, fn) == ["sfx_crit"]


def test_story_cues_and_new_place(game):
    """Сюжетные события скрыты от игроков текстом, но звучат; заставка — на первый приход в место."""
    settings, cid, hero, _ = game

    async def fn(ctx):
        await ctx.record("end_act", payload={}, hidden=True)
        await ctx.record("plot_reveal", payload={}, hidden=True)
        audio.finalize(ctx)
        first = [c["id"] for c in ctx.audio]
        ctx.audio.clear()
        ctx.events.clear()
        audio.finalize(ctx)  # то же место второй раз — без заставки
        again = [c["id"] for c in ctx.audio]
        ctx.audio.clear()
        r = await execute(
            ctx, "create_location", {"name": "Кабак", "template_id": "location.tavern", "make_current": True}
        )
        assert r["ok"], r
        audio.finalize(ctx)
        return first, again, [c["id"] for c in ctx.audio]

    first, again, moved = play(settings, cid, fn)
    assert first == ["stg_act", "sfx_secret"] and again == [] and moved == ["stg_act"]


def test_no_repeat_and_owner_swaps_track(client, admin, game):
    """Музыка одного настроения не повторяется подряд; «Сменить трек» берёт другую того же настроения."""
    settings, cid, _, (p1,) = game

    async def fn(ctx):
        await execute(ctx, "set_music", {"mood": "tension", "reason": "спешка"})
        cur = audio.current(ctx.world.scene)
        audio.set_music(ctx.world.scene, None)
        return cur.id, audio.choose(ctx, "tension").id  # только что звучавший трек — не подряд

    first, nxt = play(settings, cid, fn)
    assert {first, nxt} == {"mel_fast", "mel_fast2"}

    async def put(ctx):
        audio.set_music(ctx.world.scene, audio.library().get("mel_fast"), "tension")
        ctx.signals.add("audio")

    play(settings, cid, put)
    assert client.post(f"/api/campaigns/{cid}/audio/next", headers=p1).status_code == 403
    with connect(client, p1, cid) as (ws, snap):
        was = snap["payload"]["audio"]["music"]["title"]
        r = ok(client.post(f"/api/campaigns/{cid}/audio/next", headers=admin))
        e = next_of(ws, "audio.state")
    assert e["payload"]["music"]["title"] == r["title"]
    assert {was, r["title"]} == {"Спешка", "Бег"}  # другой трек того же настроения


def test_disabled_campaign_hides_tools(client, admin, game):
    settings, cid, _, _ = game
    ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": False}, headers=admin))

    async def fn(ctx):
        from app.agents.master import decision_tools

        names = decision_tools(ctx)
        r = await execute(ctx, "set_music", {"mood": "calm", "reason": "x"})
        return names, r, audio.prompt_block(ctx.campaign, ctx.world.scene)

    names, r, block = play(settings, cid, fn)
    assert "set_music" not in names and "play_sfx" not in names
    assert not r["ok"] and block == ""


def test_specs_list_moods_and_sfx(game):
    settings, cid, _, _ = game

    async def fn(ctx):
        return tool_specs(ctx.world, ["set_music", "play_sfx"]), audio.prompt_block(ctx.campaign, ctx.world.scene)

    specs, block = play(settings, cid, fn)
    mood = specs[0]["function"]["parameters"]["properties"]["mood"]
    assert mood["enum"] == ["calm", "warm", "tension", "battle", "off"]  # dread — только у музыки чужого мира
    assert specs[1]["function"]["parameters"]["properties"]["sfx"]["enum"] == ["sfx_thunder"]  # события — не мастеру
    assert "calm — покой" in block and "sfx_thunder — Гром" in block and "mel_hold" not in block


# --- сокет и ход ИИ-мастера ---


def test_snapshot_and_broadcast(client, admin, game, llm):
    _, cid, hero, (p1,) = game
    llm.replies += [
        {
            "tool_calls": [
                ("set_music", {"mood": "calm", "reason": "отдых"}),
                ("play_sfx", {"sfx": "sfx_thunder"}),
            ]
        },
        {"tool_calls": [("auto_success", {"character_id": hero, "reason": "садится"})]},
        {"text": "готово"},
        {"text": "За окном гремит гром."},
    ]
    with connect(client, p1, cid) as (ws, snap):
        assert snap["payload"]["audio"]["enabled"] and snap["payload"]["audio"]["music"] is None
    n = act(client, p1, cid, "Сажусь у огня")
    assert n["kind"] == "narration"
    decide = llm.requests[0]
    assert "Звук." in decide["messages"][0]["content"] and "calm — покой" in decide["messages"][0]["content"]
    with connect(client, p1, cid) as (ws, snap):
        assert snap["payload"]["audio"]["music"]["id"] == "mel_rest"
        ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": False}, headers=admin))
        e = next_of(ws, "audio.state")
        assert not e["payload"]["enabled"] and e["payload"]["music"] is None


def test_autopilot_starts_music_for_place_and_respects_master(game):
    """Мастер забыл про звук: движок включает мелодию под место; свой выбор мастера и его тишину не трогает."""
    settings, cid, _, _ = game

    async def fn(ctx):
        r = await execute(
            ctx, "create_location", {"name": "Кабак", "template_id": "location.tavern", "make_current": True}
        )
        assert r["ok"], r
        words = audio.place_words(ctx, None)
        audio.autopilot(ctx)
        first = audio.mixer(ctx.world.scene)["music"]
        await execute(ctx, "set_music", {"mood": "off", "reason": "тишина перед бурей"})
        audio.autopilot(ctx)  # в этом ходе мастер звук вёл сам
        ctx.events.clear()
        audio.autopilot(ctx)  # и следующий ход: тишина выбрана им недавно
        return words, first, audio.mixer(ctx.world.scene)["music"], "audio" in ctx.signals

    words, first, after, signal = play(settings, cid, fn)
    assert "tavern" in words and first["track"] == "mel_rest" and after is None and signal


def test_autopilot_off_when_sound_disabled(client, admin, game):
    settings, cid, _, _ = game
    ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": False}, headers=admin))

    async def fn(ctx):
        audio.autopilot(ctx)
        return audio.mixer(ctx.world.scene)["music"]

    assert play(settings, cid, fn) is None
