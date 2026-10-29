# ruff: noqa: F811 — shared integration fixtures
"""A narrator may not repair scene errors by inventing player or NPC turns."""

from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401


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
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])  # the session greeting is done first
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
