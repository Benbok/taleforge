import asyncio

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.agents.master.universal_lifecycle import open_universal_session
from app.db.models import Campaign, Message
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_session_intro_is_saved_once_without_catalog_or_model(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            c = await s.get(Campaign, "c")
            c.public_intro = "Исследуйте порт на парящих островах."
            await s.commit()
        provider = Provider([])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await open_universal_session(service, "c", "game")
        async with maker() as s:
            rows = list(await s.scalars(select(Message).where(Message.kind == "narration")))
            assert len(rows) == 1
            assert rows[0].content == "Исследуйте порт на парящих островах."
        assert not provider.prompts
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
