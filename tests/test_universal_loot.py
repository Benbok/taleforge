from collections import Counter
from types import SimpleNamespace

import pytest

from app.core.universal.loot import LootSlot, loot_profile, loot_slots
from app.rules.universal.items import ItemProfile


def campaign(difficulty="normal", enabled=True):
    return SimpleNamespace(id="c", difficulty=difficulty, settings={"loot_enabled": enabled})


def test_slots_are_deterministic_and_bounded():
    c = campaign()
    for i in range(200):
        slots = loot_slots(c, str(i))
        assert slots == loot_slots(c, str(i))
        assert len(slots) <= 2
        assert [s.ref for s in slots] == ["loot_1", "loot_2"][: len(slots)]
        assert all(s.kind in {"consumable", "weapon", "armor"} for s in slots)


def test_the_table_is_followed():
    for difficulty, shares in [("easy", [0.2, 0.5, 0.3]), ("normal", [0.3, 0.6, 0.1]), ("hard", [0.6, 0.4, 0])]:
        counts = Counter(len(loot_slots(campaign(difficulty), str(i))) for i in range(2000))
        for n, share in enumerate(shares):
            assert abs(counts[n] / 2000 - share) < 0.08
    for i in range(200):
        assert loot_slots(campaign("deadly"), str(i)) == []
        assert loot_slots(campaign(enabled=False), str(i)) == []


@pytest.mark.parametrize("kind", ["weapon", "armor", "consumable"])
def test_profile_numbers_come_from_the_server(kind):
    profile = loot_profile(LootSlot("loot_1", kind), "Находка", "Описание")
    assert ItemProfile.model_validate(profile.model_dump()) == profile
    assert profile.status == "common"
    assert profile.attack_bonus == profile.damage_bonus == 0
    if kind == "weapon":
        assert profile.base_dice == "1d6"
        assert loot_profile(LootSlot("loot_1", kind), "Нож", "", "dex").base_dice == "1d4"
        with pytest.raises(ValueError):
            loot_profile(LootSlot("loot_1", kind), "Нож", "", "wis")
    elif kind == "armor":
        assert profile.defense_bonus == 1
    else:
        assert profile.restore_pool == "hp" and profile.restore_amount == 6
