"""Атлас мира «Эха Левиафанов»: архитектор кампании видит ключевых лиц и места мира и выбирает шаблон сюжета мира.

Записи атласа пока в статусе proposal, поэтому их видит только тестовая кампания."""

from app.agents import architect
from app.content.catalog import campaign_catalog
from app.db.models import Campaign
from tests.game import run
from tests.test_api import make_campaign
from tests.test_worlds import worlds  # noqa: F401 — фикстура


def test_architect_sees_world_figures_and_places(client, admin, settings, worlds):  # noqa: F811
    brief = {"length": "short", "pillars": {"combat": "high"}, "emotions": ["heroism"], "wishes": "война на черте"}
    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans", brief=brief, test_mode=True)

    async def go(s):
        camp = await s.get(Campaign, c["id"])
        catalog = await campaign_catalog(s, camp)
        return await architect.build_input(s, camp), catalog.by_kind("plot_structure")

    (text, structure_id), structures = run(settings, go)
    # атлас пока в статусе proposal: его видит тестовая кампания рядом с шаблонами SRD;
    # пожелание «война на черте» перевешивает равный счёт по акцентам («Охота на выводок», «Охота на чудовище»)
    assert {"plot.el_hold_the_line", "plot.siege"} <= {e.id for e in structures}
    assert structure_id == "plot.el_hold_the_line"
    assert "Ключевые места мира:" in text and "location.city_oplot (Оплот)" in text
    assert "creature.npc_erofey_gar (Ерофей Гарь)" in text and "хочет: Удержать черту" in text
    assert "тайна: У Кордона топлива на один сезон" in text
    # ключевые лица не дублируются в списке шаблонов, а люди мира в него попадают
    templates = text.split("Шаблоны существ для NPC:")[1]
    assert "creature.npc_erofey_gar" not in templates and "creature.cordon_burner" in templates
