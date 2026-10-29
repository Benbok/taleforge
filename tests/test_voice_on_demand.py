# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Озвучка текста мастера по кнопке: текст появляется сразу, голос синтезируется только по просьбе игрока."""

from app.core.chat import next_seq
from app.db.models import Campaign, Message
from tests.game import party
from tests.test_master import admin_g, dice, game_client, llm, rows, run  # noqa: F401 — фикстуры


class FakeTTS:
    def __init__(self):
        self.texts = []

    def get_engine(self, provider):
        return self

    enabled = True

    async def voice_for_narration(self, media_dir, campaign_id, text, provider=None, voice_name=None):
        self.texts.append(text)
        return {"id": f"v{len(self.texts)}", "duration": 2.0}


def narration(game_client, settings, cid, *, text="Серое утро над Широм.\n\nПтицы смолкли.", enabled=True):
    master = game_client.app.state.master
    master.tts = FakeTTS()
    master.media_dir = settings.media_dir

    async def go(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "tts_enabled": enabled, "tts_text_enabled": enabled}
        m = Message(campaign_id=cid, kind="narration", content=text, seq=await next_seq(s, cid))
        s.add(m)
        await s.commit()
        return m.id

    return run(settings, go)


def test_voicing_a_master_text_attaches_the_recording(game_client, admin_g, settings, llm):
    c, _, _ = party(game_client, admin_g)
    mid = narration(game_client, settings, c["id"])
    r = game_client.post(f"/api/campaigns/{c['id']}/messages/{mid}/voice", headers=admin_g)
    assert r.status_code == 202, r.text
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    data = rows(settings, Message, Message.id == mid)[0].data
    assert data["voices"] and data["voice_parts"] == len(data["voices"]) and data["voice"] == data["voices"][0]
    assert game_client.app.state.master.tts.texts  # синтез шёл по просьбе


def test_voicing_twice_does_not_synthesize_again(game_client, admin_g, settings, llm):
    c, _, _ = party(game_client, admin_g)
    mid = narration(game_client, settings, c["id"])
    url = f"/api/campaigns/{c['id']}/messages/{mid}/voice"
    assert game_client.post(url, headers=admin_g).status_code == 202
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    calls = len(game_client.app.state.master.tts.texts)
    assert game_client.post(url, headers=admin_g).status_code == 200
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert len(game_client.app.state.master.tts.texts) == calls


def test_voicing_is_refused_when_the_voice_is_switched_off(game_client, admin_g, settings, llm):
    c, _, _ = party(game_client, admin_g)
    mid = narration(game_client, settings, c["id"], enabled=False)
    r = game_client.post(f"/api/campaigns/{c['id']}/messages/{mid}/voice", headers=admin_g)
    assert r.status_code == 409
    assert not game_client.app.state.master.tts.texts


def test_only_master_texts_of_this_campaign_can_be_voiced(game_client, admin_g, settings, llm):
    c, _, _ = party(game_client, admin_g)
    narration(game_client, settings, c["id"])

    async def speech(s):
        m = Message(campaign_id=c["id"], kind="speech", content="Привет", seq=await next_seq(s, c["id"]))
        s.add(m)
        await s.commit()
        return m.id

    sid = run(settings, speech)
    assert game_client.post(f"/api/campaigns/{c['id']}/messages/{sid}/voice", headers=admin_g).status_code == 404
    assert game_client.post(f"/api/campaigns/{c['id']}/messages/nope/voice", headers=admin_g).status_code == 404
