import asyncio

from sqlalchemy import select

from app.db.models import LlmCall
from tests.universal_helpers import DESCRIPTION, PROPOSAL, ready_reply, set_replies

BASE = '/api/hero-creation/dialogues'


def test_identity_only_starts_dialogue_and_confirm_once(client, root):
    set_replies(client, [ready_reply(description={'identity': 'Техномаг'}, question='Вы опираетесь на инженерию или магию?',
                                     proposal=None), ready_reply()])
    draft = client.post(BASE, headers=root, json={'description': {'identity': 'Техномаг'}})
    assert draft.status_code == 201, draft.text
    draft = draft.json()
    assert draft['status'] == 'questions'
    assert client.post(f'{BASE}/{draft["id"]}/confirm', headers=root,
                        json={'expected_revision': draft['revision']}).status_code == 409
    ready = client.post(f'{BASE}/{draft["id"]}/answers', headers=root,
                        json={'expected_revision': draft['revision'], 'answer': 'Магия растений и опыт походов'})
    assert ready.status_code == 200, ready.text
    ready = ready.json()
    reloaded = client.get(f'{BASE}/{draft["id"]}', headers=root).json()
    assert reloaded == ready
    assert len(client.app.state.hero_llm.requests) == 2
    assert client.post(f'{BASE}/{draft["id"]}/confirm', headers=root,
                        json={'expected_revision': draft['revision']}).status_code == 409
    confirmation = {'expected_revision': ready['revision']}
    first = client.post(f'{BASE}/{draft["id"]}/confirm', headers=root, json=confirmation)
    again = client.post(f'{BASE}/{draft["id"]}/confirm', headers=root, json=confirmation)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    cards = client.get('/api/me/characters', headers=root).json()
    assert len(cards) == 1
    assert cards[0]['level'] == '1' and cards[0]['sheet']['xp'] == '0'
    assert cards[0]['sheet']['budget']['growth_total'] == '0'
    assert sorted(map(int, cards[0]['sheet']['abilities'].values())) == [8, 10, 12, 13, 14, 15]


def test_bad_or_failed_model_preserves_draft_and_logs_usage(client, root):
    set_replies(client, [ready_reply(), {'text': 'invalid JSON'}])
    draft = client.post(BASE, headers=root, json={'description': DESCRIPTION}).json()
    before = client.get(f'{BASE}/{draft["id"]}', headers=root).json()
    failed = client.post(f'{BASE}/{draft["id"]}/answers', headers=root,
                         json={'expected_revision': draft['revision'], 'answer': 'Изменить замысел'})
    assert failed.status_code == 409
    assert client.get(f'{BASE}/{draft["id"]}', headers=root).json() == before
    from tests.test_profile import signup
    other = signup(client, 'Другой')
    assert client.get(f'{BASE}/{draft["id"]}', headers=other).status_code == 404
    assert client.post(f'{BASE}/{draft["id"]}/confirm', headers=other,
                        json={'expected_revision': draft['revision']}).status_code == 404

    async def logs():
        async with client.app.state.sessionmaker() as session:
            rows = (await session.scalars(select(LlmCall).where(LlmCall.purpose == 'hero_creation'))).all()
            assert len(rows) == 2
            assert rows[1].error
    asyncio.run(logs())


def test_model_cannot_inflate_array(client, root):
    set_replies(client, [ready_reply(proposal={**PROPOSAL, 'abilities': dict.fromkeys(PROPOSAL['abilities'], '15')})])
    response = client.post(BASE, headers=root, json={'description': DESCRIPTION})
    assert response.status_code == 409
    assert client.get('/api/me/characters', headers=root).json() == []
    assert len(client.get(BASE, headers=root).json()) == 1


def test_direct_campaign_and_admin_premade_start_at_level_one(client, root):
    from app.db.models import Character
    from tests.test_api import make_campaign

    campaign = make_campaign(client, root, owner_plays=True)
    for target in (None, 'premade'):
        set_replies(client, [ready_reply()])
        draft = client.post(BASE, headers=root, json=dict(description=DESCRIPTION,
                            campaign_id=campaign['id'], target_id=target))
        assert draft.status_code == 201, draft.text
        draft = draft.json()
        response = client.post(f'{BASE}/{draft["id"]}/confirm', headers=root,
                               json={'expected_revision': draft['revision']})
        assert response.status_code == 200, response.text

        async def check():
            async with client.app.state.sessionmaker() as session:
                ch = await session.get(Character, response.json()['hero_id'])
                assert ch.sheet['level'] == '1'
                assert ch.sheet['xp'] == '0'
                assert ch.sheet['unspent_points'] == '0'
        asyncio.run(check())
