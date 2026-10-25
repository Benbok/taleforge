import asyncio

from app.agents.master.service import MasterService
from app.agents.master.universal_mood import mood_update
from app.core.campaigns import agent_for_master
from app.db.models import MasterTurn, Scene, Seat
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def applied(**extra):
    return {"m1": {"status": "applied", "critical": False, "critical_failure": False, **extra}}


def test_cabinet_temper_sets_the_tone_even_without_critical_rolls():
    note, state = mood_update("sadist", {}, applied())
    assert "Садист" in note and "Обожает страдания" in note
    assert "не меняй" in note  # the tone never rewrites saved facts
    assert state == {"anger": 0.0, "joy": 0.0, "suspicion": 0.0, "boredom": 0.0}


def test_critical_failures_raise_the_masters_mood_and_changes_the_note():
    calm, _ = mood_update("sadist", {}, applied())
    mood, state = mood_update("sadist", {}, {"m1": {"status": "applied", "critical": False, "critical_failure": True}})
    assert state["joy"] == 3.0 and mood != calm
    assert mood.startswith(calm.split("\n")[0])  # the cabinet temper stays the first line


def test_denied_actions_and_unknown_temper_are_harmless():
    note, state = mood_update("no-such-temper", {"joy": 2.0}, {"m1": {"status": "denied", "critical_failure": True}})
    assert note and state["joy"] <= 2.0  # nothing rolled; the default temper and a decaying mood remain


def test_narration_prompt_carries_the_temper_and_the_turn_is_stepped_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            config = await agent_for_master(s, {"type": "agent"})
            config.settings = {**(config.settings or {}), "emotion_persona": "sadist"}
            s.add(config)
            await s.flush()
            (await s.get(Seat, "master")).agent_config_id = config.id
            await s.commit()
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="check",
                    attribute="wis",
                    effects=[dict(kind="observe")],
                    check_outcomes=dict(
                        success="Видно.", failure="Темно.", critical_success="Ясно.", critical_failure="Слепота."
                    ),
                ),
                "Вы едва различаете шаги.",
                dict(verdict="pass"),
            ]
        )
        from app.rules.dice import FixedDice

        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([1])).run_turn("c")
        narrate = next(p for p in provider.prompts if "Расскажи продолжение сцены" in p[0]["content"])
        assert "Садист" in narrate[0]["content"]
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            assert "Садист" in turn.trace["mood_note"]
            scene = await s.get(Scene, "c")
            if scene is not None:
                assert scene.state["gm_mood"]["joy"] == 3.0  # one natural 1 stepped the mood exactly once
        await engine.dispose()

    asyncio.run(run())
