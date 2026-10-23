import json

from app.agents.llm import ScriptedLLM

SCORES = dict(str="8", dex="12", con="14", int="13", wis="15", cha="10")
DESCRIPTION = dict(
    name="Ива",
    identity="Маг растений и путешественница",
    appearance="",
    personality="Сдержанная",
    capabilities="Знает растения, управляет лозами",
)
PROPOSAL = dict(
    abilities=SCORES,
    explanations={
        "str": "Физически слаба",
        "dex": "Координация в походах",
        "con": "Привычна к трудностям",
        "int": "Знает растения",
        "wis": "Управляет магией растений",
        "cha": "Сдержанна в общении",
    },
)


def ready_reply(**changes):
    result = dict(description=DESCRIPTION, question=None, proposal=PROPOSAL)
    result.update(changes)
    return {"text": json.dumps(result, ensure_ascii=False)}


def set_replies(client, replies):
    client.app.state.hero_llm = ScriptedLLM(replies)


def create_hero(client, headers):
    set_replies(client, [ready_reply()])
    draft = client.post("/api/hero-creation/dialogues", headers=headers, json={"description": DESCRIPTION}).json()
    confirmed = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=headers,
        json={"expected_revision": draft["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["hero_id"]
