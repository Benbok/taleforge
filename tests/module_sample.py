"""Сдача переводчика по «Неспокойным мертвецам» в сокращённом виде: два места, своё существо и предмет."""

import copy


def plot_part() -> dict:
    return {
        "title": "Неспокойные мертвецы",
        "tagline": "Мертвецы выбираются из семейного склепа.",
        "tags": ["нежить", "культ"],
        "public_intro": "Скелеты повылезали из старого склепа Давоса, за их упокоение обещают 50 зм.",
        "conflict": "Культ Дургона снимает печать с костей дьявола.",
        "stakes": "Дургон вернётся, и тьма охватит землю.",
        "antagonists": [
            {
                "id": "cult",
                "name": "Культ Дургона",
                "template_id": "creature.cult_fanatic",
                "goal": "Воскресить Дургона",
                "methods": "Нечестивый череп Давоса, ритуал в храме",
                "weakness": "Без черепа печать не снять",
                "secret": "Убежище под городом",
                "threat": ["Нежить встаёт в склепе", "Культ входит в храм", "Печать снята"],
            }
        ],
        "locations": [
            {
                "id": "crypt",
                "name": "Склеп Давоса",
                "template_id": "location.davos_crypt",
                "role": "Начало",
                "mood": "Пыль и тьма",
                "secret": "Череп Давоса украден",
            },
            {
                "id": "temple",
                "name": "Храм Давоса",
                "template_id": "location.davos_temple",
                "role": "Финал",
                "mood": "Свет и гарь",
                "secret": "Под храмом кости Дургона",
            },
        ],
        "npcs": [
            {
                "id": "noble",
                "name": "Аристократ",
                "template_id": "creature.noble",
                "role": "Наниматель",
                "want": "Упокоить предков",
                "fear": "Позор семьи",
                "secret": "Нет",
                "attitude": "Вежлив",
                "look": "Бархат и перстни",
            }
        ],
        "acts": [
            {
                "id": "act_crypt",
                "title": "Склеп",
                "goal": "Упокоить мертвецов",
                "exit": "Найдена записка культа",
                "milestone_level": 2,
                "nodes": [{"id": "n_bones", "title": "Скелеты", "summary": "Кости встают", "location_id": "crypt"}],
            },
            {
                "id": "act_temple",
                "title": "Храм",
                "goal": "Сорвать ритуал",
                "exit": "Культ разбит",
                "milestone_level": 3,
                "nodes": [{"id": "n_ritual", "title": "Ритуал", "summary": "Культ у печати", "location_id": "temple"}],
            },
        ],
        "reveals": [
            {
                "id": "skull",
                "truth": "Череп Давоса у культа",
                "node_id": "n_ritual",
                "clues": [{"at": "crypt", "text": "Пустой гроб без черепа"}],
            }
        ],
        "endings": ["Печать цела", "Дургон вернулся"],
    }


def sample() -> dict:
    return copy.deepcopy(
        {
            "title": "Неспокойные мертвецы",
            "slug": "unquiet-dead",
            "summary": "Мертвецы выбираются из склепа, а во тьме рыщут чьи-то тени.",
            "levels": {"start": 1, "end": 3},
            "party_size": 4,
            "credits": "Арден",
            "hooks": [
                {"id": "noble", "title": "Просьба аристократа", "text": "Записка от аристократа, 50 зм."},
                {"id": "board", "title": "Объявление", "text": "Объявление на доске, 50 зм."},
            ],
            "locations": [
                {
                    "id": "location.davos_crypt",
                    "name": "Семейный склеп Давоса",
                    "description": "Пыльный склеп под мавзолеем.",
                    "features": ["Потолки 10 фт.", "В склепе темно."],
                    "rooms": [
                        {
                            "id": "r1",
                            "number": "1",
                            "name": "Зал Мёртвых",
                            "description": "Таблички и гробы.",
                            "checks": [{"skill": "perception", "dc": 16, "text": "Замечает скелетов в комнате 2"}],
                            "exits": ["r2"],
                        },
                        {
                            "id": "r2",
                            "number": "2",
                            "name": "Восточная крипта",
                            "description": "Два гроба, два скелета.",
                            "encounters": [{"creature_ref": "creature.skeleton", "count": 2}],
                            "treasure": [{"text": "2к12 см у каждого скелета"}],
                            "exits": ["r1"],
                        },
                    ],
                },
                {
                    "id": "location.davos_temple",
                    "name": "Храм Давоса",
                    "description": "Храм над костями Дургона.",
                    "rooms": [
                        {
                            "id": "r1",
                            "number": "1",
                            "name": "Вход",
                            "description": "Статуи у дверей.",
                            "encounters": [{"creature_ref": "creature.temple_statue", "count": 2}],
                            "treasure": [{"item_ref": "item.davos_skull", "text": "Череп Давоса на алтаре"}],
                        }
                    ],
                },
            ],
            "creatures": [
                {
                    "id": "creature.temple_statue",
                    "name": "Статуя храма",
                    "base_ref": "creature.animated_armor",
                    "description": "Каменный страж.",
                    "changes": {"hp": {"average": 30, "dice": "5d8+8"}, "ac": 17},
                    "book_note": "В книге статуя бьёт дважды, здесь — как оживлённые доспехи.",
                }
            ],
            "items": [
                {
                    "id": "item.davos_skull",
                    "name": "Череп Давоса",
                    "category": "quest",
                    "description": "Череп жреца, полный нечестивой силы.",
                }
            ],
            "plot": plot_part(),
            "epilogue": "Аристократ платит 50 зм, церковь благодарит.",
            "notes": ["Аристократу дано имя не из книги."],
        }
    )
