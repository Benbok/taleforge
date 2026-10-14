# ruff: noqa: F811 — shared integration fixtures
"""A narrator may not repair scene errors by inventing player or NPC turns."""

from app.db.models import MasterTurn
from app.gateway.events import Stream
from tests.game import FIGHTER, ok, party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401


def test_failed_item_grant_cannot_be_narrated_as_inventory_success(game_client, admin_g, llm, settings):
    c, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {
            "tool_calls": [
                (
                    "give_item",
                    {
                        "character_id": hero["id"],
                        "item_template_id": "item.nonexistent_berry",
                        "qty": 9,
                        "reason": "остаток ягод",
                    },
                )
            ]
        },
        DONE,
        DONE,
        {"text": "Девять ягод благополучно оказались в рюкзаке. Корвин съел десятую и восстановил силы."},
    ]
    result = act(game_client, player, c["id"], "Кладу оставшиеся ягоды в рюкзак")
    assert "благополучно оказались" not in result["content"]
    assert "восстановил силы" not in result["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["item_fallback"] is True


def test_narrator_retries_invented_player_reply_before_streaming(
    game_client,
    admin_g,
    llm,
    settings,
    monkeypatch,  # noqa: F811
):
    c, (p1, p2), _ = party(game_client, admin_g, players=2)
    other = ok(
        game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER | {"name": "Emris"}, headers=p2), 201
    )
    ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{other['id']}/submit", headers=p2))
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    chunks = []
    original = Stream.push

    async def capture(self, chunk):
        chunks.append(chunk)
        await original(self, chunk)

    monkeypatch.setattr(Stream, "push", capture)
    invented = f"Пират обращается к [[{other['id']}|Emris]], та коротко отвечает: «Капитан пригласил».\n"
    llm.replies += [DONE, DONE, {"text": invented}, {"text": "Вопрос обращён к Emris. Она ещё не ответила."}]
    result = act(game_client, p1, c["id"], "А ты Эмрис, че тут делаешь — спрашиваю я")
    assert "Капитан пригласил" not in result["content"]
    assert "Капитан пригласил" not in "".join(chunks)
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["player_dialogue"] == [other["id"]]


def test_second_unknown_npc_is_blocked_even_without_numbered_name(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), _ = party(game_client, admin_g)
    llm.replies += [
        DONE,
        DONE,
        {"text": "[[npc_harbor_master|Капитан Элрик]] стоит рядом."},
        {"text": "[[npc_invented|Капитан Элрик]] отвечает на ваш вопрос."},
    ]
    result = act(game_client, p1, c["id"], "Что за тени?")
    assert "Капитан Элрик" not in result["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["blocked_refs"] == ["npc_invented"]


def test_retry_cannot_keep_unknown_npc_by_removing_markup(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), _ = party(game_client, admin_g)
    llm.replies += [
        DONE,
        DONE,
        {"text": "[[npc_elric|Captain Elric]] answers your question."},
        {"text": "Captain Elric answers your question."},
    ]
    result = act(game_client, p1, c["id"], "Что за тени?")
    assert "Captain Elric" not in result["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["blocked_names"] == ["Captain Elric"]


def test_submitted_player_dialogue_is_allowed(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "задаёт вопрос"})]},
        DONE,
        {"text": f"[[{hero['id']}|Бран]] спрашивает: «Что за тени?»"},
    ]
    result = act(game_client, p1, c["id"], "Что за тени? — спрашиваю я")
    assert "Что за тени?" in result["content"]
    (turn,) = rows(settings, MasterTurn)
    assert not turn.trace["audit"].get("player_dialogue")


def test_repeated_unknown_npc_does_not_undo_successful_transition(
    game_client,
    admin_g,
    llm,
    settings,
    monkeypatch,  # noqa: F811
):
    from app.db.models import Scene
    from tests.test_adventure import publish_sample

    module_id = publish_sample(settings)
    c, (p1,), hero = party(game_client, admin_g, module_id=module_id, module_hook="board")
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, None)

    async def skip_intro(*_args):
        return None

    monkeypatch.setattr(master, "introduce", skip_intro)
    (before,) = rows(settings, Scene, Scene.campaign_id == c["id"])
    llm.replies += [
        {"tool_calls": [("enter_room", {"room": "2", "character_ids": [hero["id"]]})]},
        DONE,
        {"text": "[[npc_ghost|Ghost]] stands here."},
        {"text": "[[npc_unknown|Ghost]] stands here."},
    ]
    result = act(game_client, p1, c["id"], "Осматриваю вход и жду решения мастера.")
    (after,) = rows(settings, Scene, Scene.campaign_id == c["id"])
    assert before.location_id != after.location_id
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["transition_outcome"] == "success"
    assert "Ghost" not in result["content"]
    assert "прежнем месте" not in result["content"]


