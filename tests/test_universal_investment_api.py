import asyncio

from app.db.models import Campaign, Message


class Slot:
    """Stands in for the turn's open answer; the test client runs on another loop than the turn would."""

    def __init__(self):
        self.answer = None

    def done(self):
        return self.answer is not None

    def set_result(self, value):
        self.answer = value


def offer(client, cid, mid="m", seat_of="player", status="offered"):
    async def seed():
        async with client.app.state.sessionmaker() as s:
            campaign = await s.get(Campaign, cid)
            seat = next(row for row in campaign.seats if row.role == seat_of)
            campaign.last_seq += 1
            s.add(
                Message(
                    id="invest_" + mid,
                    campaign_id=cid,
                    seq=campaign.last_seq,
                    kind="investment",
                    content="Вложить усилие?",
                    data=dict(mid=mid, seat_id=seat.id, status=status),
                )
            )
            await s.commit()

    asyncio.run(seed())
    slot = Slot()
    client.app.state.master.investments[(cid, mid)] = slot
    return slot


def setup_campaign(client, root, monkeypatch):
    from tests.test_api import make_campaign

    monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
    return make_campaign(client, root, owner_plays=True)["id"]


def test_controlling_seat_answers_once(client, root, monkeypatch):
    cid = setup_campaign(client, root, monkeypatch)
    slot = offer(client, cid)
    url = f"/api/campaigns/{cid}/investments/m"
    first = client.post(url, headers=root, json={"accept": True})
    assert first.status_code == 200 and first.json() == {"status": "accepted"}
    assert slot.answer is True
    assert client.post(url, headers=root, json={"accept": False}).json() == {"status": "closed"}
    assert slot.answer is True  # the first answer stands


def test_declining_is_reported(client, root, monkeypatch):
    cid = setup_campaign(client, root, monkeypatch)
    slot = offer(client, cid)
    response = client.post(f"/api/campaigns/{cid}/investments/m", headers=root, json={"accept": False})
    assert response.json() == {"status": "declined"} and slot.answer is False


def test_another_seat_cannot_answer_and_the_offer_stays_open(client, root, monkeypatch):
    cid = setup_campaign(client, root, monkeypatch)
    slot = offer(client, cid, seat_of="master")
    response = client.post(f"/api/campaigns/{cid}/investments/m", headers=root, json={"accept": True})
    assert response.status_code == 403
    assert slot.answer is None


def test_unknown_or_settled_offer_is_closed(client, root, monkeypatch):
    cid = setup_campaign(client, root, monkeypatch)
    assert client.post(f"/api/campaigns/{cid}/investments/nope", headers=root, json={"accept": True}).json() == {
        "status": "closed"
    }
    slot = offer(client, cid, mid="old", status="declined")
    assert client.post(f"/api/campaigns/{cid}/investments/old", headers=root, json={"accept": True}).json() == {
        "status": "closed"
    }
    assert slot.answer is None
