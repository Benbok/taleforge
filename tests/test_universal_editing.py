from concurrent.futures import ThreadPoolExecutor

from tests.universal_helpers import DESCRIPTION, PROPOSAL, SCORES, create_hero, ready_reply, set_replies


def test_manual_and_chat_share_budget_and_preview_does_not_mutate(client, root):
    hero_id = create_hero(client, root)
    url = f'/api/me/characters/{hero_id}'
    before = client.get(url, headers=root).json()
    for scores in (dict.fromkeys(SCORES, '15'), {**SCORES, 'str': '9', 'cha': '9'}):
        body = {'edit': {'base_scores': scores, 'expected_revision': before['revision']}, 'request_key': 'bad'}
        assert client.patch(url, headers=root, json=body).status_code == 422
        set_replies(client, [ready_reply(proposal={**PROPOSAL, 'abilities': scores})])
        assert client.post(url + '/edit-proposals', headers=root,
                            json={'message': 'Все характеристики выше', 'expected_revision': 1}).status_code == 409
    set_replies(client, [ready_reply(description={**DESCRIPTION, 'name': 'Новая Ива'})])
    proposal = client.post(url + '/edit-proposals', headers=root,
                           json={'message': 'Поменяй имя', 'expected_revision': 1})
    assert proposal.status_code == 201, proposal.text
    assert client.get(url, headers=root).json() == before
    confirmed = client.post(url + f'/edit-proposals/{proposal.json()["id"]}/confirm', headers=root,
                            json={'request_key': 'chat-one'})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['name'] == 'Новая Ива'
    assert confirmed.json()['sheet']['budget'] == before['sheet']['budget']
    assert client.get(url, headers=root).json() == confirmed.json()


def test_edit_replay_stale_revision_and_protected_fields(client, root):
    hero_id = create_hero(client, root)
    url = f'/api/me/characters/{hero_id}'
    edit = {'description_patch': {'appearance': 'Зелёный плащ'}, 'base_scores': {**SCORES, 'str': '12', 'dex': '8'},
            'expected_revision': 1}
    body = {'edit': edit, 'request_key': 'once'}
    first = client.patch(url, headers=root, json=body)
    assert first.status_code == 200, first.text
    assert first.json()['derived']['ac'] == '11'
    assert client.patch(url, headers=root, json=body).json() == first.json()
    assert client.patch(url, headers=root, json={**body, 'request_key': 'stale'}).status_code == 409
    assert client.patch(url, headers=root, json={'edit': {**edit, 'level': '10'}, 'request_key': 'hack'}).status_code == 422
    for key in ('xp', 'resources', 'budget', 'unspent_points'):
        assert client.patch(url, headers=root, json={'edit': {**edit, key: '100'},
                            'request_key': 'hack'}).status_code == 422
    assert client.put(url, headers=root, json={'name': 'bypass'}).status_code in (405, 409)
    assert client.post(url + '/roll-abilities', headers=root).status_code in (405, 409)


def test_parallel_updates_have_one_winner(client, root):
    hero_id = create_hero(client, root)
    url = f'/api/me/characters/{hero_id}'
    def save(name):
        return client.patch(url, headers=root, json={'edit': {'description_patch': {'name': name},
                            'expected_revision': 1}, 'request_key': name}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, ['Первый', 'Второй'])) == [200, 409]
    assert client.get(url, headers=root).json()['revision'] == 2


def test_campaign_card_edit_forbidden(client, root):
    from tests.test_api import make_campaign
    campaign = make_campaign(client, root, owner_plays=True)
    set_replies(client, [ready_reply()])
    draft = client.post('/api/hero-creation/dialogues', headers=root,
                        json={'description': DESCRIPTION, 'campaign_id': campaign['id']}).json()
    hero_id = client.post(f'/api/hero-creation/dialogues/{draft["id"]}/confirm', headers=root,
                          json={'expected_revision': draft['revision']}).json()['hero_id']
    url = f'/api/me/characters/{hero_id}'
    assert client.patch(url, headers=root, json={'edit': {'description_patch': {'name': 'Hack'},
                        'expected_revision': 1}, 'request_key': 'hack'}).status_code == 404
    assert client.post(url + '/edit-proposals', headers=root,
                        json={'message': 'hack', 'expected_revision': 1}).status_code == 404
    legacy = f'/api/campaigns/{campaign["id"]}/characters/{hero_id}'
    assert client.put(legacy, headers=root, json={'name': 'Hack'}).status_code == 409