def test_repeated_invented_player_reply_is_blocked(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    invented = f"«Я согласен», — отвечает [[{hero['id']}|Бран]]."
    llm.replies += [DONE, DONE, {"text": invented}, {"text": invented}]
    result = act(game_client, p1, c["id"], "Смотрю на воду")
    assert "Я согласен" not in result["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["blocked_player_dialogue"] == [hero["id"]]


def test_npc_and_ai_dialogue_do_not_belong_to_human_player():
    from app.agents.master.continuity import invented_player_dialogue

    players = {"ch_player": "Бран"}
    participants = {**players, "en_npc": "Капитан Элрик", "ch_ai": "Гимли"}
    assert (
        invented_player_dialogue("Бран слушает. Капитан Элрик говорит: «Добро пожаловать».", players, participants, "")
        == []
    )
    assert invented_player_dialogue("Гимли отвечает: «Иду с вами».", players, participants, "") == []
    assert (
        invented_player_dialogue(
            "Капитан Элрик обращается к [[ch_player|Бран]] и говорит: «Привет».", players, participants, ""
        )
        == []
    )


def test_dash_player_reply_is_checked():
    from app.agents.master.continuity import invented_player_dialogue

    assert invented_player_dialogue(
        "Бран отвечает:\n— Я пришёл за наградой.", {"ch_player": "Бран"}, {"ch_player": "Бран"}, ""
    ) == ["ch_player"]


def test_speech_attribution_starts_after_previous_quote():
    from app.agents.master.continuity import invented_player_dialogue

    assert (
        invented_player_dialogue(
            "Бран спрашивает: «Who are you?» Капитан Элрик отвечает: «I am the captain.»",
            {"ch_player": "Бран"},
            {"ch_player": "Бран", "en_npc": "Капитан Элрик"},
            "(ch_player): Who are you?",
        )
        == []
    )


def test_speech_attribution_starts_after_semicolon():
    from app.agents.master.continuity import invented_player_dialogue

    assert invented_player_dialogue(
        "Капитан Элрик pauses; Бран отвечает: «I came for the reward.»",
        {"ch_player": "Бран"},
        {"ch_player": "Бран", "en_npc": "Капитан Элрик"},
        "",
    ) == ["ch_player"]


def test_multiline_submitted_dialogue_is_allowed_for_its_author_only():
    from app.agents.master.continuity import invented_player_dialogue

    players = {"ch_player": "Бран", "ch_other": "Emris"}
    news = (
        "- [action] Бран (ch_player): I look at the captain.\n"
        "«I came for a reward.»\n- [action] Emris (ch_other): I wait."
    )
    assert invented_player_dialogue("Бран говорит: «I came for a reward.»", players, players, news) == []
    assert invented_player_dialogue("Emris говорит: «I came for a reward.»", players, players, news) == ["ch_other"]


def test_voice_line_drops_json_commands(game_client, admin_g, llm):  # noqa: F811
    from app.core.campaigns import master_seat
    from app.db.models import AgentConfig, Campaign
    from app.tools.runtime import open_context

    c, _, _ = party(game_client, admin_g)
    llm.replies += [{"voice_line": True, "text": 'Доки затихли.\n[{"call":"spawn_entity","args":{}}]'}]
    master = game_client.app.state.master

    async def voice():
        async with master.maker() as s:
            campaign = await s.get(Campaign, c["id"])
            seat = master_seat(campaign)
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, campaign, master.dice_factory(), turn_id=None, seat_id=seat.id)
            return await master._voice_line([], cfg, campaign, seat.id, None, "Мастер", ctx, [])

    assert game_client.portal.call(voice) == "Доки затихли."
