import asyncio

from app.agents.master.prompting.slicers import bounded_evidence, slice_context
from app.core.universal.perception import established_evidence, evidence_parts
from app.db.models import Character, Message
from tests.test_universal_resolution import setup

PLACE = "Тракт за рощей: дорога расширяется, вдали придорожный постоялый двор."


def narration(i, extra=""):
    return f"Событие {i}. {extra}" + "Подробности случившегося, которые не нужны каждому ходу. " * 12


def parts(count=14):
    # newest first, as the database returns them
    return {"place": PLACE, "narrations": [narration(i) for i in reversed(range(count))]}


def test_budget_holds_and_the_newest_two_narrations_stay_whole():
    text = bounded_evidence(parts(), "осматриваюсь", 4000)
    assert len(text) <= 4000
    assert PLACE in text
    assert narration(13) in text and narration(12) in text
    assert narration(11) not in text


def test_older_narrations_stay_as_headlines_in_order_of_time():
    text = bounded_evidence(parts(), "осматриваюсь", 4000)
    assert "Событие 0." in text and "Событие 5." in text
    assert text.index("Событие 3.") < text.index("Событие 9.") < text.index("Событие 12.")


def test_an_old_narration_the_player_points_at_is_kept_whole():
    data = parts()
    data["narrations"][10] = narration(3, "Гонец отдал хозяйке запечатанное письмо с красной печатью. ")
    text = bounded_evidence(data, "Спрашиваю про запечатанное письмо", 4000)
    assert "красной печатью" in text


def test_a_headline_is_a_verbatim_start_of_the_narration_so_it_can_be_quoted():
    data = parts(5)
    data["narrations"][3] = "Старик кивнул гонцу. Потом ушёл в дом и долго не возвращался."
    text = bounded_evidence(data, "осматриваюсь", 4000)
    assert "Старик кивнул гонцу." in text
    assert "…" not in text


def test_everything_fits_when_the_game_is_young():
    data = {"place": PLACE, "narrations": ["Короткий рассказ."]}
    assert bounded_evidence(data, "иду", 4000) == PLACE + "\n" + "Короткий рассказ."


def test_slice_context_swaps_the_parts_for_the_bounded_text_and_drops_them():
    context = {"source": "осматриваюсь", "established_evidence": "FULL " * 5000, "evidence_parts": parts()}
    result = slice_context(context, "осматриваюсь")
    assert "evidence_parts" not in result
    assert len(result["established_evidence"]) <= 4000
    assert context["established_evidence"].startswith("FULL")  # the authoritative text stays whole


def test_without_parts_the_old_filter_still_applies():
    context = {"source": "стол", "established_evidence": "Про стол.\n\nПро кровать."}
    assert slice_context(context, "стол")["established_evidence"] == "Про стол."


def test_the_database_text_is_the_same_as_the_parts_joined(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as s:
                hero = await s.get(Character, "hero")
                for i in range(3):
                    s.add(
                        Message(
                            id=f"n{i}",
                            campaign_id="c",
                            seq=10 + i,
                            kind="narration",
                            content=f"Рассказ {i}",
                            data={"location_id": hero.location_id},
                        )
                    )
                await s.commit()
                place, narrations = (lambda p: (p["place"], p["narrations"]))(await evidence_parts(s, "c", "hero"))
                full = await established_evidence(s, "c", "hero")
            assert full == "\n".join([p for p in [place, *narrations] if p])
        finally:
            await engine.dispose()

    asyncio.run(run())
