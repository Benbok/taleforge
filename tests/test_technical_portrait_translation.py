import asyncio

import pytest
from sqlalchemy import select

from app.agents.llm import LLMReply, ScriptedLLM
from app.config import Settings
from app.db.models import LlmCall
from tests.test_hero_portraits import PNG, setup_generator
from tests.universal_helpers import create_hero

ENGLISH = "An elven forest ranger, silver hair, green eyes, pointed ears, dark green cloak and leather armor."


def audits(client):
    async def read():
        async with client.app.state.sessionmaker() as session:
            return list(await session.scalars(select(LlmCall).where(LlmCall.purpose == "hero_portrait_translation")))

    return asyncio.run(read())


def test_translation_uses_technical_model_caches_result_and_accounts_separate_cost(client, root, tmp_path):
    from app.agents.portraits import ImageReply
    from app.agents.technical_portrait_translation import TechnicalPortraitTranslator

    fake = setup_generator(client, tmp_path)
    hero = create_hero(client, root)
    original = client.get(f"/api/me/characters/{hero}", headers=root).json()
    llm = ScriptedLLM([LLMReply(text=ENGLISH, tokens_in=50, tokens_out=20, cost=0.001, cost_known=True)])
    client.app.state.portrait_translator = TechnicalPortraitTranslator(
        llm, Settings(llm_provider="local", local_technical_model="portrait-translator")
    )
    descriptions = []

    async def image(description):
        descriptions.append(description)
        return ImageReply(PNG, "image/png", fake.model)

    fake.generate = image
    for key in ("first", "second"):
        response = client.post(
            f"/api/me/characters/{hero}/portrait", headers=root, json={"request_key": key, "expected_revision": 1}
        )
        assert response.status_code == 200, response.text
    assert len(llm.requests) == 1 and llm.requests[0]["model"] == "lm_studio/portrait-translator"
    assert llm.requests[0]["thinking"] is False
    assert descriptions[0]["appearance"] == ENGLISH and descriptions[0]["identity"] == ""
    assert descriptions[1] == descriptions[0]
    assert client.get(f"/api/me/characters/{hero}", headers=root).json()["sheet"] == original["sheet"]
    (audit,) = audits(client)
    assert audit.cost == 0.001 and audit.cost_known and audit.tokens_in == 50 and audit.error is None


@pytest.mark.parametrize(
    "reply",
    [
        LLMReply(text=""),
        LLMReply(text="эльфийка"),
        LLMReply(text=ENGLISH, finish_reason="length"),
        LLMReply(text=ENGLISH, blocked=True),
    ],
)
def test_bad_translation_never_starts_image_and_keeps_previous_portrait(client, root, tmp_path, reply):
    from app.agents.technical_portrait_translation import TechnicalPortraitTranslator

    fake = setup_generator(client, tmp_path)
    hero = create_hero(client, root)
    url = f"/api/me/characters/{hero}/portrait"
    before = client.post(url, headers=root, json={"request_key": "before", "expected_revision": 1}).json()
    client.app.state.portrait_translator = TechnicalPortraitTranslator(ScriptedLLM([reply]), Settings())
    response = client.post(url, headers=root, json={"request_key": "bad", "expected_revision": 1})
    assert response.status_code == 409 and fake.calls == 1
    assert client.get(f"/api/me/characters/{hero}", headers=root).json()["portrait_url"] == before["portrait_url"]
    assert audits(client)[0].error == "invalid_reply"


def test_english_description_does_not_call_translation_model(client):
    from app.agents.technical_portrait_translation import TechnicalPortraitTranslator

    llm = ScriptedLLM([])
    translator = TechnicalPortraitTranslator(llm, Settings())
    description = {"identity": "forest ranger", "appearance": "silver hair", "private_backstory": "SECRET"}

    async def check():
        async with client.app.state.sessionmaker() as session:
            assert await translator.translate(session, description) == description

    asyncio.run(check())
    assert llm.requests == [] and audits(client) == []


def test_translation_timeout_does_not_start_image_job(client, root, tmp_path):
    from app.agents.technical_portrait_translation import TechnicalPortraitTranslator

    fake = setup_generator(client, tmp_path)
    hero = create_hero(client, root)

    class Slow:
        async def complete(self, *args, **kwargs):
            await asyncio.Event().wait()

    client.app.state.portrait_translator = TechnicalPortraitTranslator(
        Slow(), Settings(portrait_translation_timeout_sec=0.02)
    )
    response = client.post(
        f"/api/me/characters/{hero}/portrait", headers=root, json={"request_key": "slow", "expected_revision": 1}
    )
    assert response.status_code == 409 and fake.calls == 0
    assert "перевода" in response.json()["detail"]


def test_translation_cost_belongs_to_creation_phase():
    from app.core.spend import session_report

    report = session_report(
        [
            LlmCall(
                purpose="hero_portrait_translation",
                model="technical",
                cost=0.001,
                tokens_in=50,
                tokens_out=20,
                turn_id=None,
            )
        ],
        [],
    )
    assert report["by_phase"]["creation"]["cost"] == 0.001
