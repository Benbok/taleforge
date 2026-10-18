"""Полный генератор экспериментальной коллекции из 12 шаблонов локаций для TaleForge.

Строит Blueprint через DeterministicLayoutProvider, проверяет через validation
и geometry.build_area, тестирует seeds [1, 7, 42, 99, 123] и экспортирует JSON-файлы
в experiments/location-layout-templates/templates/<id>/.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.layout.contracts import Blueprint
from app.core.layout.geometry import build_area
from app.core.layout.intent import ApproachIntent, BandIntent, DetailIntent, LayoutIntent, PartIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.validation import validate

ROOT = Path(__file__).resolve().parents[3]
EXP_DIR = ROOT / "experiments" / "location-layout-templates"
TEMPLATES_DIR = EXP_DIR / "templates"
TEST_SEEDS = [1, 7, 42, 99, 123]
SELECTED_SEED = 7

# ==============================================================================
# 1. ТАВЕРНА
# ==============================================================================

def make_tavern_roadside() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "tavern_roadside",
        "version": "1.1.0",
        "archetype": "tavern",
        "variant": "A",
        "variant_name": "Небольшая придорожная",
        "purpose": "Придорожный привал для отдыха, сбора слухов и ночлега путевых отрядов",
        "visual_concept": "Уютная деревянно-каменная таверна у тракта с теплым очагом в торце, Г-образной барной стойкой с табуретами, двумя отдельными обеденными столами со скамьями, кухней и спальным отсеком.",
        "environment": "indoor",
        "materials": ["wood", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Разговоры с трактирщиком через стойку, приватные беседы за обособленными столами, застольные споры у очага.",
            "exploration": "Осмотр кухонной кладовой и припасов, проверка кованых сундуков в жилой комнате (содержимое и наличие добычи определяются правилами приключения/мастером).",
            "combat": "Твёрдые столы и стойка служат физическими препятствиями перемещению (solid=True согласно геометрии); очаг выступает источником света (kind='light'); сквозные проходы между входом с юга, кухней на западе и спальнями на востоке полностью свободны для манёвра."
        },
        "allowable_adaptations": [
            "Добавление подвала/ледника под кухней",
            "Замена мебели на казарменную или лазаретную",
            "Добавление чердака или второго входа с заднего двора"
        ],
        "discovered_constraints": [
            "Двери между комнатами ограничены шириной 1 клетка.",
            "Детали вдоль стены с дверью смещаются алгоритмом _place_details, если попадают в створ проёма."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="common_room",
        parts=[
            PartIntent(
                part_ref="common_room",
                role="tavern_hall",
                name="Общий зал таверны",
                public_name="Общий зал",
                description="Просторный деревянный зал с массивными дубовыми балками, тёплым очагом в торце и удобными столами.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=8,
                level=0,
                material="wood",
                details=[
                    DetailIntent(detail_ref="hearth", name="Большой очаг", kind="light", solid=True, cells=[[3, 0, 4, 0]]),
                    DetailIntent(detail_ref="bar_counter", name="Барная стойка", kind="furniture", solid=True, cells=[[1, 1, 1, 2], [2, 2, 2, 2]]),
                    DetailIntent(detail_ref="bar_stools", name="Табуреты у стойки", kind="furniture", cells=[[2, 3, 2, 3]]),
                    DetailIntent(detail_ref="table_north", name="Северный обеденный стол", kind="furniture", solid=True, cells=[[5, 2, 6, 2]]),
                    DetailIntent(detail_ref="benches_north", name="Скамьи северного стола", kind="furniture", cells=[[5, 1, 6, 1], [5, 3, 6, 3]]),
                    DetailIntent(detail_ref="table_south", name="Южный обеденный стол", kind="furniture", solid=True, cells=[[5, 6, 6, 6]]),
                    DetailIntent(detail_ref="benches_south", name="Скамья южного стола", kind="furniture", cells=[[5, 5, 6, 5]]),
                    DetailIntent(detail_ref="ale_casks", name="Бочки с элем", kind="object", cells=[[1, 6, 1, 7]]),
                ],
            ),
            PartIntent(
                part_ref="kitchen_pantry",
                role="kitchen",
                name="Кухня и кладовая",
                public_name="Кухня",
                description="Жаркое каменное помещение с печью, разделочным столом и полками с припасами.",
                environment="indoor",
                shape="rect",
                cols=5,
                rows=6,
                level=0,
                material="stone",
                connects_to="common_room",
                side="w",
                passage_kind="door",
                passage_name="Дверь на кухню",
                details=[
                    DetailIntent(detail_ref="stove", name="Кухонная печь", kind="light", solid=True, cells=[[0, 2, 0, 3]]),
                    DetailIntent(detail_ref="pantry_shelves", name="Стеллажи с припасами", kind="furniture", cells=[[1, 0, 3, 0]]),
                    DetailIntent(detail_ref="prep_table", name="Разделочный стол", kind="furniture", cells=[[2, 3, 2, 4]]),
                ],
            ),
            PartIntent(
                part_ref="guest_rooms",
                role="quarters",
                name="Комнаты постояльцев",
                public_name="Комнаты отдыха",
                description="Тихий жилой отсек со спальными местами для уставших путников.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="common_room",
                side="e",
                passage_kind="door",
                passage_name="Дверь в коридор покоев",
                details=[
                    DetailIntent(detail_ref="bunks_north", name="Спальные лежанки", kind="furniture", cells=[[1, 1, 2, 1]]),
                    DetailIntent(detail_ref="bunks_south", name="Дополнительные лежанки", kind="furniture", cells=[[1, 4, 2, 4]]),
                    DetailIntent(detail_ref="traveler_chests", name="Кованые сундуки", kind="object", cells=[[4, 2, 4, 3]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="common_room", side="s", kind="door", public_name="Вход с тракта", width=1),
        ],
    )
    return meta, intent


def make_tavern_urban_cellar() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "tavern_urban_cellar",
        "version": "1.0.0",
        "archetype": "tavern",
        "variant": "B",
        "variant_name": "Городская с погребом",
        "purpose": "Шумная городская таверна с залом переговоров, винным погребом и тайником контрабандистов",
        "visual_concept": "Двухуровневое каменное заведение: оживлённый зал первого этажа, приватный гильдейский кабинет и глубокий сводчатый погреб со скрытой нишей.",
        "environment": "indoor",
        "materials": ["stone", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Шумная толпа в общем зале, конфиденциальные сделки за запертой дверью кабинета, конспиративные встречи в винном подвале.",
            "exploration": "Поиск потайного механизма за винными стеллажами, инспекция замков на гильдейском сейфе, учет контрабандных партий.",
            "combat": "Лестничный колодец как точка обороны, узкое пространство между бочками в подвале, темнота погреба."
        },
        "allowable_adaptations": [
            "Превращение погреба в подземный ход в городскую канализацию",
            "Использование кабинета как штаба городской стражи или ростовщика",
            "Замена тайника на камеру для должников"
        ],
        "discovered_constraints": [
            "Связь между разными уровнями поддерживается строго через лестницу (stairs) или люк (hatch).",
            "Тайный проход помечается secret=True, скрывая помещение от публичной связности."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="taproom",
        parts=[
            PartIntent(
                part_ref="taproom",
                role="tavern_hall",
                name="Городской питейный зал",
                public_name="Питейный зал",
                description="Высокий каменный зал с дубовыми круглыми столами, витражными окнами на улицу и массивной стойкой.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(detail_ref="long_bar", name="Массивная барная стойка", kind="furniture", solid=True, cells=[[2, 2, 2, 5]]),
                    DetailIntent(detail_ref="round_tables", name="Круглые столы горожан", kind="furniture", cells=[[5, 2, 7, 3]]),
                    DetailIntent(detail_ref="iron_stove", name="Чугунная печь", kind="light", solid=True, cells=[[8, 1, 8, 1]]),
                    DetailIntent(detail_ref="ale_casks", name="Ряд пивных бочек", kind="object", cells=[[1, 2, 1, 5]]),
                ],
            ),
            PartIntent(
                part_ref="private_parlor",
                role="parlor",
                name="Приватный кабинет",
                public_name="Отдельный кабинет",
                description="Кабинет с обитыми кожей креслами, тяжёлыми портьерами и шкафом для документов.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="taproom",
                side="e",
                passage_kind="door",
                passage_name="Дверь с замком",
                passage_state="locked",
                details=[
                    DetailIntent(detail_ref="leather_chairs", name="Кожаные кресла и круглый столик", kind="furniture", cells=[[2, 2, 3, 3]]),
                    DetailIntent(detail_ref="bookcase", name="Шкаф с бухгалтерскими книгами", kind="object", cells=[[1, 0, 4, 0]]),
                    DetailIntent(detail_ref="wall_sconce", name="Бронзовый настенный светильник", kind="light", cells=[[5, 2, 5, 2]]),
                ],
            ),
            PartIntent(
                part_ref="cold_cellar",
                role="cellar",
                name="Холодный винный погреб",
                public_name="Винный погреб",
                description="Сырой каменный подвал с ровными рядами дубовых винных бочек и стеллажами для бутылей.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=8,
                level=-1,
                material="stone",
                connects_to="taproom",
                passage_kind="stairs",
                passage_name="Каменная лестница в подвал",
                details=[
                    DetailIntent(detail_ref="wine_tuns", name="Большие дубовые чаны", kind="object", solid=True, cells=[[1, 1, 1, 3]]),
                    DetailIntent(detail_ref="bottle_racks", name="Стеллажи с винами", kind="furniture", cells=[[3, 1, 6, 1]]),
                    DetailIntent(detail_ref="ice_pit", name="Ледник для скоропортящихся продуктов", kind="cover", cells=[[5, 5, 6, 6]]),
                    DetailIntent(detail_ref="cellar_lantern", name="Подвесной масляный фонарь", kind="light", cells=[[3, 4, 3, 4]]),
                ],
            ),
            PartIntent(
                part_ref="secret_vault",
                role="vault",
                name="Потайное хранилище гильдии",
                public_name="Потайная каморка",
                description="Узкая ниша за фальшивой стеной, где спрятаны запрещённые товары и гильдейская казна.",
                environment="indoor",
                shape="rect",
                cols=4,
                rows=4,
                level=-1,
                material="stone",
                connects_to="cold_cellar",
                side="w",
                passage_kind="door",
                passage_name="Откидная панель стеллажа",
                passage_state="closed",
                secret=True,
                details=[
                    DetailIntent(detail_ref="iron_strongbox", name="Кованый сундук гильдии", kind="object", solid=True, cells=[[1, 1, 2, 1]]),
                    DetailIntent(detail_ref="smuggled_crates", name="Ящики с контрабандой", kind="object", cells=[[1, 2, 2, 2]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="taproom", side="w", kind="door", public_name="Вход с городской площади", width=1),
        ],
    )
    return meta, intent


# ==============================================================================
# 2. ХРАМ
# ==============================================================================

def make_temple_compact_shrine() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "temple_compact_shrine",
        "version": "1.0.0",
        "archetype": "temple",
        "variant": "A",
        "variant_name": "Компактное святилище",
        "purpose": "Действующее городское или монастырское святилище для молитв, благословений и обрядов",
        "visual_concept": "Строгое симметричное каменное святилище: входной притвор с чашей омовения, неф с рядами колонн и священным алтарем, ризница священника.",
        "environment": "indoor",
        "materials": ["stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Беседа со жрецом, получение благословения, исповедь кающихся, поиск священных свитков.",
            "exploration": "Изучение символики алтаря, проверка ритуальных реликвий в сундуках ризницы, чтение священных текстов.",
            "combat": "Несущие каменные колонны как полное укрытие, алтарное возвышение для преимущества высоты, узкие проходы между нефом и притвором."
        },
        "allowable_adaptations": [
            "Осквернение алтаря темными культами",
            "Добавление крипты под алтарем",
            "Превращение ризницы в келью затворника"
        ],
        "discovered_constraints": [
            "Колонны оформляются как solid=True детали, создавая непроходимые препятствия на карте.",
            "Проход между притвором и святилищем выполнен широкой аркой (passage_kind=arch)."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="narthex",
        parts=[
            PartIntent(
                part_ref="narthex",
                role="vestibule",
                name="Храмовый притвор",
                public_name="Притвор",
                description="Прохладный притвор со сводчатым потолком, каменными скамьями и чашей для омовения.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=5,
                level=0,
                material="stone",
                details=[
                    DetailIntent(detail_ref="holy_water_font", name="Чаша со святой водой", kind="object", solid=True, cells=[[3, 2, 4, 2]]),
                    DetailIntent(detail_ref="prayer_benches", name="Скамьи для молящихся", kind="furniture", cells=[[1, 1, 1, 3], [6, 1, 6, 3]]),
                    DetailIntent(detail_ref="candle_stand", name="Подсвечник с лампадами", kind="light", cells=[[3, 0, 4, 0]]),
                ],
            ),
            PartIntent(
                part_ref="sanctuary",
                role="sanctuary",
                name="Главное святилище",
                public_name="Святилище",
                description="Величественный неф с двумя рядами мраморных колонн, резным алтарём и золотым храмовым символом.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=12,
                level=0,
                material="stone",
                connects_to="narthex",
                side="n",
                passage_kind="arch",
                passage_name="Входная храмовая арка",
                details=[
                    DetailIntent(detail_ref="grand_altar", name="Мраморный алтарь", kind="furniture", solid=True, cells=[[4, 1, 5, 2]]),
                    DetailIntent(detail_ref="columns_west", name="Западный ряд колонн", kind="cover", solid=True, cells=[[2, 4, 2, 4], [2, 8, 2, 8]]),
                    DetailIntent(detail_ref="columns_east", name="Восточный ряд колонн", kind="cover", solid=True, cells=[[7, 4, 7, 4], [7, 8, 7, 8]]),
                    DetailIntent(detail_ref="incense_braziers", name="Курильницы с благовониями", kind="light", cells=[[3, 1, 3, 1], [6, 1, 6, 1]]),
                    DetailIntent(detail_ref="lectern", name="Пюпитр священнослужителя", kind="furniture", cells=[[4, 4, 5, 4]]),
                ],
            ),
            PartIntent(
                part_ref="sacristy",
                role="sacristy",
                name="Ризница священников",
                public_name="Ризница",
                description="Боковое помещение для хранения священных реликвий, облачений и церковных хроник.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="sanctuary",
                side="e",
                passage_kind="door",
                passage_name="Дверь в ризницу",
                details=[
                    DetailIntent(detail_ref="relic_chest", name="Сундук с реликвиями", kind="object", solid=True, cells=[[4, 1, 4, 2]]),
                    DetailIntent(detail_ref="vestment_press", name="Шкаф с ритуальными облачениями", kind="furniture", cells=[[1, 0, 3, 0]]),
                    DetailIntent(detail_ref="study_desk", name="Стол летописца", kind="furniture", cells=[[2, 4, 3, 4]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="narthex", side="s", kind="door", public_name="Парадные врата храма", width=1),
        ],
    )
    return meta, intent


def make_temple_ruined_courtyard() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "temple_ruined_courtyard",
        "version": "1.0.0",
        "archetype": "temple",
        "variant": "B",
        "variant_name": "Разрушенный храм с двором",
        "purpose": "Заброшенный полуразрушенный культовый комплекс с внешним двором, осквернённым нефом и древней криптой",
        "visual_concept": "Открытый внешний двор с порослью сорняков и рухнувшими статуями ведёт в частично уцелевший неф с расколотым алтарём, откуда лестница спускается в тёмную крипту.",
        "environment": "mixed",
        "materials": ["grass", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Переговоры с отрядом мародёров или встреча с духом древнего хранителя в подземном склепе.",
            "exploration": "Поиск уцелевших святынь среди обломков двора, спуск в запечатанную крипту, расшифровка надписей на саркофагах.",
            "combat": "Стычка во дворе с использованием обломков стен и валунов как укрытий, тесный бой в крипте против нежити."
        },
        "allowable_adaptations": [
            "Заселение двора лагерем наёмников или культистов",
            "Затопление крипты грунтовыми водами",
            "Размещение ловушек на ступенях в подземелье"
        ],
        "discovered_constraints": [
            "Комплекс смешанного типа (mixed): открытый двор (outdoor) переходит в закрытое здание (indoor) через дверь/портал.",
            "Спуск в крипту на level -1 требует passage_kind=stairs."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="overgrown_courtyard",
        parts=[
            PartIntent(
                part_ref="overgrown_courtyard",
                role="courtyard",
                name="Заросший храмовый двор",
                public_name="Храмовый двор",
                description="Открытый двор, поросший густой травой, с обломками рухнувшей колоннады и разбитой каменной чашей.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=10,
                level=0,
                material="grass",
                details=[
                    DetailIntent(detail_ref="fallen_statue", name="Поваленная статуя божества", kind="cover", solid=True, cells=[[3, 2, 4, 3]]),
                    DetailIntent(detail_ref="rubble_piles", name="Груды битого камня", kind="hazard", cells=[[8, 2, 9, 3]]),
                    DetailIntent(detail_ref="dry_well", name="Осквернённый сухой колодец", kind="cover", solid=True, cells=[[5, 6, 6, 6]]),
                    DetailIntent(detail_ref="weed_thicket", name="Заросли колючей травы", kind="nature", cells=[[2, 7, 3, 8]]),
                ],
            ),
            PartIntent(
                part_ref="ruined_nave",
                role="sanctuary",
                name="Полуразрушенный неф",
                public_name="Разрушенный неф",
                description="Уцелевшая часть храма с частично обвалившимся сводом, расколотым алтарным камнем и следами костров.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=10,
                level=0,
                material="stone",
                connects_to="overgrown_courtyard",
                side="e",
                passage_kind="gate",
                passage_name="Обветшалый портал храма",
                details=[
                    DetailIntent(detail_ref="cracked_altar", name="Расколотый алтарный камень", kind="furniture", solid=True, cells=[[7, 4, 8, 5]]),
                    DetailIntent(detail_ref="standing_pillars", name="Уцелевшие пилоны свода", kind="cover", solid=True, cells=[[3, 2, 3, 2], [3, 7, 3, 7]]),
                    DetailIntent(detail_ref="ash_remains", name="Остывшее кострище бродяг", kind="light", cells=[[5, 5, 5, 5]]),
                    DetailIntent(detail_ref="collapsed_arch", name="Обвал каменной кладки", kind="cover", cells=[[1, 1, 2, 2]]),
                ],
            ),
            PartIntent(
                part_ref="crypt_undercroft",
                role="crypt",
                name="Погребальная крипта",
                public_name="Древняя крипта",
                description="Холодное подземное хранилище предков с каменными саркофагами вдоль стен и тяжелым запахом пыли.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=8,
                level=-1,
                material="stone",
                connects_to="ruined_nave",
                passage_kind="stairs",
                passage_name="Ступени в подземный склеп",
                details=[
                    DetailIntent(detail_ref="sarcophagi_north", name="Ряд надгробных саркофагов", kind="object", solid=True, cells=[[1, 1, 3, 1]]),
                    DetailIntent(detail_ref="sarcophagi_south", name="Южные надгробия", kind="object", solid=True, cells=[[1, 6, 3, 6]]),
                    DetailIntent(detail_ref="burial_niche", name="Стена с погребальными урнами", kind="furniture", cells=[[6, 2, 6, 5]]),
                    DetailIntent(detail_ref="eternal_flame", name="Угасший жертвенник", kind="light", cells=[[4, 3, 4, 4]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="overgrown_courtyard", side="w", kind="edge", band="temple_road", width=2, public_name="Старая храмовая дорога"),
        ],
        bands=[
            BandIntent(band_ref="temple_road", kind="road", axis="we", at=4, width=2),
        ],
    )
    return meta, intent


# ==============================================================================
# 3. ПЕЩЕРА
# ==============================================================================

def make_cave_passages_grotto() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "cave_passages_grotto",
        "version": "1.1.0",
        "archetype": "cave",
        "variant": "A",
        "variant_name": "Узкие переходы и просторный грот",
        "purpose": "Дикое подземное подземелье с естественными препятствиями, туннелями, озером и логовом хищника",
        "visual_concept": "Входная расщелина переходит в тесный лаз, открывающийся в высокий скальный грот с отдельной затопленной каверной-озером и боковым логовом.",
        "environment": "indoor",
        "materials": ["earth", "stone", "water"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча с отшельником или переговоры с разумными обитателями глубин в нейтральной зоне грота.",
            "exploration": "Поиск следов хищника в боковой нише, исследование скального берега подземного озера (ресурсы и находки задаются сценарием/мастером).",
            "combat": "Узкий лаз служит естественным тактическим бутылочным горлышком; сталагмиты и валун являются физическими твёрдыми преградами (solid=True по геометрии); подземное озеро отображено материалом water (правила плавания, глубины и преодоления воды определяются боевой системой)."
        },
        "allowable_adaptations": [
            "Замена озера на расщелину с лавой или бездонный провал",
            "Обустройство стоянки гоблинов или разбойников в центральном гроте",
            "Добавление тайного выхода из боковой ниши"
        ],
        "discovered_constraints": [
            "При форме cave маска пола детерминированно эродирует, поэтому детали должны отступать от углов габаритного прямоугольника.",
            "Ширина коридора ограничена максимум 2 клетками.",
            "Для отображения водоёма в закрытом подземелье (indoor) текущий контракт требует отдельного смежного участка с material='water', так как полосы BandIntent поддерживаются только для outdoor."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="entry_chasm",
        parts=[
            PartIntent(
                part_ref="entry_chasm",
                role="cave_entrance",
                name="Входная расщелина",
                public_name="Входной грот",
                description="Сырой каменный свод, куда едва пробивается дневной свет.",
                environment="indoor",
                shape="cave",
                cols=8,
                rows=8,
                level=0,
                material="earth",
                details=[
                    DetailIntent(detail_ref="scree", name="Осыпь щебня", kind="nature", cells=[[3, 2, 4, 2]]),
                    DetailIntent(detail_ref="boulder", name="Каменный валун", kind="cover", solid=True, cells=[[4, 5, 4, 5]]),
                ],
            ),
            PartIntent(
                part_ref="winding_tunnel",
                role="corridor",
                name="Узкий лаз",
                public_name="Каменный проход",
                description="Низкий вытянутый тоннель с трещинами в своде.",
                environment="indoor",
                shape="corridor",
                cols=6,
                rows=2,
                level=0,
                material="stone",
                connects_to="entry_chasm",
                side="e",
                passage_kind="passage",
                passage_name="Узкий лаз",
                details=[
                    DetailIntent(detail_ref="stalactites", name="Острые сталактиты", kind="nature", cells=[[2, 0, 3, 0]]),
                ],
            ),
            PartIntent(
                part_ref="great_grotto",
                role="grotto",
                name="Большой подземный грот",
                public_name="Подземный грот",
                description="Огромная каверна с высоким сводом, причудливыми сталагмитами и выходом к подземному озеру.",
                environment="indoor",
                shape="cave",
                cols=12,
                rows=10,
                level=0,
                material="stone",
                connects_to="winding_tunnel",
                side="e",
                passage_kind="arch",
                passage_name="Высокий скальный свод",
                details=[
                    DetailIntent(detail_ref="stalagmite_pillars", name="Колонны сталагмитов", kind="cover", solid=True, cells=[[3, 3, 3, 4]]),
                    DetailIntent(detail_ref="glowing_lichen", name="Светящийся мох", kind="light", cells=[[8, 2, 9, 2]]),
                    DetailIntent(detail_ref="rock_ledge", name="Скальный уступ", kind="cover", cells=[[4, 7, 6, 7]]),
                ],
            ),
            PartIntent(
                part_ref="subterranean_lake",
                role="water_basin",
                name="Подземное озеро",
                public_name="Подземное озеро",
                description="Холодная затопленная каверна с чистой подземной водой и отражающимися отблесками мха.",
                environment="indoor",
                shape="cave",
                cols=8,
                rows=8,
                level=0,
                material="water",
                connects_to="great_grotto",
                side="n",
                passage_kind="gap",
                passage_name="Скальный берег озера",
                details=[
                    DetailIntent(detail_ref="shimmering_pool", name="Фосфоресцирующая заводь", kind="light", cells=[[3, 3, 4, 4]]),
                ],
            ),
            PartIntent(
                part_ref="side_den",
                role="den",
                name="Боковая ниша",
                public_name="Тёмная ниша",
                description="Укромный глухой тупик, усыпанный костями и сухим мхом.",
                environment="indoor",
                shape="cave",
                cols=6,
                rows=6,
                level=0,
                material="earth",
                connects_to="great_grotto",
                side="s",
                passage_kind="passage",
                passage_name="Низкий пролаз",
                details=[
                    DetailIntent(detail_ref="beast_bedding", name="Лёжка хищника", kind="nature", cells=[[2, 3, 3, 4]]),
                    DetailIntent(detail_ref="bone_pile", name="Куча обглоданных костей", kind="object", cells=[[3, 2, 4, 2]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="entry_chasm", side="w", kind="gap", public_name="Вход в пещеру", width=1),
        ],
    )
    return meta, intent


def make_cave_multilevel_grottos() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "cave_multilevel_grottos",
        "version": "1.0.0",
        "archetype": "cave",
        "variant": "B",
        "variant_name": "Несколько гротов на разных уровнях",
        "purpose": "Многоуровневая пещерная система с вертикальным провалом, подземным водопадом и затопленным нижним ярусом",
        "visual_concept": "Верхний карстовый грот с сухим каменным карнизом обрывается в глубокую расщелину, по уступам которой можно спуститься на сырой нижний уровень (level -1).",
        "environment": "indoor",
        "materials": ["stone", "earth"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча с подземным проводником у края провала или переговоры со стражами нижнего яруса.",
            "exploration": "Поиск безопасного спуска по скользким скалам, обследование заросших светящимися спорами гротов, поиск жилы кристаллов.",
            "combat": "Стрельба с верхнего яруса вниз по врагам, риск падения в провал, использование сталагмитовых колонн как укрытий."
        },
        "allowable_adaptations": [
            "Заполнение нижнего яруса ядовитыми испарениями",
            "Превращение нижнего грота в гнездо пауков или логово троглодитов",
            "Устройство подвесного моста над пропастью"
        ],
        "discovered_constraints": [
            "Связка между уровнями 0 и -1 обеспечивается проходом вида stairs (каменные уступы/расщелина).",
            "Размеры пещер cave должны быть не менее 6 клеток для корректного формирования проходимого ядра."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="upper_gallery",
        parts=[
            PartIntent(
                part_ref="upper_gallery",
                role="cave_entrance",
                name="Верхняя карстовая галерея",
                public_name="Верхняя галерея",
                description="Сухой карстовый грот со следами копоти от факелов и естественными каменными ступенями.",
                environment="indoor",
                shape="cave",
                cols=8,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(detail_ref="torch_bracket", name="Факельное кострище", kind="light", cells=[[3, 3, 4, 3]]),
                    DetailIntent(detail_ref="rocky_ledge", name="Каменный карниз", kind="cover", solid=True, cells=[[5, 4, 5, 5]]),
                    DetailIntent(detail_ref="crystal_cluster", name="Друза горных кристаллов", kind="object", cells=[[2, 4, 2, 5]]),
                ],
            ),
            PartIntent(
                part_ref="chasm_overlook",
                role="chasm",
                name="Край глубокого провала",
                public_name="Край провала",
                description="Широкий скальный балкон над зияющей бездной, откуда доносится шум подземного водопада.",
                environment="indoor",
                shape="cave",
                cols=8,
                rows=8,
                level=0,
                material="stone",
                connects_to="upper_gallery",
                side="e",
                passage_kind="arch",
                passage_name="Широкий скальный пролом",
                details=[
                    DetailIntent(detail_ref="climbing_rig", name="Вбитые альпинистские крючья", kind="object", cells=[[3, 4, 4, 4]]),
                    DetailIntent(detail_ref="stalagmites_brink", name="Сталагмиты у края обрыва", kind="cover", solid=True, cells=[[4, 2, 4, 3]]),
                ],
            ),
            PartIntent(
                part_ref="lower_wet_cavern",
                role="cavern",
                name="Нижняя сырая каверна",
                public_name="Нижний грот",
                description="Огромный сырой грот на дне провала, куда стекают струи ледяной воды со стен.",
                environment="indoor",
                shape="cave",
                cols=10,
                rows=10,
                level=-1,
                material="earth",
                connects_to="chasm_overlook",
                passage_kind="stairs",
                passage_name="Скальный спуск по расщелине",
                details=[
                    DetailIntent(detail_ref="dripping_basin", name="Мокрая каменная чаша", kind="cover", solid=True, cells=[[4, 4, 6, 5]]),
                    DetailIntent(detail_ref="luminescent_spores", name="Светящиеся споровики", kind="light", cells=[[2, 3, 2, 4]]),
                    DetailIntent(detail_ref="mossy_pillar", name="Замшелая каменная колонна", kind="cover", solid=True, cells=[[6, 7, 7, 7]]),
                ],
            ),
            PartIntent(
                part_ref="submerged_lair",
                role="den",
                name="Затопленное логово",
                public_name="Затопленный карман",
                description="Глубокая полузатопленная ниша, уходящая в чёрную неподвижную воду.",
                environment="indoor",
                shape="cave",
                cols=6,
                rows=6,
                level=-1,
                material="water",
                connects_to="lower_wet_cavern",
                side="s",
                passage_kind="passage",
                passage_name="Затопленный проход",
                details=[
                    DetailIntent(detail_ref="floating_debris", name="Плавающий топляк и кости", kind="hazard", cells=[[2, 2, 3, 3]]),
                    DetailIntent(detail_ref="dry_nest", name="Сухой уступ гнездовища", kind="cover", cells=[[4, 2, 4, 3]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="upper_gallery", side="s", kind="gap", public_name="Входная расщелина с поверхности", width=1),
        ],
    )
    return meta, intent


# ==============================================================================
# 4. ЛЕС
# ==============================================================================

def make_forest_clearing_trail() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "forest_clearing_trail",
        "version": "1.0.0",
        "archetype": "forest",
        "variant": "A",
        "variant_name": "Поляна и извилистая тропа",
        "purpose": "Открытая лесная локация для путевых встреч, следопытства, засад и привала",
        "visual_concept": "Светлая опушка переходит в просторную поляну с вековым дубом и кострищем, переходящую на севере в глухую чащу.",
        "environment": "outdoor",
        "materials": ["grass", "earth"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Привал у костра с проводником или бродячими охотниками на солнечной поляне.",
            "exploration": "Поиск следов на тропе, изучение ведьминого кольца грибов, осмотр дупла векового дуба.",
            "combat": "Стрелковый бой на открытой поляне, использование векового дуба и гранитных выступов как укрытий, труднопроходимые корни как штраф перемещения."
        },
        "allowable_adaptations": [
            "Размещение ловушек браконьеров на тропе",
            "Превращение поляны в капище друидов с каменным кругом",
            "Добавление тумана или ночного освещения"
        ],
        "discovered_constraints": [
            "Открытые смежные участки outdoor соединяются краем во всю длину соприкосновения (passage kind edge).",
            "Сквозные полосы рельефа (полоса path) требуют строгого совпадения координат полосы на стыке."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="forest_verge",
        parts=[
            PartIntent(
                part_ref="forest_verge",
                role="field",
                name="Лесная опушка",
                public_name="Опушка леса",
                description="Редколесье на краю дремучей чащи, сквозь которое петляет протоптанная тропа.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=10,
                level=0,
                material="grass",
                details=[
                    DetailIntent(detail_ref="brambles", name="Колючий кустарник", kind="nature", solid=True, cells=[[2, 1, 3, 2]]),
                    DetailIntent(detail_ref="fallen_trunk", name="Поваленный ствол", kind="cover", cells=[[7, 7, 9, 7]]),
                    DetailIntent(detail_ref="moss_rock", name="Мшистый валун", kind="cover", cells=[[3, 7, 4, 7]]),
                ],
            ),
            PartIntent(
                part_ref="sunlit_clearing",
                role="field",
                name="Солнечная поляна",
                public_name="Лесная поляна",
                description="Широкая открытая поляна с могучим дубом в центре и следами привала.",
                environment="outdoor",
                shape="open",
                cols=14,
                rows=10,
                level=0,
                material="grass",
                connects_to="forest_verge",
                side="e",
                passage_kind="passage",
                passage_name="Тропа через деревья",
                details=[
                    DetailIntent(detail_ref="ancient_oak", name="Вековой дуб", kind="nature", solid=True, cells=[[6, 1, 7, 2]]),
                    DetailIntent(detail_ref="campfire", name="Охотничье кострище", kind="light", cells=[[6, 7, 7, 7]]),
                    DetailIntent(detail_ref="log_seat", name="Бревно у костра", kind="furniture", cells=[[5, 8, 8, 8]]),
                    DetailIntent(detail_ref="mushrooms", name="Ведьмино кольцо грибов", kind="nature", cells=[[11, 2, 12, 3]]),
                ],
            ),
            PartIntent(
                part_ref="dense_thicket",
                role="field",
                name="Густая чаща",
                public_name="Чаща",
                description="Сгустившиеся заросли, где ветви сплетаются над головой плотным пологом.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=8,
                level=0,
                material="earth",
                connects_to="sunlit_clearing",
                side="n",
                passage_kind="passage",
                passage_name="Просека в чащу",
                details=[
                    DetailIntent(detail_ref="twisted_roots", name="Узловатые корни", kind="hazard", cells=[[3, 3, 5, 4]]),
                    DetailIntent(detail_ref="granite_outcrop", name="Гранитные выступы", kind="cover", solid=True, cells=[[1, 1, 2, 2]]),
                    DetailIntent(detail_ref="ancient_stump", name="Трухлявый пень-великан", kind="object", cells=[[7, 5, 8, 5]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="forest_verge", side="w", kind="edge", band="forest_trail", width=2, public_name="Тропа из предгорий"),
        ],
        bands=[
            BandIntent(band_ref="forest_trail", kind="path", axis="we", at=4, width=2),
        ],
    )
    return meta, intent


def make_forest_stream_crossing() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "forest_stream_crossing",
        "version": "1.0.0",
        "archetype": "forest",
        "variant": "B",
        "variant_name": "Участок с ручьём и переправой",
        "purpose": "Лесная переправа с естественной водной преградой, деревянным мостом и прибрежными зарослями",
        "visual_concept": "Лесной тракт пересекает быстрый каменистый ручей по старому бревенчатому мосту, соединяя западный пологий берег с крутым восточным откосом.",
        "environment": "outdoor",
        "materials": ["grass", "earth"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча путевого обоза у моста, дорожная пошлина от разбойников, разговор с местным рыбаком.",
            "exploration": "Поиск брода в обход моста, осмотр следов у водопоя, тайник в полом дереве у заводи.",
            "combat": "Удержание узкого моста, форсирование водной преграды под обстрелом, засада на крутом восточном откосе."
        },
        "allowable_adaptations": [
            "Разрушение моста (требуется переправа вброд)",
            "Подъем воды во время паводка",
            "Устройство укрепленного заслона стражи"
        ],
        "discovered_constraints": [
            "Пересечение полосы дороги (road) и ручья (stream) автоматически формирует мост (bridge) генератором рельефа.",
            "Ширина открытых проходов со стороны берегов сохраняет целостность полос рельефа."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="west_bank",
        parts=[
            PartIntent(
                part_ref="west_bank",
                role="field",
                name="Западный пологий берег",
                public_name="Западный берег",
                description="Пологий лесной берег с накатанной грунтовой дорогой, ведущей к деревянному мосту.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=10,
                level=0,
                material="grass",
                details=[
                    DetailIntent(detail_ref="mile_marker", name="Дорожный верстовой столб", kind="object", solid=True, cells=[[3, 2, 3, 2]]),
                    DetailIntent(detail_ref="wayside_shrine", name="Придорожная божница", kind="light", cells=[[3, 7, 4, 7]]),
                    DetailIntent(detail_ref="willow_tree", name="Плакучая ива у воды", kind="nature", solid=True, cells=[[8, 1, 8, 2]]),
                ],
            ),
            PartIntent(
                part_ref="stream_crossing",
                role="crossing",
                name="Мост через лесной ручей",
                public_name="Переправа через ручей",
                description="Быстрый журчащий ручей с каменистым руслом, пересекаемый крепким настилом из бревен.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=10,
                level=0,
                material="grass",
                connects_to="west_bank",
                side="e",
                passage_kind="passage",
                passage_name="Выход на мост",
                details=[
                    DetailIntent(detail_ref="bridge_railings", name="Перила моста", kind="cover", cells=[[5, 3, 7, 3], [5, 6, 7, 6]]),
                    DetailIntent(detail_ref="river_stones", name="Скользкие валуны в русле", kind="nature", solid=True, cells=[[6, 1, 6, 1], [6, 8, 6, 8]]),
                    DetailIntent(detail_ref="reeds_bed", name="Заросли речного камыша", kind="nature", cells=[[2, 7, 3, 8]]),
                ],
            ),
            PartIntent(
                part_ref="east_bluff",
                role="field",
                name="Восточный лесистый откос",
                public_name="Восточный холм",
                description="Приподнятый откос над ручьем, с которого открывается отличный обзор на переправу.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=10,
                level=0,
                material="grass",
                connects_to="stream_crossing",
                side="e",
                passage_kind="passage",
                passage_name="Подъем на откос",
                details=[
                    DetailIntent(detail_ref="hunter_blind", name="Охотничья засидка за валунами", kind="cover", solid=True, cells=[[2, 2, 3, 2]]),
                    DetailIntent(detail_ref="lookout_pine", name="Высокая сосна", kind="nature", solid=True, cells=[[7, 7, 8, 8]]),
                    DetailIntent(detail_ref="camp_embers", name="Следы старого привала", kind="light", cells=[[4, 7, 5, 7]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="west_bank", side="w", kind="edge", band="trade_road", width=2, public_name="Тракт с запада"),
        ],
        bands=[
            BandIntent(band_ref="trade_road", kind="road", axis="we", at=4, width=2),
            BandIntent(band_ref="forest_brook", kind="stream", axis="ns", at=16, width=2),
        ],
    )
    return meta, intent


# ==============================================================================
# 5. ПОРТ
# ==============================================================================

def make_port_quay_warehouse() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "port_quay_warehouse",
        "version": "1.1.0",
        "archetype": "port",
        "variant": "A",
        "variant_name": "Набережная, причал и склад",
        "purpose": "Оживленная городская гавань с каменной набережной, деревянным пирсом над видимой водой и портовым складом",
        "visual_concept": "Широкая гранитная набережная переходит в выступающий в воду деревянный настил пирса с краном и примыкает к массивному пакгаузу, с двух сторон окружённому акваторией гавани.",
        "environment": "mixed",
        "materials": ["stone", "wood", "water"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Торг с купцами на набережной, наем матросов, разговор с таможенным инспектором в конторке пакгауза.",
            "exploration": "Осмотр опечатанных ящиков и стеллажей пакгауза (содержимое и добыча не генерируются декорацией автоматически, а задаются модулем).",
            "combat": "Штабеля ящиков и грузовой кран служат физическими препятствиями перемещению (solid=True согласно геометрии); деревянный пирс окружён видимой водой (material='water'), при этом механика падения в воду или плавания зависит от игровой системы."
        },
        "allowable_adaptations": [
            "Причаливание торгового когга или пиратского люггера к пирсу",
            "Пожар на складе с взрывоопасным грузом",
            "Ночной налет банды контрабандистов со стороны акватории"
        ],
        "discovered_constraints": [
            "Деревянный пирс соприкасается с гранитной набережной открытым переходом (edge/passage).",
            "Склад является крытым помещением (indoor), отделенным от набережной воротами (gate).",
            "Для выразительного восприятия причала как настила над водой акватория гавани представлена смежными открытыми участками с material='water'."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="granite_quay",
        parts=[
            PartIntent(
                part_ref="granite_quay",
                role="quay",
                name="Гранитная набережная",
                public_name="Портовая набережная",
                description="Широкая мощеная набережная с причальными тумбами, бухтами смоленых канатов и фонарными столбами.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=6,
                level=0,
                material="stone",
                details=[
                    DetailIntent(detail_ref="mooring_bollards", name="Чугунные причальные тумбы", kind="object", solid=True, cells=[[3, 5, 4, 5], [7, 5, 8, 5]]),
                    DetailIntent(detail_ref="cargo_pallets", name="Штабель грузовых поддонов", kind="cover", cells=[[2, 2, 3, 2]]),
                    DetailIntent(detail_ref="quay_lantern", name="Портовый масляный фонарь", kind="light", cells=[[5, 1, 5, 1]]),
                ],
            ),
            PartIntent(
                part_ref="cargo_pier",
                role="pier",
                name="Грузовой деревянный причал",
                public_name="Причал",
                description="Деревянный пирс на просмоленных сваях, уходящий в открытую акваторию гавани.",
                environment="outdoor",
                shape="open",
                cols=6,
                rows=8,
                level=0,
                material="wood",
                connects_to="granite_quay",
                side="s",
                passage_kind="passage",
                passage_name="Сходни на пирс",
                details=[
                    DetailIntent(detail_ref="cargo_crane", name="Поворотный грузовой кран", kind="object", solid=True, cells=[[1, 3, 2, 4]]),
                    DetailIntent(detail_ref="coiled_hawsers", name="Бухты тяжелых канатов", kind="cover", cells=[[4, 2, 4, 3]]),
                    DetailIntent(detail_ref="cleats", name="Швартовочные утки", kind="object", cells=[[1, 6, 1, 7], [4, 6, 4, 7]]),
                ],
            ),
            PartIntent(
                part_ref="harbor_warehouse",
                role="warehouse",
                name="Портовый пакгауз",
                public_name="Портовый склад",
                description="Высокое прохладное здание склада со стеллажами, опечатанными ящиками и конторкой смотрителя.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="wood",
                connects_to="granite_quay",
                side="e",
                passage_kind="gate",
                passage_name="Складские ворота",
                details=[
                    DetailIntent(detail_ref="crate_stacks", name="Штабеля опечатанных ящиков", kind="cover", solid=True, cells=[[2, 1, 3, 2]]),
                    DetailIntent(detail_ref="storage_racks", name="Многоярусные стеллажи", kind="furniture", cells=[[6, 1, 6, 4]]),
                    DetailIntent(detail_ref="overseer_desk", name="Конторка портового смотрителя", kind="furniture", cells=[[3, 4, 4, 4]]),
                ],
            ),
            PartIntent(
                part_ref="harbor_water_west",
                role="harbor",
                name="Западная гавань",
                public_name="Западная акватория",
                description="Глубокая портовая вода у западной стороны деревянного причала.",
                environment="outdoor",
                shape="open",
                cols=6,
                rows=8,
                level=0,
                material="water",
                connects_to="cargo_pier",
                side="w",
                passage_kind="passage",
                passage_name="Открытая вода",
                details=[
                    DetailIntent(detail_ref="floating_buoy", name="Сигнальный буй", kind="object", cells=[[2, 3, 2, 3]]),
                ],
            ),
            PartIntent(
                part_ref="harbor_water_east",
                role="harbor",
                name="Восточная гавань",
                public_name="Восточная акватория",
                description="Участок гавани между пакгаузом и восточным рейдом со сваями.",
                environment="outdoor",
                shape="open",
                cols=8,
                rows=8,
                level=0,
                material="water",
                connects_to="harbor_warehouse",
                side="s",
                passage_kind="passage",
                passage_name="Прискладская вода",
                details=[
                    DetailIntent(detail_ref="wooden_piles", name="Торчащие сваи", kind="cover", cells=[[1, 1, 1, 2]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="granite_quay", side="w", kind="edge", public_name="Вход с припортовой улицы", width=2),
        ],
    )
    return meta, intent


def make_port_fishing_pier() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "port_fishing_pier",
        "version": "1.0.0",
        "archetype": "port",
        "variant": "B",
        "variant_name": "Небольшая рыбацкая пристань",
        "purpose": "Камерная деревенская рыбацкая стоянка с песчаным берегом, деревянными мостками и хижиной",
        "visual_concept": "Уютный песчаный берег с кострищем для смоления лодок, узкие деревянные мостки над заросшей заводью и просоленная бревенчатая хижина.",
        "environment": "mixed",
        "materials": ["earth", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Разговор со старым рыбаком о чудовищах залива, покупка свежей рыбы или лодки, аренда снастей.",
            "exploration": "Поиск брошенных снастей под мостками, осмотр сушащихся сетей, изучение карты глубин в хижине.",
            "combat": "Сражение на узких качающихся мостках, использование перевернутой лодки как укрытия, смоляное кострище как огненная ловушка."
        },
        "allowable_adaptations": [
            "Прибытие лодки ночных контрабандистов",
            "Нападение глубоководных чудовищ прямо с мостков",
            "Превращение хижины в убежище беглого преступника"
        ],
        "discovered_constraints": [
            "Узкий деревянный пирс шириной 6 клеток требует точного центрирования деталей, чтобы не блокировать проход.",
            "Хижина рыбака — компактное деревянное помещение indoor."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="sandy_shore",
        parts=[
            PartIntent(
                part_ref="sandy_shore",
                role="shore",
                name="Песчаный берег залива",
                public_name="Песчаный берег",
                description="Отлогий берег с полосой влажного песка, кострищем для смоления и вешалами для просушки сетей.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=8,
                level=0,
                material="earth",
                details=[
                    DetailIntent(detail_ref="tar_firepit", name="Кострище для смоления лодок", kind="light", cells=[[3, 2, 4, 2]]),
                    DetailIntent(detail_ref="net_drying_racks", name="Вешала с рыболовными сетями", kind="cover", cells=[[2, 5, 4, 5]]),
                    DetailIntent(detail_ref="upturned_skiff", name="Перевёрнутая просмоленная плоскодонка", kind="cover", solid=True, cells=[[7, 3, 8, 4]]),
                ],
            ),
            PartIntent(
                part_ref="wooden_jetty",
                role="pier",
                name="Рыбацкие мостки",
                public_name="Деревянные мостки",
                description="Узкие бревенчатые мостки на кривых сваях с садками для живой рыбы.",
                environment="outdoor",
                shape="open",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="sandy_shore",
                side="s",
                passage_kind="passage",
                passage_name="Сходни на мостки",
                details=[
                    DetailIntent(detail_ref="fish_corfs", name="Садки для рыбы в воде", kind="nature", cells=[[1, 3, 2, 3]]),
                    DetailIntent(detail_ref="gutting_bench", name="Стол для разделки улова", kind="furniture", cells=[[4, 2, 4, 3]]),
                ],
            ),
            PartIntent(
                part_ref="fisher_shack",
                role="shack",
                name="Хижина старого рыбака",
                public_name="Рыбацкая хижина",
                description="Низкая просмоленная постройка с очагом, верстаком для вязания сетей и запахом сушеной рыбы.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="sandy_shore",
                side="w",
                passage_kind="door",
                passage_name="Дверь хижины",
                details=[
                    DetailIntent(detail_ref="smokehouse_stove", name="Каменная коптильня", kind="light", solid=True, cells=[[1, 1, 1, 2]]),
                    DetailIntent(detail_ref="tackle_table", name="Верстак со снастями", kind="furniture", cells=[[3, 4, 4, 4]]),
                    DetailIntent(detail_ref="salted_fish_barrels", name="Бочонки с соленой сельдью", kind="object", cells=[[4, 1, 4, 2]]),
                ],
            ),
            PartIntent(
                part_ref="fishing_water",
                role="water",
                name="Прибрежная вода",
                public_name="Вода у мостков",
                description="Мелкая прибрежная вода с садками и деревянными сваями.",
                environment="outdoor", shape="open", cols=8, rows=6,
                material="water", connects_to="wooden_jetty", side="e",
                passage_kind="gap", passage_name="Край мостков",
                details=[
                    DetailIntent(detail_ref="fish_corfs_water", name="Плавучие садки", kind="object", cells=[[2, 2, 3, 2]]),
                    DetailIntent(detail_ref="mooring_float", name="Швартовочный поплавок", kind="object", cells=[[5, 4, 5, 4]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="sandy_shore", side="n", kind="edge", public_name="Тропинка из прибрежной деревни", width=2),
        ],
    )
    return meta, intent


# ==============================================================================
# 6. РУИНЫ
# ==============================================================================

def make_ruins_manor_estate() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "ruins_manor_estate",
        "version": "1.0.0",
        "archetype": "ruins",
        "variant": "A",
        "variant_name": "Остатки усадьбы",
        "purpose": "Дворянская усадьба после пожара и запустения: одичавший парк, рухнувший зал и уцелевший сводчатый кабинет",
        "visual_concept": "Разрушенный парадный ансамбль: внешний парк с разбитым мраморным фонтаном ведет в рухнувший бальный зал, за которым сохранился запертый архивный кабинет.",
        "environment": "mixed",
        "materials": ["grass", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча с бродячим бардом или историком, контакт с призраком хозяйки поместья в бальном зале.",
            "exploration": "Взлом запечатанного архива лорда, раскопки фамильного герба под завалом, расшифровка тайных писем.",
            "combat": "Схватка среди поваленных мраморных колонн, укрытие за разбитыми стенами парка, узкий проход в кабинет."
        },
        "allowable_adaptations": [
            "Устройство стоянки охотников за сокровищами в парке",
            "Осквернение кабинета алтарем некроманта",
            "Обрушение части пола в подвал при неосторожном шаге"
        ],
        "discovered_constraints": [
            "Бальный зал имеет форму l_shape, воспроизводя сложную архитектуру разрушенного дворцового крыла.",
            "Сочетание открытого сада outdoor и закрытого кабинета indoor."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="overgrown_park",
        parts=[
            PartIntent(
                part_ref="overgrown_park",
                role="park",
                name="Одичавший усадебный парк",
                public_name="Заросший парк",
                description="Бывший регулярный парк с одичавшими кустами роз, разбитыми скамьями и иссохшим мраморным фонтаном.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=10,
                level=0,
                material="grass",
                details=[
                    DetailIntent(detail_ref="ruined_fountain", name="Расколотый мраморный фонтан", kind="cover", solid=True, cells=[[5, 4, 6, 5]]),
                    DetailIntent(detail_ref="overgrown_hedges", name="Одичавшая живая изгородь", kind="nature", solid=True, cells=[[2, 2, 4, 2]]),
                    DetailIntent(detail_ref="broken_benches", name="Обломки резных парковых скамей", kind="furniture", cells=[[8, 2, 9, 2]]),
                    DetailIntent(detail_ref="garden_urn", name="Мраморная урна с плющом", kind="nature", cells=[[3, 7, 3, 7]]),
                ],
            ),
            PartIntent(
                part_ref="collapsed_ballroom",
                role="hall",
                name="Рухнувший бальный зал",
                public_name="Бальный зал",
                description="Огромный парадный зал с провалившейся крышей, растрескавшимся паркетом и рухнувшей люстрой.",
                environment="indoor",
                shape="l_shape",
                cols=10,
                rows=10,
                level=0,
                material="stone",
                connects_to="overgrown_park",
                side="e",
                passage_kind="arch",
                passage_name="Парадная арка сада",
                details=[
                    DetailIntent(detail_ref="fallen_chandelier", name="Рухнувшая бронзовая люстра", kind="hazard", cells=[[4, 4, 5, 5]]),
                    DetailIntent(detail_ref="marble_pillars", name="Обломки мраморных колонн", kind="cover", solid=True, cells=[[2, 3, 2, 3], [2, 7, 2, 7]]),
                    DetailIntent(detail_ref="grand_fireplace", name="Разрушенный камин с гербом", kind="light", solid=True, cells=[[8, 7, 8, 8]]),
                ],
            ),
            PartIntent(
                part_ref="intact_study",
                role="study",
                name="Уцелевший кабинет лорда",
                public_name="Уцелевший кабинет",
                description="Изолированная сводчатая комната, чудом уцелевшая в пожаре: книги, карты поместья и секретер.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="collapsed_ballroom",
                side="s",
                passage_kind="door",
                passage_name="Окованная дубовая дверь",
                passage_state="locked",
                details=[
                    DetailIntent(detail_ref="carved_desk", name="Массивный письменный стол", kind="furniture", solid=True, cells=[[2, 2, 3, 3]]),
                    DetailIntent(detail_ref="parchment_shelves", name="Шкафы с семейными хрониками", kind="furniture", cells=[[1, 0, 4, 0]]),
                    DetailIntent(detail_ref="hidden_safe", name="Вмурованный в стену сейф", kind="object", cells=[[5, 2, 5, 3]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="overgrown_park", side="w", kind="edge", public_name="Въездная усадебная аллея", width=2),
        ],
    )
    return meta, intent


def make_ruins_watchpost() -> tuple[dict[str, Any], LayoutIntent]:
    meta = {
        "id": "ruins_watchpost",
        "version": "1.0.0",
        "archetype": "ruins",
        "variant": "B",
        "variant_name": "Разрушенный сторожевой пост",
        "purpose": "Остатки пограничного форта на перевале с барбаканом, основанием дозорной башни и подземным казематом",
        "visual_concept": "Укреплённый пост на перевале: внешний каменистый барбакан с остатками частокола переходит в круглую дозорную башню, откуда винтовая лестница ведет в каземат (level -1).",
        "environment": "mixed",
        "materials": ["stone", "earth"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Допрос захваченного дезертира в каземате, переговоры с пограничным разъездом у ворот.",
            "exploration": "Осмотр обрушенных перекрытий башни, поиск оружия в оружейной клети, разведка горного перевала.",
            "combat": "Стрельба из узких бойниц башни по внешнему двору, баррикадирование лестницы в каземат, узкие углы подземной части."
        },
        "allowable_adaptations": [
            "Обустройство сигнального костра на верхней площадке",
            "Завал лестницы в каземат камнями",
            "Размещение ловушек-растяжек во входном створе ворот"
        ],
        "discovered_constraints": [
            "Башня watchtower использует круглую форму circle, требуя осторожного отступа деталей от скругленных стен.",
            "Каземат расположен на подземном уровне level -1."
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False}
        }
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="outer_barbican",
        parts=[
            PartIntent(
                part_ref="outer_barbican",
                role="barbican",
                name="Внешний барбакан",
                public_name="Барбакан",
                description="Открытый двор передового укрепления с зубчатыми обломками стен, коновязью и следами осады.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=8,
                level=0,
                material="earth",
                details=[
                    DetailIntent(detail_ref="broken_gate_timber", name="Обломки дубовых ворот", kind="cover", solid=True, cells=[[2, 3, 2, 4]]),
                    DetailIntent(detail_ref="weapon_rack_ruin", name="Искореженные стойки для копий", kind="object", cells=[[6, 1, 7, 1]]),
                    DetailIntent(detail_ref="watch_brazier", name="Походная жаровня караула", kind="light", cells=[[5, 5, 5, 5]]),
                ],
            ),
            PartIntent(
                part_ref="watchtower_ruin",
                role="tower",
                name="Основание сторожевой башни",
                public_name="Сторожевая башня",
                description="Круглое каменное основание башни с узкими бойницами и каменной лестницей, уходящей вниз.",
                environment="indoor",
                shape="circle",
                cols=8,
                rows=8,
                level=0,
                material="stone",
                connects_to="outer_barbican",
                side="e",
                passage_kind="door",
                passage_name="Укрепленная дверь башни",
                details=[
                    DetailIntent(detail_ref="spiral_stairs_center", name="Каменная винтовая лестница", kind="cover", solid=True, cells=[[3, 3, 4, 4]]),
                    DetailIntent(detail_ref="archer_embrasures", name="Узкие бойницы в кладке", kind="cover", cells=[[5, 2, 5, 2], [5, 5, 5, 5]]),
                    DetailIntent(detail_ref="oil_lantern", name="Гарнизонный фонарь", kind="light", cells=[[2, 4, 2, 4]]),
                ],
            ),
            PartIntent(
                part_ref="dungeon_casemate",
                role="casemate",
                name="Подземный каземат и арсенал",
                public_name="Подземный каземат",
                description="Толстостенный подземный бункер для хранения пороха, стрел и содержания пленных.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=-1,
                material="stone",
                connects_to="watchtower_ruin",
                passage_kind="stairs",
                passage_name="Лестница в каземат",
                details=[
                    DetailIntent(detail_ref="armory_crates", name="Сундуки с арбалетными болтами", kind="object", solid=True, cells=[[1, 1, 2, 1]]),
                    DetailIntent(detail_ref="iron_grate_cell", name="Решётчатый карцер", kind="cover", cells=[[5, 1, 6, 2]]),
                    DetailIntent(detail_ref="interrogation_table", name="Каменный стол караульного", kind="furniture", cells=[[3, 3, 4, 3]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="outer_barbican", side="w", kind="gap", public_name="Пролом во внешней стене", width=2),
        ],
    )
    return meta, intent


# ==============================================================================
# СБОРКА И ПРОВЕРКА ВСЕХ 12 ШАБЛОНОВ
# ==============================================================================

ALL_TEMPLATES = [
    # Таверна
    make_tavern_roadside,
    make_tavern_urban_cellar,
    # Храм
    make_temple_compact_shrine,
    make_temple_ruined_courtyard,
    # Пещера
    make_cave_passages_grotto,
    make_cave_multilevel_grottos,
    # Лес
    make_forest_clearing_trail,
    make_forest_stream_crossing,
    # Порт
    make_port_quay_warehouse,
    make_port_fishing_pier,
    # Руины
    make_ruins_manor_estate,
    make_ruins_watchpost,
]


# These are authored art choices, resolved offline rather than inferred by the renderer.
VISUAL_GROUPS = {
    "table": "table_north table_south prep_table round_tables leather_chairs overseer_desk tackle_table carved_desk study_desk interrogation_table lectern",
    "bench": "bar_stools benches_north benches_south prayer_benches log_seat broken_benches gutting_bench",
    "bed": "bunks_north bunks_south",
    "nest": "beast_bedding dry_nest",
    "lichen": "glowing_lichen luminescent_spores",
    "glow": "shimmering_pool",
    "counter": "bar_counter long_bar",
    "shelf": "pantry_shelves bookcase bottle_racks vestment_press storage_racks parchment_shelves weapon_rack_ruin",
    "barrel": "ale_casks wine_tuns salted_fish_barrels",
    "crate": "smuggled_crates cargo_pallets crate_stacks armory_crates fish_corfs fish_corfs_water",
    "chest": "traveler_chests iron_strongbox relic_chest hidden_safe sarcophagi_north sarcophagi_south burial_niche",
    "hearth": "hearth stove iron_stove campfire camp_embers tar_firepit smokehouse_stove grand_fireplace watch_brazier",
    "torch": "wall_sconce cellar_lantern candle_stand incense_braziers eternal_flame torch_bracket quay_lantern oil_lantern",
    "altar": "grand_altar cracked_altar wayside_shrine holy_water_font ruined_fountain garden_urn fallen_statue dry_well",
    "pillar": "columns_west columns_east standing_pillars marble_pillars wooden_piles mossy_pillar spiral_stairs_center archer_embrasures iron_grate_cell",
    "rock": "boulder stalagmite_pillars stalagmites_brink rock_ledge rocky_ledge moss_rock granite_outcrop river_stones mile_marker grotto_rocks_east grotto_rocks_south",
    "rubble": "scree stalactites rubble_piles ash_remains collapsed_arch floating_debris fallen_chandelier broken_gate_timber ice_pit dripping_basin",
    "tree": "ancient_oak fallen_trunk ancient_stump willow_tree lookout_pine",
    "shrub": "brambles mushrooms twisted_roots weed_thicket overgrown_hedges",
    "reeds": "reeds_bed",
    "crystal": "crystal_cluster",
    "bones": "bone_pile",
    "net": "net_drying_racks coiled_hawsers climbing_rig bridge_railings hunter_blind upturned_skiff",
    "crane": "cargo_crane",
    "mooring": "mooring_bollards cleats floating_buoy mooring_float",
}
VISUAL_KEYS = {ref: f"feature:{key}" for key, refs in VISUAL_GROUPS.items() for ref in refs.split()}


def author_quality_v2(meta: dict[str, Any], intent: LayoutIntent) -> None:
    """Apply reviewed local furnishing plans without changing narrative part identities."""
    tid = meta["id"]
    meta["version"] = "1.2.0" if tid in {"tavern_roadside", "cave_passages_grotto", "port_quay_warehouse"} else "1.1.0"
    parts = {p.part_ref: p for p in intent.parts}

    def furnish(part_ref, placements):
        for detail in parts[part_ref].details:
            if detail.detail_ref in placements:
                detail.cells, detail.solid = placements[detail.detail_ref]

    if tid == "tavern_roadside":
        parts["common_room"].cols = 12
        parts["common_room"].rows = 10
        furnish("common_room", {
            "hearth": ([[5, 0, 6, 0]], True),
            "bar_counter": ([[1, 1, 1, 3], [2, 3, 3, 3]], True),
            "bar_stools": ([[2, 4, 2, 4], [4, 3, 4, 3]], False),
            "table_north": ([[8, 2, 9, 2]], True),
            "benches_north": ([[8, 1, 9, 1], [8, 3, 9, 3]], False),
            "table_south": ([[8, 7, 9, 7]], True),
            "benches_south": ([[8, 6, 9, 6], [8, 8, 9, 8]], False),
            "ale_casks": ([[1, 7, 1, 7], [2, 8, 2, 8]], True),
        })
        parts["kitchen_pantry"].cols = 6
        parts["kitchen_pantry"].rows = 7
        furnish("kitchen_pantry", {
            "stove": ([[0, 1, 0, 2]], True),
            "pantry_shelves": ([[2, 0, 4, 0]], True),
            "prep_table": ([[2, 4, 3, 4]], True),
        })
        parts["guest_rooms"].cols = 7
        parts["guest_rooms"].rows = 8
        furnish("guest_rooms", {
            "bunks_north": ([[4, 1, 5, 1]], True),
            "bunks_south": ([[4, 6, 5, 6]], True),
            "traveler_chests": ([[6, 1, 6, 1], [6, 6, 6, 6]], True),
        })
    elif tid == "cave_passages_grotto":
        parts["great_grotto"].cols = 14
        parts["great_grotto"].rows = 12
        furnish("great_grotto", {
            "stalagmite_pillars": ([[4, 3, 4, 4], [5, 4, 5, 4]], True),
            "glowing_lichen": ([[10, 2, 10, 2], [11, 3, 11, 3]], False),
            "rock_ledge": ([[3, 9, 4, 9]], False),
        })
        parts["great_grotto"].details.extend([
            DetailIntent(detail_ref="grotto_rocks_east", name="\u0421\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u043e\u0441\u0442\u0440\u043e\u0432\u043e\u043a", kind="cover", solid=True, cells=[[9, 5, 10, 5], [10, 6, 10, 6]]),
            DetailIntent(detail_ref="grotto_rocks_south", name="\u041d\u0438\u0437\u043a\u0438\u0435 \u0441\u0442\u0430\u043b\u0430\u0433\u043c\u0438\u0442\u044b", kind="cover", solid=True, cells=[[6, 8, 6, 8]]),
        ])
        # L-shaped rock islands and offset wall accents retain the existing cave floor algorithm.
        furnish("entry_chasm", {"scree": ([[2, 2, 2, 2], [3, 1, 3, 1]], False)})
    elif tid == "port_quay_warehouse":
        parts["cargo_pier"].cols = 4
        parts["cargo_pier"].rows = 10
        furnish("cargo_pier", {
            "cargo_crane": ([[1, 4, 1, 5]], True),
            "coiled_hawsers": ([[2, 3, 2, 3]], False),
            "cleats": ([[1, 8, 1, 8], [2, 8, 2, 8]], False),
        })
        parts["harbor_water_west"].cols = 4
        parts["harbor_water_west"].rows = 10
        parts["harbor_water_east"].cols = 4
        parts["harbor_water_east"].rows = 10
        parts["harbor_water_east"].connects_to = "cargo_pier"
        parts["harbor_water_east"].side = "e"
        parts["harbor_warehouse"].cols = 10
        parts["harbor_warehouse"].rows = 8
        furnish("harbor_warehouse", {
            "crate_stacks": ([[2, 1, 3, 2], [6, 1, 7, 2]], True),
            "storage_racks": ([[2, 6, 3, 6], [6, 6, 8, 6]], True),
            "overseer_desk": ([[8, 1, 8, 2]], True),
        })
        furnish("granite_quay", {
            "mooring_bollards": ([[2, 5, 2, 5], [9, 5, 9, 5]], True),
            "cargo_pallets": ([[1, 1, 2, 1], [8, 1, 9, 2]], True),
            "quay_lantern": ([[10, 0, 10, 0]], False),
        })
    elif tid == "tavern_urban_cellar":
        furnish("taproom", {"round_tables": ([[5, 2, 6, 2], [6, 5, 7, 5]], True),
                             "ale_casks": ([[1, 1, 1, 1], [1, 4, 1, 4]], True)})
    elif tid == "temple_ruined_courtyard":
        furnish("overgrown_courtyard", {"rubble_piles": ([[2, 2, 3, 2], [7, 6, 7, 6]], False)})
    elif tid == "forest_clearing_trail":
        furnish("sunlit_clearing", {"mushrooms": ([[2, 2, 2, 2], [6, 6, 6, 6]], False)})
    elif tid == "ruins_manor_estate":
        furnish("overgrown_park", {"overgrown_hedges": ([[1, 2, 1, 4], [7, 2, 7, 4]], True)})
    for part in intent.parts:
        for detail in part.details:
            detail.visual_key = VISUAL_KEYS[detail.detail_ref]


def build_and_save_template(factory_fn, output_dir: Path) -> dict[str, Any]:
    meta, intent = factory_fn()
    author_quality_v2(meta, intent)
    tid = meta["id"]
    tdir = output_dir / tid
    tdir.mkdir(parents=True, exist_ok=True)
    previews_dir = tdir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    provider = DeterministicLayoutProvider()

    # Проверка набора seed
    seed_results = {}
    root_id = f"tpl_{tid}"
    for seed in TEST_SEEDS:
        try:
            test_bp = provider.propose(intent, seed=seed, root_id=root_id)
            v_errs = validate(test_bp)
            if v_errs:
                seed_results[str(seed)] = f"validation_error: {'; '.join(v_errs)}"
            else:
                test_ids = {a.area_ref: a.area_ref for a in test_bp.areas}
                for a in test_bp.areas:
                    build_area(test_bp, a, root_id=root_id, ids=test_ids)
                assert Blueprint.from_json(test_bp.to_json()) == test_bp
                seed_results[str(seed)] = "passed"
        except Exception as e:
            seed_results[str(seed)] = f"exception: {e}"

    meta["tested_seeds"] = seed_results
    if any(result != "passed" for result in seed_results.values()):
        raise ValueError(f"{tid}: failed seeds: {seed_results}")

    # Выбранный рабочий Blueprint для выбранного seed
    bp = provider.propose(intent, seed=meta["selected_seed"], root_id=root_id)
    errors = validate(bp)
    validation_report = {
        "valid": len(errors) == 0,
        "errors": errors,
        "tested_seeds": seed_results,
        "area_count": len(bp.areas),
        "passage_count": len(bp.passages),
        "levels": sorted(list({a.level for a in bp.areas})),
        "detail_preservation": {}
    }

    # Анализ сохранения деталей и построение эскизов с разрешёнными ссылками переходов
    ids = {a.area_ref: a.area_ref for a in bp.areas}
    sketches = {}
    for area in bp.areas:
        sk = build_area(bp, area, root_id=root_id, ids=ids)
        sketches[area.area_ref] = sk
        orig_part = next(p for p in intent.parts if p.part_ref == area.area_ref)
        orig_details = {d.detail_ref: [list(r) for r in d.cells] for d in orig_part.details}
        res_details = {d.detail_ref: [list(r) for r in d.cells] for d in area.details}
        preservation = {}
        for dref, ocells in orig_details.items():
            rcells = res_details.get(dref)
            if rcells == ocells:
                preservation[dref] = "preserved"
            elif rcells is not None:
                preservation[dref] = f"shifted: {ocells} -> {rcells}"
            else:
                preservation[dref] = "dropped"
        validation_report["detail_preservation"][area.area_ref] = preservation

    # Сохранение артефактов
    (tdir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tdir / "intent.json").write_text(json.dumps(intent.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tdir / "blueprint.json").write_text(json.dumps(bp.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tdir / "validation.json").write_text(json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Экспорт структуры для frontend renderer
    render_payload = {
        "template_id": tid,
        "root_id": root_id,
        "entry": bp.entry,
        "levels": validation_report["levels"],
        "areas": [
            {
                "id": a.area_ref,
                "name": a.public_name,
                "offset": [a.offset[0], a.offset[1]],
                "level": a.level,
                "secret": a.secret,
                "status": "here" if a.area_ref == bp.entry else "remembered",
                "revision": 1,
                "sketch": sketches[a.area_ref]
            }
            for a in bp.areas
        ]
    }
    (tdir / "render_payload.json").write_text(json.dumps(render_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resource_path = ROOT / "app" / "content" / "layout_templates" / f"{tid}.json"
    resource = json.loads(resource_path.read_text(encoding="utf-8"))
    resource["intent"] = intent.model_dump(mode="json")
    resource["version"] = meta["version"]
    resource_path.write_text(json.dumps(resource, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{tid}] Built! Areas: {len(bp.areas)}, Passages: {len(bp.passages)}, Levels: {validation_report['levels']}")
    return meta


def build_all():
    print(f"Building all {len(ALL_TEMPLATES)} templates...")
    manifest = {
        "version": "1.1.0",
        "description": "Экспериментальная коллекция из 12 шаблонов локаций для TaleForge",
        "templates": []
    }
    for fn in ALL_TEMPLATES:
        meta = build_and_save_template(fn, TEMPLATES_DIR)
        manifest["templates"].append({
            "id": meta["id"],
            "archetype": meta["archetype"],
            "variant": meta["variant"],
            "variant_name": meta["variant_name"],
            "purpose": meta["purpose"],
            "environment": meta["environment"],
            "materials": meta["materials"],
            "selected_seed": meta["selected_seed"],
            "tested_seeds": meta["tested_seeds"]
        })
    manifest_path = EXP_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    build_all()
