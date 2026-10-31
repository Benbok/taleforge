import asyncio

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.agents.master.universal_lifecycle import open_universal_session
from app.db.models import Campaign, Message
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_master_status_is_scoped_and_cleared_after_session_intro(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        service = MasterService(maker, Bus(), Provider([]))
        service._audience["c"] = ["seat"]
        await service._status("c", "rolling")
        assert service.current_stage("c", "seat") == "rolling"
        assert service.current_stage("c", "foreign-seat") is None
        await service._status("c", "idle")
        assert service.current_stage("c", "seat") is None
        service._audience.pop("c")
        service.schedule_session_open("c", "game")
        await service.wait_idle("c")
        assert service.current_stage("c", "seat") is None
        await engine.dispose()

    asyncio.run(run())


def test_session_intro_is_saved_once_and_only_the_greeting_needs_the_model(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            c = await s.get(Campaign, "c")
            c.public_intro = "Исследуйте порт на парящих островах."
            await s.commit()
        provider = Provider(["Тайны мира.", "Добро пожаловать к столу."])  # secrets, then the greeting
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await open_universal_session(service, "c", "game")
        async with maker() as s:
            rows = list(await s.scalars(select(Message).where(Message.kind == "narration").order_by(Message.seq)))
            assert [r.content for r in rows] == ["Исследуйте порт на парящих островах.", "Добро пожаловать к столу."]
        assert len(provider.prompts) == 2
        await engine.dispose()

    asyncio.run(run())


def test_private_question_needs_no_catalog_and_answer_stays_private(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            source = Message(
                id="whisper",
                campaign_id="c",
                session_id="game",
                seq=2,
                kind="whisper",
                seat_id="seat",
                author_user_id="u",
                content="Где я?",
                visible_to=["seat", "master"],
                data={"answer": "pending"},
            )
            s.add(source)
            (await s.get(Campaign, "c")).last_seq = 2
            await s.commit()
        provider = Provider(["Вы у ворот порта."])
        service = MasterService(maker, Bus(), provider)
        ids = await service.answer_whispers("c")
        assert len(ids) == 1
        async with maker() as s:
            reply = await s.get(Message, ids[0])
            assert set(reply.visible_to) == {"seat", "master"}
            assert (await s.get(Message, "whisper")).data["answer"] == "answered"
        assert "HIDDEN-SECRET" not in str(provider.prompts)
        await engine.dispose()

    asyncio.run(run())


async def _table(maker):
    """The seated hero gets a public bio and a private backstory; the secret plot sits in the campaign secrets."""
    from app.db.models import CampaignSecret, Character

    async with maker() as s:
        hero = await s.get(Character, "hero")
        hero.name = "Мира"
        hero.public_bio = "Бывшая лодочница с Озёрного края"
        hero.private_backstory = "HERO-PRIVATE: убила брата"
        c = await s.get(Campaign, "c")
        c.name = "Кольцо власти"
        c.public_intro = "Шир ждёт."
        secret = await s.get(CampaignSecret, "c")
        secret.setting = {
            "studio": {
                "premise": "Путь Кольца",
                "world": "Средиземье",
                "laws": "Кольцо искажает носителя",
                "style": "Героический эпос",
                "history": "Эпохи сменяли друг друга",
                "start": "Трактир в Байуотере",
                "secret_text": "WORLD-SECRET: хозяин трактира шпион",
            }
        }
        await s.commit()


def test_session_opening_greets_the_table_and_weaves_in_the_heroes_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _table(maker)
        provider = Provider(["Добро пожаловать, друзья! Мира, у стойки тебя ждёт знакомый лодочник."])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await open_universal_session(service, "c", "game")  # the second start adds nothing
        async with maker() as s:
            rows = list(await s.scalars(select(Message).where(Message.kind == "narration").order_by(Message.seq)))
            assert [r.content for r in rows][0] == "Шир ждёт."  # the authored intro stays first
            assert rows[1].content.startswith("Добро пожаловать")
            assert rows[1].visible_to is None or rows[1].visible_to == []  # said to the whole table
            assert len(rows) == 2
        assert len(provider.prompts) == 1
        prompt = str(provider.prompts[0])
        assert "Мира" in prompt and "лодочница" in prompt and "Кольцо искажает носителя" in prompt
        assert "HERO-PRIVATE" not in prompt and "WORLD-SECRET" not in prompt and "HIDDEN-SECRET" not in prompt
        await engine.dispose()

    asyncio.run(run())


def test_a_failed_opening_does_not_block_the_session_and_is_retried_at_the_next_start(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _table(maker)
        provider = Provider([RuntimeError("provider down"), "Добро пожаловать после сбоя."])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        async with maker() as s:
            rows = list(await s.scalars(select(Message).where(Message.kind == "narration")))
            assert [r.content for r in rows] == ["Шир ждёт."]  # the session opened without the greeting
        assert await open_universal_session(service, "c", "game")
        async with maker() as s:
            rows = list(await s.scalars(select(Message).where(Message.kind == "narration").order_by(Message.seq)))
            assert rows[-1].content == "Добро пожаловать после сбоя."
        await engine.dispose()

    asyncio.run(run())


def test_a_player_turn_waits_for_the_session_greeting(tmp_path):
    from app.agents.master.universal import run_universal_turn

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider([])
        service = MasterService(maker, Bus(), provider)
        async with service.intro_lock("c"):  # the greeting is being written
            turn = asyncio.create_task(run_universal_turn(service, "c"))
            await asyncio.sleep(0.2)
            assert not turn.done() and not provider.prompts  # the master does not answer over the greeting
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await engine.dispose()

    asyncio.run(run())


async def _studio(maker, **extra):
    from app.db.models import CampaignSecret

    async with maker() as s:
        secret = await s.get(CampaignSecret, "c")
        secret.setting = {
            "studio": {"premise": "Путь Кольца", "world": "Средиземье", "laws": "Кольцо искажает", **extra}
        }
        await s.commit()


async def _stored_secret(maker):
    from app.db.models import CampaignSecret

    async with maker() as s:
        return ((await s.get(CampaignSecret, "c")).setting or {}).get("studio", {}).get("secret_text", "")


def test_empty_master_secrets_are_invented_before_the_greeting_once_and_stay_private(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _studio(maker)
        provider = Provider(["SECRET-1: хозяин трактира служит Тени.", "Добро пожаловать к столу."])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await open_universal_session(service, "c", "game")  # nothing more is asked
        assert len(provider.prompts) == 2
        assert await _stored_secret(maker) == "SECRET-1: хозяин трактира служит Тени."
        assert "Кольцо искажает" in str(provider.prompts[0])  # invented from the world facts
        assert "SECRET-1" not in str(provider.prompts[1])  # the greeting never hears the secrets
        async with maker() as s:
            texts = [m.content for m in await s.scalars(select(Message).where(Message.kind == "narration"))]
            assert not any("SECRET-1" in t for t in texts)  # and the table never reads them
        await engine.dispose()

    asyncio.run(run())


def test_author_written_secrets_are_never_replaced(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _studio(maker, secret_text="Авторская тайна")
        provider = Provider(["Добро пожаловать."])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert len(provider.prompts) == 1  # only the greeting
        assert await _stored_secret(maker) == "Авторская тайна"
        await engine.dispose()

    asyncio.run(run())


def test_failed_secret_invention_does_not_block_the_session_and_is_retried(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _studio(maker)
        provider = Provider(
            [
                RuntimeError("down"),  # the immediate second try fails too, so the session goes on without the plot
                RuntimeError("down"),
                "Добро пожаловать.",
                "SECRET-2: тайна",
            ]
        )
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await _stored_secret(maker) == ""
        assert await open_universal_session(service, "c", "game")
        assert await _stored_secret(maker) == "SECRET-2: тайна"
        await engine.dispose()

    asyncio.run(run())


def test_the_opening_is_told_who_is_in_the_place_and_never_a_hidden_one(tmp_path):
    """Found in play: the greeting brought in a guild elder who was not in the prepared scene, so the first question
    to him was answered by the innkeeper."""

    async def run():
        from app.db.models import Character, Entity
        from tests.test_universal_location_knowledge import place as put_hero_in_a_place

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await put_hero_in_a_place(maker)
        await _table(maker)
        async with maker() as s:
            place = (await s.get(Character, "hero")).location_id
            s.add(
                Entity(
                    id="en_keeper",
                    campaign_id="c",
                    kind="creature",
                    location_id=place,
                    name="Хозяин Брен",
                    description="Сухой жилистый трактирщик.",
                    state={"hostile": False},
                )
            )
            s.add(
                Entity(
                    id="en_spy",
                    campaign_id="c",
                    kind="creature",
                    location_id=place,
                    name="Скрытый соглядатай",
                    description="Прячется.",
                    state={"hostile": False, "hidden": True},
                )
            )
            await s.commit()
        provider = Provider(["Добро пожаловать."])
        await open_universal_session(MasterService(maker, Bus(), provider), "c", "game")
        prompt = str(provider.prompts[0])
        assert "Хозяин Брен" in prompt and "Скрытый соглядатай" not in prompt
        from app.agents.master.universal_lifecycle import OPENING_PROMPT

        assert "present" in OPENING_PROMPT
        await engine.dispose()

    asyncio.run(run())


def test_the_plot_is_invented_before_the_opening_scene_is_prepared(tmp_path, monkeypatch):
    """The scene's people should come from the plot, so the plot must exist when the scene is prepared."""

    async def run():
        import app.agents.master.universal_lifecycle as lifecycle
        import app.agents.master.world as world
        from tests.test_universal_location_knowledge import place as put_hero_in_a_place

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await put_hero_in_a_place(maker)
        async with maker() as s:
            c = await s.get(Campaign, "c")
            c.settings = {**c.settings, "universal_world_generation": True, "studio_entry_location_id": "gorge"}
            await s.commit()
        order = []

        async def secrets(service, cid):
            order.append("plot")

        async def scene(service, campaign, turn_id, location_id, **kwargs):
            order.append("scene")

        monkeypatch.setattr(lifecycle, "_invent_secrets", secrets)
        monkeypatch.setattr(world, "prepare_scene", scene)
        await open_universal_session(MasterService(maker, Bus(), Provider(["Привет."])), "c", "game")
        assert order[:2] == ["plot", "scene"]
        await engine.dispose()

    asyncio.run(run())


def test_the_plot_comes_with_a_cast_kept_beside_the_secret(tmp_path):
    """The people of the plot (hirer, enemies, witnesses) become data, so they can be brought into the world."""

    async def run():
        import json

        from app.agents.master.universal_lifecycle import _invent_secrets
        from app.db.models import CampaignSecret

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _table(maker)
        async with maker() as s:
            secret = await s.get(CampaignSecret, "c")
            secret.setting = {"studio": {**secret.setting["studio"], "secret_text": ""}}
            await s.commit()
        plot = {
            "secrets": "Тайны мира.",
            "cast": [
                {"name": "Годвин Тарп", "role": "цеховой старшина", "place": "кабачок у канатных дворов"},
                {"name": "", "role": "без имени не лицо", "place": "нигде"},
            ]
            + [{"name": f"Лицо {i}", "role": "горожанин", "place": "порт"} for i in range(12)],
        }
        await _invent_secrets(MasterService(maker, Bus(), Provider([json.dumps(plot, ensure_ascii=False)])), "c")
        async with maker() as s:
            setting = (await s.get(CampaignSecret, "c")).setting
            assert setting["studio"]["secret_text"] == "Тайны мира."
            cast = setting["cast"]
            assert cast[0] == {"name": "Годвин Тарп", "role": "цеховой старшина", "place": "кабачок у канатных дворов"}
            assert len(cast) == 8 and all(person["name"] for person in cast)  # nameless dropped, the cast is bounded
        await engine.dispose()

    asyncio.run(run())


def test_a_plot_written_as_plain_text_still_works_and_has_no_cast(tmp_path):
    async def run():
        from app.agents.master.universal_lifecycle import _invent_secrets
        from app.db.models import CampaignSecret

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await _table(maker)
        async with maker() as s:
            secret = await s.get(CampaignSecret, "c")
            secret.setting = {"studio": {**secret.setting["studio"], "secret_text": ""}}
            await s.commit()
        await _invent_secrets(MasterService(maker, Bus(), Provider(["Просто тайны без списка."])), "c")
        async with maker() as s:
            setting = (await s.get(CampaignSecret, "c")).setting
            assert setting["studio"]["secret_text"] == "Просто тайны без списка." and not setting.get("cast")
        await engine.dispose()

    asyncio.run(run())


def test_a_plot_reply_with_raw_line_breaks_inside_its_strings_is_still_read():
    """Found in play: the model wrote its paragraphs with real line breaks inside the JSON string; the strict
    reader gave up and the raw JSON became the text of the secrets."""
    from app.agents.master.universal_lifecycle import parse_plot

    person = '{"name": "Ольхер", "role": "старшина", "place": "кабачок"}'
    reply = "```json\n" + '{"secrets": "Первая тайна.\n\nВторая тайна.", "cast": [' + person + "]}" + "\n```"
    text, cast = parse_plot(reply)
    assert text == "Первая тайна.\n\nВторая тайна." and cast[0]["name"] == "Ольхер"


def test_one_failed_plot_call_is_tried_again_at_once_but_only_once(tmp_path):
    """Found in play: one empty model reply left the whole game without a plot until the next session start."""

    async def run():
        from app.agents.master.universal_lifecycle import _invent_secrets
        from app.db.models import CampaignSecret

        for replies, expected in (
            ([RuntimeError("empty"), "Тайны со второй попытки."], "Тайны со второй попытки."),
            ([RuntimeError("empty"), RuntimeError("empty"), "Третья не нужна."], ""),
        ):
            folder = tmp_path / ("a" if expected else "b")
            folder.mkdir()
            engine, maker = await setup(folder)
            await prepare(maker)
            await _table(maker)
            async with maker() as s:
                secret = await s.get(CampaignSecret, "c")
                secret.setting = {"studio": {**secret.setting["studio"], "secret_text": ""}}
                await s.commit()
            provider = Provider(replies)
            await _invent_secrets(MasterService(maker, Bus(), provider), "c")
            async with maker() as s:
                got = ((await s.get(CampaignSecret, "c")).setting["studio"]).get("secret_text", "")
                assert got == expected
            await engine.dispose()

    asyncio.run(run())


def test_a_cut_off_plot_is_a_failed_try_not_the_text_of_the_secrets(tmp_path):
    """Found in play: the model spent nearly all its budget thinking and the JSON stopped mid-word; the stump was
    saved as the plot."""

    async def run():
        from app.agents.master.universal_lifecycle import _invent_secrets, parse_plot
        from app.db.models import CampaignSecret

        stump = (
            '{"secrets": "Мастера живы. Старшина знала и молчала, она подписала бумаги, по которым уходили «на сторон'
        )
        try:
            parse_plot(stump)
        except ValueError:
            pass
        else:
            raise AssertionError("a cut-off JSON must not be accepted as a plot")
        good = '{"secrets": "Целые тайны.", "cast": [{"name": "Ольхер", "role": "старшина", "place": "кабачок"}]}'
        for replies, expected in (([stump, good], "Целые тайны."), ([stump, stump], "")):
            folder = tmp_path / ("ok" if expected else "bad")
            folder.mkdir()
            engine, maker = await setup(folder)
            await prepare(maker)
            await _table(maker)
            async with maker() as s:
                secret = await s.get(CampaignSecret, "c")
                secret.setting = {"studio": {**secret.setting["studio"], "secret_text": ""}}
                await s.commit()
            await _invent_secrets(MasterService(maker, Bus(), Provider(replies)), "c")
            async with maker() as s:
                got = ((await s.get(CampaignSecret, "c")).setting["studio"]).get("secret_text", "")
                assert got == expected
            await engine.dispose()

    asyncio.run(run())
