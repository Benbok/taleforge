"""Retained admission and privacy protections exercised through current APIs."""

import pytest

from app.db.models import Campaign, HeroDialogue, MasterTurn, Scene
from tests.game import import_base, ok, party, run
from tests.universal_helpers import DESCRIPTION, create_hero, ready_reply, set_replies


@pytest.mark.parametrize("boundary", ["active", "ended", "combat", "turn"])
@pytest.mark.parametrize("entry", ["dialogue", "library"])
def test_admission_refuses_busy_or_finished_campaign_without_creating_copy(client, admin, settings, boundary, entry):
    import_base(settings)
    campaign, (_, player), _ = party(client, admin, players=2, start=False)
    library_id = create_hero(client, player) if entry == "library" else None

    async def arrange(session):
        c = await session.get(Campaign, campaign["id"])
        if boundary in {"active", "ended"}:
            c.status = boundary
        elif boundary == "combat":
            scene = await session.get(Scene, c.id)
            scene.mode = "combat"
        else:
            session.add(MasterTurn(campaign_id=c.id, upto_seq=0, status="running", trace={}))
        await session.commit()

    run(settings, arrange)
    set_replies(client, [ready_reply()])
    if entry == "dialogue":
        response = client.post(
            "/api/hero-creation/dialogues",
            headers=player,
            json={"campaign_id": campaign["id"], "description": DESCRIPTION},
        )
    else:
        response = client.post(f"/api/campaigns/{campaign['id']}/characters/from-library/{library_id}", headers=player)
    assert response.status_code == 409, response.text
    from sqlalchemy import select

    from app.db.models import Character

    async def check(session):
        return list(await session.scalars(select(Character).where(Character.campaign_id == campaign["id"])))

    assert len(run(settings, check)) == 1


def test_confirmation_rechecks_campaign_after_saved_dialogue(client, admin, settings):
    import_base(settings)
    campaign, (_, player), _ = party(client, admin, players=2, start=False)
    set_replies(client, [ready_reply()])
    draft = ok(
        client.post(
            "/api/hero-creation/dialogues",
            headers=player,
            json={"campaign_id": campaign["id"], "description": DESCRIPTION},
        ),
        201,
    )

    async def arrange(session):
        c = await session.get(Campaign, campaign["id"])
        c.status = "active"
        await session.commit()

    run(settings, arrange)
    response = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=player,
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 409, response.text

    async def check(session):
        saved = await session.get(HeroDialogue, draft["id"])
        return saved.status, saved.hero_id

    assert run(settings, check) == ("ready", None)


def test_concurrent_confirmations_never_add_two_heroes_or_two_admission_receipts(client, admin, settings):
    import asyncio

    import httpx
    from sqlalchemy import select

    from app.db.models import Character, Event

    import_base(settings)
    campaign, (_, player), _ = party(client, admin, players=2, start=False)
    set_replies(client, [ready_reply()])
    draft = ok(
        client.post(
            "/api/hero-creation/dialogues",
            headers=player,
            json={"campaign_id": campaign["id"], "description": DESCRIPTION},
        ),
        201,
    )

    async def race():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as http:
            return await asyncio.gather(
                *[
                    http.post(
                        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
                        headers=player,
                        json={"expected_revision": draft["revision"]},
                    )
                    for _ in range(2)
                ]
            )

    responses = client.portal.call(race)
    assert any(response.status_code == 200 for response in responses)
    assert all(response.status_code in {200, 409} for response in responses)

    async def check(session):
        heroes = list(await session.scalars(select(Character).where(Character.campaign_id == campaign["id"])))
        receipts = list(
            await session.scalars(
                select(Event).where(Event.campaign_id == campaign["id"], Event.tool == "universal_catchup")
            )
        )
        return len(heroes), len(receipts)

    assert run(settings, check) == (2, 2)
