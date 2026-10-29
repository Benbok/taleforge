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
