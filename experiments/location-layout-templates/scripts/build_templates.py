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
from app.core.layout.intent import ApproachIntent, BandIntent, DetailIntent, LayoutIntent, ObjectSlotIntent, PartIntent
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
            "combat": "Твёрдые столы и стойка служат физическими препятствиями перемещению (solid=True согласно геометрии); очаг выступает источником света (kind='light'); сквозные проходы между входом с юга, кухней на западе и спальнями на востоке полностью свободны для манёвра.",
        },
        "allowable_adaptations": [
            "Добавление подвала/ледника под кухней",
            "Замена мебели на казарменную или лазаретную",
            "Добавление чердака или второго входа с заднего двора",
        ],
        "discovered_constraints": [
            "Двери между комнатами ограничены шириной 1 клетка.",
            "Детали вдоль стены с дверью смещаются алгоритмом _place_details, если попадают в створ проёма.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="hearth", name="Большой очаг", kind="light", solid=True, cells=[[3, 0, 4, 0]]
                    ),
                    DetailIntent(
                        detail_ref="bar_counter",
                        name="Барная стойка",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 1, 2], [2, 2, 2, 2]],
                    ),
                    DetailIntent(
                        detail_ref="bar_stools", name="Табуреты у стойки", kind="furniture", cells=[[2, 3, 2, 3]]
                    ),
                    DetailIntent(
                        detail_ref="table_north",
                        name="Северный обеденный стол",
                        kind="furniture",
                        solid=True,
                        cells=[[5, 2, 6, 2]],
                    ),
                    DetailIntent(
                        detail_ref="benches_north",
                        name="Скамьи северного стола",
                        kind="furniture",
                        cells=[[5, 1, 6, 1], [5, 3, 6, 3]],
                    ),
                    DetailIntent(
                        detail_ref="table_south",
                        name="Южный обеденный стол",
                        kind="furniture",
                        solid=True,
                        cells=[[5, 6, 6, 6]],
                    ),
                    DetailIntent(
                        detail_ref="benches_south", name="Скамья южного стола", kind="furniture", cells=[[5, 5, 6, 5]]
                    ),
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
                    DetailIntent(
                        detail_ref="stove", name="Кухонная печь", kind="light", solid=True, cells=[[0, 2, 0, 3]]
                    ),
                    DetailIntent(
                        detail_ref="pantry_shelves", name="Стеллажи с припасами", kind="furniture", cells=[[1, 0, 3, 0]]
                    ),
                    DetailIntent(
                        detail_ref="prep_table", name="Разделочный стол", kind="furniture", cells=[[2, 3, 2, 4]]
                    ),
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
                    DetailIntent(
                        detail_ref="bunks_north", name="Спальные лежанки", kind="furniture", cells=[[1, 1, 2, 1]]
                    ),
                    DetailIntent(
                        detail_ref="bunks_south", name="Дополнительные лежанки", kind="furniture", cells=[[1, 4, 2, 4]]
                    ),
                    DetailIntent(
                        detail_ref="traveler_chests", name="Кованые сундуки", kind="object", cells=[[4, 2, 4, 3]]
                    ),
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
            "combat": "Лестничный колодец как точка обороны, узкое пространство между бочками в подвале, темнота погреба.",
        },
        "allowable_adaptations": [
            "Превращение погреба в подземный ход в городскую канализацию",
            "Использование кабинета как штаба городской стражи или ростовщика",
            "Замена тайника на камеру для должников",
        ],
        "discovered_constraints": [
            "Связь между разными уровнями поддерживается строго через лестницу (stairs) или люк (hatch).",
            "Тайный проход помечается secret=True, скрывая помещение от публичной связности.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="long_bar",
                        name="Массивная барная стойка",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 2, 5]],
                    ),
                    DetailIntent(
                        detail_ref="round_tables", name="Круглые столы горожан", kind="furniture", cells=[[5, 2, 7, 3]]
                    ),
                    DetailIntent(
                        detail_ref="iron_stove", name="Чугунная печь", kind="light", solid=True, cells=[[8, 1, 8, 1]]
                    ),
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
                    DetailIntent(
                        detail_ref="leather_chairs",
                        name="Кожаные кресла и круглый столик",
                        kind="furniture",
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="bookcase", name="Шкаф с бухгалтерскими книгами", kind="object", cells=[[1, 0, 4, 0]]
                    ),
                    DetailIntent(
                        detail_ref="wall_sconce",
                        name="Бронзовый настенный светильник",
                        kind="light",
                        cells=[[5, 2, 5, 2]],
                    ),
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
                    DetailIntent(
                        detail_ref="wine_tuns",
                        name="Большие дубовые чаны",
                        kind="object",
                        solid=True,
                        cells=[[1, 1, 1, 3]],
                    ),
                    DetailIntent(
                        detail_ref="bottle_racks", name="Стеллажи с винами", kind="furniture", cells=[[3, 1, 6, 1]]
                    ),
                    DetailIntent(
                        detail_ref="ice_pit",
                        name="Ледник для скоропортящихся продуктов",
                        kind="cover",
                        cells=[[5, 5, 6, 6]],
                    ),
                    DetailIntent(
                        detail_ref="cellar_lantern",
                        name="Подвесной масляный фонарь",
                        kind="light",
                        cells=[[3, 4, 3, 4]],
                    ),
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
                    DetailIntent(
                        detail_ref="iron_strongbox",
                        name="Кованый сундук гильдии",
                        kind="object",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="smuggled_crates", name="Ящики с контрабандой", kind="object", cells=[[1, 2, 2, 2]]
                    ),
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
            "combat": "Несущие каменные колонны как полное укрытие, алтарное возвышение для преимущества высоты, узкие проходы между нефом и притвором.",
        },
        "allowable_adaptations": [
            "Осквернение алтаря темными культами",
            "Добавление крипты под алтарем",
            "Превращение ризницы в келью затворника",
        ],
        "discovered_constraints": [
            "Колонны оформляются как solid=True детали, создавая непроходимые препятствия на карте.",
            "Проход между притвором и святилищем выполнен широкой аркой (passage_kind=arch).",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="holy_water_font",
                        name="Чаша со святой водой",
                        kind="object",
                        solid=True,
                        cells=[[3, 2, 4, 2]],
                    ),
                    DetailIntent(
                        detail_ref="prayer_benches",
                        name="Скамьи для молящихся",
                        kind="furniture",
                        cells=[[1, 1, 1, 3], [6, 1, 6, 3]],
                    ),
                    DetailIntent(
                        detail_ref="candle_stand", name="Подсвечник с лампадами", kind="light", cells=[[3, 0, 4, 0]]
                    ),
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
                    DetailIntent(
                        detail_ref="grand_altar",
                        name="Мраморный алтарь",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 1, 5, 2]],
                    ),
                    DetailIntent(
                        detail_ref="columns_west",
                        name="Западный ряд колонн",
                        kind="cover",
                        solid=True,
                        cells=[[2, 4, 2, 4], [2, 8, 2, 8]],
                    ),
                    DetailIntent(
                        detail_ref="columns_east",
                        name="Восточный ряд колонн",
                        kind="cover",
                        solid=True,
                        cells=[[7, 4, 7, 4], [7, 8, 7, 8]],
                    ),
                    DetailIntent(
                        detail_ref="incense_braziers",
                        name="Курильницы с благовониями",
                        kind="light",
                        cells=[[3, 1, 3, 1], [6, 1, 6, 1]],
                    ),
                    DetailIntent(
                        detail_ref="lectern", name="Пюпитр священнослужителя", kind="furniture", cells=[[4, 4, 5, 4]]
                    ),
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
                    DetailIntent(
                        detail_ref="relic_chest",
                        name="Сундук с реликвиями",
                        kind="object",
                        solid=True,
                        cells=[[4, 1, 4, 2]],
                    ),
                    DetailIntent(
                        detail_ref="vestment_press",
                        name="Шкаф с ритуальными облачениями",
                        kind="furniture",
                        cells=[[1, 0, 3, 0]],
                    ),
                    DetailIntent(
                        detail_ref="study_desk", name="Стол летописца", kind="furniture", cells=[[2, 4, 3, 4]]
                    ),
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
            "combat": "Стычка во дворе с использованием обломков стен и валунов как укрытий, тесный бой в крипте против нежити.",
        },
        "allowable_adaptations": [
            "Заселение двора лагерем наёмников или культистов",
            "Затопление крипты грунтовыми водами",
            "Размещение ловушек на ступенях в подземелье",
        ],
        "discovered_constraints": [
            "Комплекс смешанного типа (mixed): открытый двор (outdoor) переходит в закрытое здание (indoor) через дверь/портал.",
            "Спуск в крипту на level -1 требует passage_kind=stairs.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="fallen_statue",
                        name="Поваленная статуя божества",
                        kind="cover",
                        solid=True,
                        cells=[[3, 2, 4, 3]],
                    ),
                    DetailIntent(
                        detail_ref="rubble_piles", name="Груды битого камня", kind="hazard", cells=[[8, 2, 9, 3]]
                    ),
                    DetailIntent(
                        detail_ref="dry_well",
                        name="Осквернённый сухой колодец",
                        kind="cover",
                        solid=True,
                        cells=[[5, 6, 6, 6]],
                    ),
                    DetailIntent(
                        detail_ref="weed_thicket", name="Заросли колючей травы", kind="nature", cells=[[2, 7, 3, 8]]
                    ),
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
                    DetailIntent(
                        detail_ref="cracked_altar",
                        name="Расколотый алтарный камень",
                        kind="furniture",
                        solid=True,
                        cells=[[7, 4, 8, 5]],
                    ),
                    DetailIntent(
                        detail_ref="standing_pillars",
                        name="Уцелевшие пилоны свода",
                        kind="cover",
                        solid=True,
                        cells=[[3, 2, 3, 2], [3, 7, 3, 7]],
                    ),
                    DetailIntent(
                        detail_ref="ash_remains", name="Остывшее кострище бродяг", kind="light", cells=[[5, 5, 5, 5]]
                    ),
                    DetailIntent(
                        detail_ref="collapsed_arch", name="Обвал каменной кладки", kind="cover", cells=[[1, 1, 2, 2]]
                    ),
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
                    DetailIntent(
                        detail_ref="sarcophagi_north",
                        name="Ряд надгробных саркофагов",
                        kind="object",
                        solid=True,
                        cells=[[1, 1, 3, 1]],
                    ),
                    DetailIntent(
                        detail_ref="sarcophagi_south",
                        name="Южные надгробия",
                        kind="object",
                        solid=True,
                        cells=[[1, 6, 3, 6]],
                    ),
                    DetailIntent(
                        detail_ref="burial_niche",
                        name="Стена с погребальными урнами",
                        kind="furniture",
                        cells=[[6, 2, 6, 5]],
                    ),
                    DetailIntent(
                        detail_ref="eternal_flame", name="Угасший жертвенник", kind="light", cells=[[4, 3, 4, 4]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="overgrown_courtyard",
                side="w",
                kind="edge",
                band="temple_road",
                width=2,
                public_name="Старая храмовая дорога",
            ),
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
            "combat": "Узкий лаз служит естественным тактическим бутылочным горлышком; сталагмиты и валун являются физическими твёрдыми преградами (solid=True по геометрии); подземное озеро отображено материалом water (правила плавания, глубины и преодоления воды определяются боевой системой).",
        },
        "allowable_adaptations": [
            "Замена озера на расщелину с лавой или бездонный провал",
            "Обустройство стоянки гоблинов или разбойников в центральном гроте",
            "Добавление тайного выхода из боковой ниши",
        ],
        "discovered_constraints": [
            "При форме cave маска пола детерминированно эродирует, поэтому детали должны отступать от углов габаритного прямоугольника.",
            "Ширина коридора ограничена максимум 2 клетками.",
            "Для отображения водоёма в закрытом подземелье (indoor) текущий контракт требует отдельного смежного участка с material='water', так как полосы BandIntent поддерживаются только для outdoor.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="boulder", name="Каменный валун", kind="cover", solid=True, cells=[[4, 5, 4, 5]]
                    ),
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
                    DetailIntent(
                        detail_ref="stalactites", name="Острые сталактиты", kind="nature", cells=[[2, 0, 3, 0]]
                    ),
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
                    DetailIntent(
                        detail_ref="stalagmite_pillars",
                        name="Колонны сталагмитов",
                        kind="cover",
                        solid=True,
                        cells=[[3, 3, 3, 4]],
                    ),
                    DetailIntent(
                        detail_ref="glowing_lichen", name="Светящийся мох", kind="light", cells=[[8, 2, 9, 2]]
                    ),
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
                    DetailIntent(
                        detail_ref="shimmering_pool", name="Фосфоресцирующая заводь", kind="light", cells=[[3, 3, 4, 4]]
                    ),
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
                    DetailIntent(
                        detail_ref="bone_pile", name="Куча обглоданных костей", kind="object", cells=[[3, 2, 4, 2]]
                    ),
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
            "combat": "Стрельба с верхнего яруса вниз по врагам, риск падения в провал, использование сталагмитовых колонн как укрытий.",
        },
        "allowable_adaptations": [
            "Заполнение нижнего яруса ядовитыми испарениями",
            "Превращение нижнего грота в гнездо пауков или логово троглодитов",
            "Устройство подвесного моста над пропастью",
        ],
        "discovered_constraints": [
            "Связка между уровнями 0 и -1 обеспечивается проходом вида stairs (каменные уступы/расщелина).",
            "Размеры пещер cave должны быть не менее 6 клеток для корректного формирования проходимого ядра.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="torch_bracket", name="Факельное кострище", kind="light", cells=[[3, 3, 4, 3]]
                    ),
                    DetailIntent(
                        detail_ref="rocky_ledge", name="Каменный карниз", kind="cover", solid=True, cells=[[5, 4, 5, 5]]
                    ),
                    DetailIntent(
                        detail_ref="crystal_cluster",
                        name="Друза горных кристаллов",
                        kind="object",
                        cells=[[2, 4, 2, 5]],
                    ),
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
                    DetailIntent(
                        detail_ref="climbing_rig",
                        name="Вбитые альпинистские крючья",
                        kind="object",
                        cells=[[3, 4, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="stalagmites_brink",
                        name="Сталагмиты у края обрыва",
                        kind="cover",
                        solid=True,
                        cells=[[4, 2, 4, 3]],
                    ),
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
                    DetailIntent(
                        detail_ref="dripping_basin",
                        name="Мокрая каменная чаша",
                        kind="cover",
                        solid=True,
                        cells=[[4, 4, 6, 5]],
                    ),
                    DetailIntent(
                        detail_ref="luminescent_spores", name="Светящиеся споровики", kind="light", cells=[[2, 3, 2, 4]]
                    ),
                    DetailIntent(
                        detail_ref="mossy_pillar",
                        name="Замшелая каменная колонна",
                        kind="cover",
                        solid=True,
                        cells=[[6, 7, 7, 7]],
                    ),
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
                    DetailIntent(
                        detail_ref="floating_debris",
                        name="Плавающий топляк и кости",
                        kind="hazard",
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="dry_nest", name="Сухой уступ гнездовища", kind="cover", cells=[[4, 2, 4, 3]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="upper_gallery", side="s", kind="gap", public_name="Входная расщелина с поверхности", width=1
            ),
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
            "combat": "Стрелковый бой на открытой поляне, использование векового дуба и гранитных выступов как укрытий, труднопроходимые корни как штраф перемещения.",
        },
        "allowable_adaptations": [
            "Размещение ловушек браконьеров на тропе",
            "Превращение поляны в капище друидов с каменным кругом",
            "Добавление тумана или ночного освещения",
        ],
        "discovered_constraints": [
            "Открытые смежные участки outdoor соединяются краем во всю длину соприкосновения (passage kind edge).",
            "Сквозные полосы рельефа (полоса path) требуют строгого совпадения координат полосы на стыке.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="brambles", name="Колючий кустарник", kind="nature", solid=True, cells=[[2, 1, 3, 2]]
                    ),
                    DetailIntent(
                        detail_ref="fallen_trunk", name="Поваленный ствол", kind="cover", cells=[[7, 7, 9, 7]]
                    ),
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
                    DetailIntent(
                        detail_ref="ancient_oak", name="Вековой дуб", kind="nature", solid=True, cells=[[6, 1, 7, 2]]
                    ),
                    DetailIntent(detail_ref="campfire", name="Охотничье кострище", kind="light", cells=[[6, 7, 7, 7]]),
                    DetailIntent(detail_ref="log_seat", name="Бревно у костра", kind="furniture", cells=[[5, 8, 8, 8]]),
                    DetailIntent(
                        detail_ref="mushrooms", name="Ведьмино кольцо грибов", kind="nature", cells=[[11, 2, 12, 3]]
                    ),
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
                    DetailIntent(
                        detail_ref="twisted_roots", name="Узловатые корни", kind="hazard", cells=[[3, 3, 5, 4]]
                    ),
                    DetailIntent(
                        detail_ref="granite_outcrop",
                        name="Гранитные выступы",
                        kind="cover",
                        solid=True,
                        cells=[[1, 1, 2, 2]],
                    ),
                    DetailIntent(
                        detail_ref="ancient_stump", name="Трухлявый пень-великан", kind="object", cells=[[7, 5, 8, 5]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="forest_verge",
                side="w",
                kind="edge",
                band="forest_trail",
                width=2,
                public_name="Тропа из предгорий",
            ),
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
            "combat": "Удержание узкого моста, форсирование водной преграды под обстрелом, засада на крутом восточном откосе.",
        },
        "allowable_adaptations": [
            "Разрушение моста (требуется переправа вброд)",
            "Подъем воды во время паводка",
            "Устройство укрепленного заслона стражи",
        ],
        "discovered_constraints": [
            "Пересечение полосы дороги (road) и ручья (stream) автоматически формирует мост (bridge) генератором рельефа.",
            "Ширина открытых проходов со стороны берегов сохраняет целостность полос рельефа.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="mile_marker",
                        name="Дорожный верстовой столб",
                        kind="object",
                        solid=True,
                        cells=[[3, 2, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="wayside_shrine", name="Придорожная божница", kind="light", cells=[[3, 7, 4, 7]]
                    ),
                    DetailIntent(
                        detail_ref="willow_tree",
                        name="Плакучая ива у воды",
                        kind="nature",
                        solid=True,
                        cells=[[8, 1, 8, 2]],
                    ),
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
                    DetailIntent(
                        detail_ref="bridge_railings",
                        name="Перила моста",
                        kind="cover",
                        cells=[[5, 3, 7, 3], [5, 6, 7, 6]],
                    ),
                    DetailIntent(
                        detail_ref="river_stones",
                        name="Скользкие валуны в русле",
                        kind="nature",
                        solid=True,
                        cells=[[6, 1, 6, 1], [6, 8, 6, 8]],
                    ),
                    DetailIntent(
                        detail_ref="reeds_bed", name="Заросли речного камыша", kind="nature", cells=[[2, 7, 3, 8]]
                    ),
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
                    DetailIntent(
                        detail_ref="hunter_blind",
                        name="Охотничья засидка за валунами",
                        kind="cover",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="lookout_pine", name="Высокая сосна", kind="nature", solid=True, cells=[[7, 7, 8, 8]]
                    ),
                    DetailIntent(
                        detail_ref="camp_embers", name="Следы старого привала", kind="light", cells=[[4, 7, 5, 7]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="west_bank", side="w", kind="edge", band="trade_road", width=2, public_name="Тракт с запада"
            ),
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
            "combat": "Штабеля ящиков и грузовой кран служат физическими препятствиями перемещению (solid=True согласно геометрии); деревянный пирс окружён видимой водой (material='water'), при этом механика падения в воду или плавания зависит от игровой системы.",
        },
        "allowable_adaptations": [
            "Причаливание торгового когга или пиратского люггера к пирсу",
            "Пожар на складе с взрывоопасным грузом",
            "Ночной налет банды контрабандистов со стороны акватории",
        ],
        "discovered_constraints": [
            "Деревянный пирс соприкасается с гранитной набережной открытым переходом (edge/passage).",
            "Склад является крытым помещением (indoor), отделенным от набережной воротами (gate).",
            "Для выразительного восприятия причала как настила над водой акватория гавани представлена смежными открытыми участками с material='water'.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="mooring_bollards",
                        name="Чугунные причальные тумбы",
                        kind="object",
                        solid=True,
                        cells=[[3, 5, 4, 5], [7, 5, 8, 5]],
                    ),
                    DetailIntent(
                        detail_ref="cargo_pallets", name="Штабель грузовых поддонов", kind="cover", cells=[[2, 2, 3, 2]]
                    ),
                    DetailIntent(
                        detail_ref="quay_lantern", name="Портовый масляный фонарь", kind="light", cells=[[5, 1, 5, 1]]
                    ),
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
                    DetailIntent(
                        detail_ref="cargo_crane",
                        name="Поворотный грузовой кран",
                        kind="object",
                        solid=True,
                        cells=[[1, 3, 2, 4]],
                    ),
                    DetailIntent(
                        detail_ref="coiled_hawsers", name="Бухты тяжелых канатов", kind="cover", cells=[[4, 2, 4, 3]]
                    ),
                    DetailIntent(
                        detail_ref="cleats", name="Швартовочные утки", kind="object", cells=[[1, 6, 1, 7], [4, 6, 4, 7]]
                    ),
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
                    DetailIntent(
                        detail_ref="crate_stacks",
                        name="Штабеля опечатанных ящиков",
                        kind="cover",
                        solid=True,
                        cells=[[2, 1, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="storage_racks", name="Многоярусные стеллажи", kind="furniture", cells=[[6, 1, 6, 4]]
                    ),
                    DetailIntent(
                        detail_ref="overseer_desk",
                        name="Конторка портового смотрителя",
                        kind="furniture",
                        cells=[[3, 4, 4, 4]],
                    ),
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
                    DetailIntent(
                        detail_ref="floating_buoy", name="Сигнальный буй", kind="object", cells=[[2, 3, 2, 3]]
                    ),
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
            ApproachIntent(
                part_ref="granite_quay", side="w", kind="edge", public_name="Вход с припортовой улицы", width=2
            ),
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
            "combat": "Сражение на узких качающихся мостках, использование перевернутой лодки как укрытия, смоляное кострище как огненная ловушка.",
        },
        "allowable_adaptations": [
            "Прибытие лодки ночных контрабандистов",
            "Нападение глубоководных чудовищ прямо с мостков",
            "Превращение хижины в убежище беглого преступника",
        ],
        "discovered_constraints": [
            "Узкий деревянный пирс шириной 6 клеток требует точного центрирования деталей, чтобы не блокировать проход.",
            "Хижина рыбака — компактное деревянное помещение indoor.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="tar_firepit", name="Кострище для смоления лодок", kind="light", cells=[[3, 2, 4, 2]]
                    ),
                    DetailIntent(
                        detail_ref="net_drying_racks",
                        name="Вешала с рыболовными сетями",
                        kind="cover",
                        cells=[[2, 5, 4, 5]],
                    ),
                    DetailIntent(
                        detail_ref="upturned_skiff",
                        name="Перевёрнутая просмоленная плоскодонка",
                        kind="cover",
                        solid=True,
                        cells=[[7, 3, 8, 4]],
                    ),
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
                    DetailIntent(
                        detail_ref="fish_corfs", name="Садки для рыбы в воде", kind="nature", cells=[[1, 3, 2, 3]]
                    ),
                    DetailIntent(
                        detail_ref="gutting_bench",
                        name="Стол для разделки улова",
                        kind="furniture",
                        cells=[[4, 2, 4, 3]],
                    ),
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
                    DetailIntent(
                        detail_ref="smokehouse_stove",
                        name="Каменная коптильня",
                        kind="light",
                        solid=True,
                        cells=[[1, 1, 1, 2]],
                    ),
                    DetailIntent(
                        detail_ref="tackle_table", name="Верстак со снастями", kind="furniture", cells=[[3, 4, 4, 4]]
                    ),
                    DetailIntent(
                        detail_ref="salted_fish_barrels",
                        name="Бочонки с соленой сельдью",
                        kind="object",
                        cells=[[4, 1, 4, 2]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="fishing_water",
                role="water",
                name="Прибрежная вода",
                public_name="Вода у мостков",
                description="Мелкая прибрежная вода с садками и деревянными сваями.",
                environment="outdoor",
                shape="open",
                cols=8,
                rows=6,
                material="water",
                connects_to="wooden_jetty",
                side="e",
                passage_kind="gap",
                passage_name="Край мостков",
                details=[
                    DetailIntent(
                        detail_ref="fish_corfs_water", name="Плавучие садки", kind="object", cells=[[2, 2, 3, 2]]
                    ),
                    DetailIntent(
                        detail_ref="mooring_float", name="Швартовочный поплавок", kind="object", cells=[[5, 4, 5, 4]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="sandy_shore", side="n", kind="edge", public_name="Тропинка из прибрежной деревни", width=2
            ),
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
            "combat": "Схватка среди поваленных мраморных колонн, укрытие за разбитыми стенами парка, узкий проход в кабинет.",
        },
        "allowable_adaptations": [
            "Устройство стоянки охотников за сокровищами в парке",
            "Осквернение кабинета алтарем некроманта",
            "Обрушение части пола в подвал при неосторожном шаге",
        ],
        "discovered_constraints": [
            "Бальный зал имеет форму l_shape, воспроизводя сложную архитектуру разрушенного дворцового крыла.",
            "Сочетание открытого сада outdoor и закрытого кабинета indoor.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="ruined_fountain",
                        name="Расколотый мраморный фонтан",
                        kind="cover",
                        solid=True,
                        cells=[[5, 4, 6, 5]],
                    ),
                    DetailIntent(
                        detail_ref="overgrown_hedges",
                        name="Одичавшая живая изгородь",
                        kind="nature",
                        solid=True,
                        cells=[[2, 2, 4, 2]],
                    ),
                    DetailIntent(
                        detail_ref="broken_benches",
                        name="Обломки резных парковых скамей",
                        kind="furniture",
                        cells=[[8, 2, 9, 2]],
                    ),
                    DetailIntent(
                        detail_ref="garden_urn", name="Мраморная урна с плющом", kind="nature", cells=[[3, 7, 3, 7]]
                    ),
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
                    DetailIntent(
                        detail_ref="fallen_chandelier",
                        name="Рухнувшая бронзовая люстра",
                        kind="hazard",
                        cells=[[4, 4, 5, 5]],
                    ),
                    DetailIntent(
                        detail_ref="marble_pillars",
                        name="Обломки мраморных колонн",
                        kind="cover",
                        solid=True,
                        cells=[[2, 3, 2, 3], [2, 7, 2, 7]],
                    ),
                    DetailIntent(
                        detail_ref="grand_fireplace",
                        name="Разрушенный камин с гербом",
                        kind="light",
                        solid=True,
                        cells=[[8, 7, 8, 8]],
                    ),
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
                    DetailIntent(
                        detail_ref="carved_desk",
                        name="Массивный письменный стол",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="parchment_shelves",
                        name="Шкафы с семейными хрониками",
                        kind="furniture",
                        cells=[[1, 0, 4, 0]],
                    ),
                    DetailIntent(
                        detail_ref="hidden_safe", name="Вмурованный в стену сейф", kind="object", cells=[[5, 2, 5, 3]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="overgrown_park", side="w", kind="edge", public_name="Въездная усадебная аллея", width=2
            ),
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
            "combat": "Стрельба из узких бойниц башни по внешнему двору, баррикадирование лестницы в каземат, узкие углы подземной части.",
        },
        "allowable_adaptations": [
            "Обустройство сигнального костра на верхней площадке",
            "Завал лестницы в каземат камнями",
            "Размещение ловушек-растяжек во входном створе ворот",
        ],
        "discovered_constraints": [
            "Башня watchtower использует круглую форму circle, требуя осторожного отступа деталей от скругленных стен.",
            "Каземат расположен на подземном уровне level -1.",
        ],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
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
                    DetailIntent(
                        detail_ref="broken_gate_timber",
                        name="Обломки дубовых ворот",
                        kind="cover",
                        solid=True,
                        cells=[[2, 3, 2, 4]],
                    ),
                    DetailIntent(
                        detail_ref="weapon_rack_ruin",
                        name="Искореженные стойки для копий",
                        kind="object",
                        cells=[[6, 1, 7, 1]],
                    ),
                    DetailIntent(
                        detail_ref="watch_brazier", name="Походная жаровня караула", kind="light", cells=[[5, 5, 5, 5]]
                    ),
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
                    DetailIntent(
                        detail_ref="spiral_stairs_center",
                        name="Каменная винтовая лестница",
                        kind="cover",
                        solid=True,
                        cells=[[3, 3, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="archer_embrasures",
                        name="Узкие бойницы в кладке",
                        kind="cover",
                        cells=[[5, 2, 5, 2], [5, 5, 5, 5]],
                    ),
                    DetailIntent(
                        detail_ref="oil_lantern", name="Гарнизонный фонарь", kind="light", cells=[[2, 4, 2, 4]]
                    ),
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
                    DetailIntent(
                        detail_ref="armory_crates",
                        name="Сундуки с арбалетными болтами",
                        kind="object",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="iron_grate_cell", name="Решётчатый карцер", kind="cover", cells=[[5, 1, 6, 2]]
                    ),
                    DetailIntent(
                        detail_ref="interrogation_table",
                        name="Каменный стол караульного",
                        kind="furniture",
                        cells=[[3, 3, 4, 3]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="outer_barbican", side="w", kind="gap", public_name="Пролом во внешней стене", width=2
            ),
        ],
    )
    return meta, intent


# ==============================================================================
# 1. ТАВЕРНА (Tavern C & D)
# ==============================================================================


def make_tavern_fortified_brewery() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "tavern_fortified_brewery",
        "version": "1.0.0",
        "archetype": "tavern",
        "variant": "C",
        "variant_name": "Укреплённая пивоварня",
        "purpose": "Каменная приграничная пивоварня с дегустационным залом, варочным цехом и хранилищем хмеля",
        "visual_concept": "Массивное каменное здание с толстыми стенами, медными варочными котлами, рядами бочек и конторкой мастера.",
        "environment": "indoor",
        "materials": ["stone", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Торговля с гильдией пивоваров, наём караванной стражи в дегустационном зале.",
            "exploration": "Поиск редких рецептов в конторке или тайника в солодовне.",
            "combat": "Медные чаны и стойки бочек создают прочные укрытия; узкие переходы удобны для обороны.",
        },
        "allowable_adaptations": ["Превращение в подпольную алхимическую лабораторию", "Осада пограничного форпоста"],
        "discovered_constraints": ["Чаны и печи должны стоять у стен для безопасных проходов к выходам."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="tasting_room",
        parts=[
            PartIntent(
                part_ref="tasting_room",
                role="tavern_hall",
                name="Дегустационный зал",
                public_name="Дегустационный зал",
                description="Сводчатый зал с массивными дубовыми столами, жаровней и тяжёлой стойкой разлива.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="bar_counter",
                        name="Стойка разлива",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 1, 3], [2, 3, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="bar_stools", name="Табуреты у стойки", kind="furniture", cells=[[2, 4, 3, 4]]
                    ),
                    DetailIntent(
                        detail_ref="table_north",
                        name="Широкий дубовый стол",
                        kind="furniture",
                        solid=True,
                        cells=[[6, 2, 7, 2]],
                    ),
                    DetailIntent(
                        detail_ref="chair",
                        name="Кресла для гостей",
                        kind="furniture",
                        cells=[[6, 1, 7, 1], [6, 3, 7, 3]],
                    ),
                    DetailIntent(
                        detail_ref="brazier", name="Угольная жаровня", kind="light", solid=True, cells=[[8, 5, 8, 5]]
                    ),
                    DetailIntent(detail_ref="carpet", name="Суконный ковёр", kind="furniture", cells=[[5, 5, 6, 6]]),
                ],
            ),
            PartIntent(
                part_ref="brewhouse",
                role="kitchen",
                name="Варочный цех",
                public_name="Варочный цех",
                description="Жаркий цех с медным варочным котлом, печью и верстаком бондаря.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=8,
                level=0,
                material="stone",
                connects_to="tasting_room",
                side="e",
                passage_kind="arch",
                passage_name="Арочный проход в цех",
                details=[
                    DetailIntent(
                        detail_ref="cauldron",
                        name="Медный варочный котёл",
                        kind="object",
                        solid=True,
                        cells=[[2, 1, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="forge", name="Печной горн", kind="light", solid=True, cells=[[6, 1, 6, 2]]
                    ),
                    DetailIntent(
                        detail_ref="workbench",
                        name="Верстак бондаря",
                        kind="furniture",
                        solid=True,
                        cells=[[6, 5, 6, 6]],
                    ),
                    DetailIntent(detail_ref="ale_casks", name="Бочки с суслом", kind="object", cells=[[1, 5, 2, 5]]),
                ],
            ),
            PartIntent(
                part_ref="malt_store",
                role="cellar",
                name="Склад хмеля и зерна",
                public_name="Склад сырья",
                description="Сухое прохладное помещение с мешками зерна и ящиками сушёного хмеля.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="brewhouse",
                side="n",
                passage_kind="door",
                passage_name="Дверь в зернохранилище",
                details=[
                    DetailIntent(
                        detail_ref="sack", name="Мешки с отборным солодом", kind="object", cells=[[1, 1, 2, 1]]
                    ),
                    DetailIntent(
                        detail_ref="pantry_shelves",
                        name="Стеллажи для трав и хмеля",
                        kind="furniture",
                        cells=[[4, 1, 4, 3]],
                    ),
                    DetailIntent(
                        detail_ref="traveler_chests", name="Сундук со специями", kind="object", cells=[[1, 4, 1, 4]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="brewers_office",
                role="quarters",
                name="Конторка главного пивовара",
                public_name="Конторка пивовара",
                description="Уединённый кабинет с письменным столом, шкафом с записями и сейфом.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="tasting_room",
                side="n",
                passage_kind="door",
                passage_name="Дубовая дверь кабинета",
                details=[
                    DetailIntent(
                        detail_ref="desk",
                        name="Письменный стол пивовара",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(detail_ref="chair", name="Резное кресло", kind="furniture", cells=[[2, 1, 3, 1]]),
                    DetailIntent(
                        detail_ref="wardrobe",
                        name="Шкаф для образцов и документов",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 4, 4, 5]],
                    ),
                    DetailIntent(
                        detail_ref="iron_strongbox",
                        name="Кованый сейф гильдии",
                        kind="object",
                        solid=True,
                        cells=[[1, 4, 1, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="tasting_room", side="s", kind="gate", public_name="Входные ворота пивоварни", width=2
            ),
        ],
    )
    return meta, intent


def make_tavern_coastal_inn() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "tavern_coastal_inn",
        "version": "1.0.0",
        "archetype": "tavern",
        "variant": "D",
        "variant_name": "Прибрежная гостиница на сваях",
        "purpose": "Двухуровневая приморская таверна с террасой над водой, общим залом и коптильней",
        "visual_concept": "Деревянное строение на сваях у кромки прилива: открытая дощатая терраса с видом на море и уютный зал с камином.",
        "environment": "mixed",
        "materials": ["wood", "water", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Слухи моряков, сделки с контрабандистами прямо на террасе у шлюпок.",
            "exploration": "Тайный люк в полу над водой для выгрузки запрещённых товаров.",
            "combat": "Сбрасывание врагов за перила в воду; столы и бочки служат прикрытием от арбалетных болтов.",
        },
        "allowable_adaptations": ["Рыбацкий приют во время шторма", "Штаб береговой охраны"],
        "discovered_constraints": ["Терраса открытая (outdoor), внутренние комнаты деревянные (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="seaside_terrace",
        parts=[
            PartIntent(
                part_ref="seaside_terrace",
                role="pier",
                name="Терраса над водой",
                public_name="Приморская терраса",
                description="Открытый дощатый настил на сваях со столиками и верёвочными ограждениями.",
                environment="outdoor",
                shape="rect",
                cols=10,
                rows=6,
                level=0,
                material="wood",
                details=[
                    DetailIntent(
                        detail_ref="table_north",
                        name="Столики на открытом воздухе",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 2], [7, 2, 8, 2]],
                    ),
                    DetailIntent(
                        detail_ref="chair", name="Плетёные кресла", kind="furniture", cells=[[2, 3, 3, 3], [7, 3, 8, 3]]
                    ),
                    DetailIntent(
                        detail_ref="coiled_hawsers",
                        name="Швартовые канаты и снасти",
                        kind="object",
                        cells=[[1, 4, 1, 4]],
                    ),
                    DetailIntent(
                        detail_ref="quay_lantern",
                        name="Сигнальный фонарь на столбе",
                        kind="light",
                        cells=[[9, 1, 9, 1]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="sailors_hall",
                role="tavern_hall",
                name="Зал моряков",
                public_name="Зал таверны",
                description="Тёплый деревянный зал с люстрой из штурвала, очагом и стойкой.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="wood",
                connects_to="seaside_terrace",
                side="n",
                passage_kind="door",
                passage_name="Дверь с террасы",
                details=[
                    DetailIntent(
                        detail_ref="hearth",
                        name="Большой камин из ракушечника",
                        kind="light",
                        solid=True,
                        cells=[[5, 0, 6, 0]],
                    ),
                    DetailIntent(
                        detail_ref="bar_counter",
                        name="Трактирная стойка",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 2, 1, 4], [2, 4, 2, 4]],
                    ),
                    DetailIntent(
                        detail_ref="bar_stools", name="Табуреты у стойки", kind="furniture", cells=[[2, 2, 2, 3]]
                    ),
                    DetailIntent(
                        detail_ref="chandelier", name="Кованая люстра со свечами", kind="light", cells=[[5, 4, 5, 4]]
                    ),
                    DetailIntent(
                        detail_ref="round_tables",
                        name="Круглый стол для игры в кости",
                        kind="furniture",
                        solid=True,
                        cells=[[6, 3, 7, 3]],
                    ),
                    DetailIntent(detail_ref="ale_casks", name="Бочонки рома", kind="object", cells=[[1, 6, 2, 6]]),
                ],
            ),
            PartIntent(
                part_ref="fish_smokehouse",
                role="kitchen",
                name="Рыбная кухня и коптильня",
                public_name="Коптильня и кухня",
                description="Служебное помещение с коптильной печью и разделочным столом.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="sailors_hall",
                side="e",
                passage_kind="door",
                passage_name="Дверь на кухню",
                details=[
                    DetailIntent(
                        detail_ref="smokehouse_stove",
                        name="Коптильная печь",
                        kind="light",
                        solid=True,
                        cells=[[4, 1, 4, 2]],
                    ),
                    DetailIntent(
                        detail_ref="workbench",
                        name="Разделочный верстак",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="salted_fish_barrels",
                        name="Бочки с соленой рыбой",
                        kind="object",
                        cells=[[1, 4, 2, 4]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="attic_quarters",
                role="quarters",
                name="Жилые комнаты мансарды",
                public_name="Комнаты постояльцев",
                description="Уютные спальные места под скатной крышей со шкафом и сундуками.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="wood",
                connects_to="sailors_hall",
                side="w",
                passage_kind="door",
                passage_name="Дверь в коридор комнат",
                details=[
                    DetailIntent(
                        detail_ref="bunks_north",
                        name="Двухъярусные кровати",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 2, 1], [4, 1, 5, 1]],
                    ),
                    DetailIntent(
                        detail_ref="wardrobe", name="Платяной шкаф", kind="furniture", solid=True, cells=[[6, 4, 6, 4]]
                    ),
                    DetailIntent(
                        detail_ref="traveler_chests", name="Сундуки постояльцев", kind="object", cells=[[1, 4, 2, 4]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="seaside_terrace", side="s", kind="passage", public_name="Сходни с пирса", width=1),
        ],
    )
    return meta, intent


print("Tavern C & D defined successfully")

# ==============================================================================
# 2. ХРАМ (Temple C & D)
# ==============================================================================


def make_temple_sunken_catacombs() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "temple_sunken_catacombs",
        "version": "1.0.0",
        "archetype": "temple",
        "variant": "C",
        "variant_name": "Затопленные катакомбы",
        "purpose": "Древний подземный некрополь с погребальной часовней, залом саркофагов и осквернённым оссуарием",
        "visual_concept": "Мрачные сводчатые склепы с каменными саркофагами, надгробиями, горящими жаровнями и тайной нишей первосвященника.",
        "environment": "indoor",
        "materials": ["stone", "water"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча с хранителем могил или фанатиками культа смерти.",
            "exploration": "Поиск древних реликвий в саркофагах и раскрытие потайного склепа.",
            "combat": "Укрытия за массивными каменными саркофагами и статуями святых.",
        },
        "allowable_adaptations": ["Логово нежити", "Тайный культовый алтарь"],
        "discovered_constraints": ["Саркофаги и надгробия не должны блокировать центральный проход."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="burial_chapel",
        parts=[
            PartIntent(
                part_ref="burial_chapel",
                role="hall",
                name="Погребальная часовня",
                public_name="Погребальная часовня",
                description="Входной покой некрополя с алтарём заупокойной службы и каменными надгробиями.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="grand_altar",
                        name="Заупокойный алтарь",
                        kind="object",
                        solid=True,
                        cells=[[4, 1, 5, 1]],
                    ),
                    DetailIntent(
                        detail_ref="brazier",
                        name="Храмовая жаровня",
                        kind="light",
                        solid=True,
                        cells=[[2, 2, 2, 2], [7, 2, 7, 2]],
                    ),
                    DetailIntent(
                        detail_ref="tombstone",
                        name="Надгробные плиты",
                        kind="cover",
                        cells=[[1, 4, 2, 4], [7, 4, 8, 4]],
                    ),
                    DetailIntent(
                        detail_ref="carpet", name="Погребальный ковёр", kind="furniture", cells=[[4, 3, 5, 5]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="hall_of_sarcophagi",
                role="sanctuary",
                name="Галерея саркофагов",
                public_name="Зал саркофагов",
                description="Высокий каменный зал с массивными саркофагами знатных патрициев и статуями стражей.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                connects_to="burial_chapel",
                side="n",
                passage_kind="arch",
                passage_name="Высокая погребальная арка",
                details=[
                    DetailIntent(
                        detail_ref="sarcophagus",
                        name="Каменные саркофаги",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 2], [6, 2, 7, 2]],
                    ),
                    DetailIntent(
                        detail_ref="statue",
                        name="Статуи скорбящих стражей",
                        kind="object",
                        solid=True,
                        cells=[[1, 5, 1, 5], [8, 5, 8, 5]],
                    ),
                    DetailIntent(
                        detail_ref="brazier", name="Неугасимая жаровня", kind="light", solid=True, cells=[[4, 4, 5, 4]]
                    ),
                    DetailIntent(
                        detail_ref="wall_sconce",
                        name="Настенные факелы",
                        kind="light",
                        cells=[[1, 1, 1, 1], [8, 1, 8, 1]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="flooded_ossuary",
                role="crypt",
                name="Оссуарий",
                public_name="Костехранилище",
                description="Низкий сырой свод с грудами костей и осыпавшимися нишами.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="hall_of_sarcophagi",
                side="w",
                passage_kind="door",
                passage_name="Железная решётка оссуария",
                details=[
                    DetailIntent(
                        detail_ref="bone_pile", name="Груды освящённых костей", kind="cover", cells=[[1, 1, 2, 1]]
                    ),
                    DetailIntent(
                        detail_ref="rubble_piles", name="Осыпавшаяся кладка", kind="nature", cells=[[1, 4, 2, 4]]
                    ),
                    DetailIntent(
                        detail_ref="relic_chest",
                        name="Кованый реликварий",
                        kind="object",
                        solid=True,
                        cells=[[4, 4, 4, 4]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="hierophant_crypt",
                role="vault",
                name="Склеп первосвященника",
                public_name="Потайной склеп",
                description="Скрытая усыпальница с мраморным саркофагом и священными дарами.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="hall_of_sarcophagi",
                side="e",
                passage_kind="door",
                passage_name="Потайная каменная плита",
                passage_state="closed",
                secret=True,
                details=[
                    DetailIntent(
                        detail_ref="sarcophagus",
                        name="Мраморный саркофаг первосвященника",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="statue", name="Статуя божества", kind="object", solid=True, cells=[[4, 1, 4, 1]]
                    ),
                    DetailIntent(
                        detail_ref="relic_chest",
                        name="Сундук со священными сосудами",
                        kind="object",
                        solid=True,
                        cells=[[1, 4, 1, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(part_ref="burial_chapel", side="s", kind="door", public_name="Вход в усыпальницу", width=1),
        ],
    )
    return meta, intent


def make_temple_mountain_monastery() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "temple_mountain_monastery",
        "version": "1.0.0",
        "archetype": "temple",
        "variant": "D",
        "variant_name": "Высокогорный монастырь",
        "purpose": "Изолированный скальный монастырь с двором созерцания, святилищем колокола и скрипторием",
        "visual_concept": "Двор на вершине утеса с колодцем и статуей, каменное святилище с колоколом и тихий скрипторий.",
        "environment": "mixed",
        "materials": ["stone", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Беседа с монахами-молчальниками, доступ к монастырской библиотеке.",
            "exploration": "Изучение древних манускриптов и механизмов башенного колокола.",
            "combat": "Узкие ступени и двор с колодцем создают перепады высот и укрытия.",
        },
        "allowable_adaptations": ["Оплот ордена паладинов", "Горная обсерватория"],
        "discovered_constraints": ["Двор открытый (outdoor), святилище и скрипторий закрытые (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="monastery_courtyard",
        parts=[
            PartIntent(
                part_ref="monastery_courtyard",
                role="courtyard",
                name="Двор созерцания",
                public_name="Монастырский двор",
                description="Открытый мощёный двор на скальном уступе с каменным колодцем и статуей основателя.",
                environment="outdoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="well",
                        name="Глубокий каменный колодец",
                        kind="object",
                        solid=True,
                        cells=[[2, 3, 3, 4]],
                    ),
                    DetailIntent(
                        detail_ref="statue",
                        name="Статуя святого основателя",
                        kind="object",
                        solid=True,
                        cells=[[7, 3, 7, 4]],
                    ),
                    DetailIntent(
                        detail_ref="log_seat",
                        name="Каменные скамьи для молитвы",
                        kind="furniture",
                        cells=[[2, 1, 3, 1], [7, 1, 8, 1]],
                    ),
                    DetailIntent(
                        detail_ref="fountain", name="Чаша для омовений", kind="object", solid=True, cells=[[5, 6, 5, 6]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="bell_sanctuary",
                role="sanctuary",
                name="Святилище колокола",
                public_name="Храм святого колокола",
                description="Каменная ротонда с великим колоколом под сводом, алтарём и резными скамьями.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                connects_to="monastery_courtyard",
                side="n",
                passage_kind="door",
                passage_name="Кованые врата святилища",
                details=[
                    DetailIntent(
                        detail_ref="grand_altar",
                        name="Главный алтарь Света",
                        kind="object",
                        solid=True,
                        cells=[[4, 1, 5, 1]],
                    ),
                    DetailIntent(
                        detail_ref="chandelier",
                        name="Подвесной храмовый светильник",
                        kind="light",
                        cells=[[4, 4, 5, 4]],
                    ),
                    DetailIntent(
                        detail_ref="brazier",
                        name="Бронзовые курильницы",
                        kind="light",
                        solid=True,
                        cells=[[2, 2, 2, 2], [7, 2, 7, 2]],
                    ),
                    DetailIntent(detail_ref="carpet", name="Молитвенный ковёр", kind="furniture", cells=[[4, 3, 5, 5]]),
                    DetailIntent(
                        detail_ref="prayer_benches",
                        name="Скамьи братии",
                        kind="furniture",
                        cells=[[2, 5, 3, 5], [6, 5, 7, 5]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="scriptorium",
                role="quarters",
                name="Скрипторий и библиотека",
                public_name="Скрипторий",
                description="Тихая монастырская библиотека с пюпитрами, книжными шкафами и рабочими столами.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="wood",
                connects_to="bell_sanctuary",
                side="e",
                passage_kind="door",
                passage_name="Дверь в библиотеку",
                details=[
                    DetailIntent(
                        detail_ref="desk",
                        name="Письменные столы переписчиков",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 2], [2, 4, 3, 4]],
                    ),
                    DetailIntent(
                        detail_ref="chair",
                        name="Стулья переписчиков",
                        kind="furniture",
                        cells=[[4, 2, 4, 2], [4, 4, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="bookcase",
                        name="Шкафы с древними манускриптами",
                        kind="object",
                        solid=True,
                        cells=[[6, 1, 6, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="monastery_courtyard",
                side="s",
                kind="gate",
                public_name="Тропа к монастырским воротам",
                width=2,
            ),
        ],
    )
    return meta, intent


# ==============================================================================
# 3. ПЕЩЕРА (Cave C & D)
# ==============================================================================


def make_cave_fungal_chasm() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "cave_fungal_chasm",
        "version": "1.0.0",
        "archetype": "cave",
        "variant": "C",
        "variant_name": "Грибная расселина",
        "purpose": "Глубокая пещерная расселина со светящимся лесом грибов, каменным карнизом и логовом пещерных пауков",
        "visual_concept": "Мерцающие сине-зеленым светом заросли исполинских грибов, скользкие скалы и трещины с кристаллами.",
        "environment": "indoor",
        "materials": ["earth", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Встреча с сумеречным следопытом или сборщиком целебных спор.",
            "exploration": "Сбор ядовитых и светящихся грибов, поиск кристаллов в трещинах.",
            "combat": "Грибные наросты дают мягкое укрытие; валуны прикрывают от атак сверху.",
        },
        "allowable_adaptations": ["Подземные фермы дроу", "Заражённые спорами туннели"],
        "discovered_constraints": ["При форме cave отступать от краев."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="spore_entry",
        parts=[
            PartIntent(
                part_ref="spore_entry",
                role="cave_entrance",
                name="Входная расселина спор",
                public_name="Грибной грот",
                description="Сырой каменный свод с плотными зарослями светящихся грибов и каменными осыпями.",
                environment="indoor",
                shape="cave",
                cols=8,
                rows=8,
                level=0,
                material="earth",
                details=[
                    DetailIntent(
                        detail_ref="mushrooms",
                        name="Скопления светящихся грибов",
                        kind="nature",
                        cells=[[2, 2, 3, 2], [2, 5, 2, 5]],
                    ),
                    DetailIntent(
                        detail_ref="boulder", name="Обкатанный валун", kind="cover", solid=True, cells=[[5, 4, 5, 4]]
                    ),
                    DetailIntent(detail_ref="scree", name="Осыпь мелких камней", kind="nature", cells=[[4, 2, 5, 2]]),
                ],
            ),
            PartIntent(
                part_ref="chasm_bridge",
                role="corridor",
                name="Каменный карниз над бездной",
                public_name="Узкий карниз",
                description="Опасная тропа вдоль трещины со свисающими сталактитами.",
                environment="indoor",
                shape="corridor",
                cols=6,
                rows=2,
                level=0,
                material="stone",
                connects_to="spore_entry",
                side="e",
                passage_kind="passage",
                passage_name="Узкий проход по карнизу",
                details=[
                    DetailIntent(
                        detail_ref="stalactites", name="Острые сталактиты", kind="nature", cells=[[2, 0, 3, 0]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="fungal_heart",
                role="grotto",
                name="Великая грибная каверна",
                public_name="Светящийся грот",
                description="Огромный грот с исполинскими грибами, кристаллами и мерцающим подземным озером.",
                environment="indoor",
                shape="cave",
                cols=12,
                rows=10,
                level=0,
                material="stone",
                connects_to="chasm_bridge",
                side="e",
                passage_kind="arch",
                passage_name="Сводчатый вход в каверну",
                details=[
                    DetailIntent(
                        detail_ref="mushrooms",
                        name="Лес гигантских грибов",
                        kind="nature",
                        cells=[[3, 3, 4, 3], [8, 3, 8, 4]],
                    ),
                    DetailIntent(
                        detail_ref="crystal_cluster",
                        name="Друза светящихся кристаллов",
                        kind="object",
                        solid=True,
                        cells=[[6, 7, 7, 7]],
                    ),
                    DetailIntent(
                        detail_ref="shimmering_pool", name="Мерцающий ручей", kind="light", cells=[[3, 6, 4, 6]]
                    ),
                    DetailIntent(
                        detail_ref="stalagmite_pillars",
                        name="Колонны сталагмитов",
                        kind="cover",
                        solid=True,
                        cells=[[8, 6, 8, 7]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="spider_lair",
                role="lair",
                name="Логово пещерных тварей",
                public_name="Паучье логово",
                description="Тёмная боковая расщелина, затянутая паутиной, с костями жертв.",
                environment="indoor",
                shape="cave",
                cols=6,
                rows=6,
                level=0,
                material="earth",
                connects_to="fungal_heart",
                side="s",
                passage_kind="gap",
                passage_name="Узкая трещина в логово",
                details=[
                    DetailIntent(
                        detail_ref="beast_bedding", name="Кокон из паутины", kind="furniture", cells=[[2, 2, 3, 2]]
                    ),
                    DetailIntent(detail_ref="bone_pile", name="Оглоданные кости", kind="cover", cells=[[2, 4, 3, 4]]),
                    DetailIntent(detail_ref="scree", name="Каменные осколки", kind="nature", cells=[[4, 2, 4, 3]]),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="spore_entry", side="w", kind="gap", public_name="Входная расселина в пещеру", width=1
            ),
        ],
    )
    return meta, intent


def make_cave_smugglers_cove() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "cave_smugglers_cove",
        "version": "1.0.0",
        "archetype": "cave",
        "variant": "D",
        "variant_name": "Бухта контрабандистов",
        "purpose": "Приливная морская пещера с тайной стоянкой лодок, причалом, складом товаров и карцером",
        "visual_concept": "Скальная каверна с естественной гаванью: деревянные мостки, ящики с грузом, фонари и железная клетка.",
        "environment": "indoor",
        "materials": ["stone", "water", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Переговоры с контрабандистами, подкуп часовых у причала.",
            "exploration": "Вскрытие ящиков с заморским товаром, освобождение пленника из клетки.",
            "combat": "Бой на шатких мостках; перевёрнутые лодки и тюки служат бруствером.",
        },
        "allowable_adaptations": ["Пиратское убежище", "База сектантов морского бога"],
        "discovered_constraints": ["Пристань примыкает к пещере; клетка в боковой нише."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="tidal_harbor",
        parts=[
            PartIntent(
                part_ref="tidal_harbor",
                role="pier",
                name="Приливная гавань",
                public_name="Подземная стоянка лодок",
                description="Высокая пещера с водой, деревянным причалом, швартовыми кольцами и лодкой.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="upturned_skiff",
                        name="Шлюпка у причала",
                        kind="cover",
                        solid=True,
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="mooring_bollards",
                        name="Швартовые тумбы",
                        kind="furniture",
                        cells=[[1, 5, 1, 5], [4, 5, 4, 5]],
                    ),
                    DetailIntent(
                        detail_ref="coiled_hawsers", name="Бухты канатов и сетей", kind="object", cells=[[7, 2, 8, 2]]
                    ),
                    DetailIntent(
                        detail_ref="oil_lantern", name="Штормовой фонарь на балке", kind="light", cells=[[7, 5, 7, 5]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="smugglers_cache",
                role="warehouse",
                name="Склад контрабанды",
                public_name="Пещерный склад",
                description="Сухой скальный зал с горами ящиков, бочками и тележкой.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                connects_to="tidal_harbor",
                side="n",
                passage_kind="arch",
                passage_name="Прорубленный в скале проход",
                details=[
                    DetailIntent(
                        detail_ref="crate_stacks",
                        name="Штабели грузов",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 2], [7, 2, 8, 2]],
                    ),
                    DetailIntent(
                        detail_ref="cart",
                        name="Двухколёсная грузовая тележка",
                        kind="object",
                        solid=True,
                        cells=[[2, 5, 3, 5]],
                    ),
                    DetailIntent(detail_ref="sack", name="Мешки с ценностями", kind="object", cells=[[7, 5, 8, 5]]),
                    DetailIntent(
                        detail_ref="watch_brazier",
                        name="Жаровня караульных",
                        kind="light",
                        solid=True,
                        cells=[[5, 4, 5, 4]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="prisoner_niche",
                role="vault",
                name="Карцер для пленников",
                public_name="Боковая ниша с клеткой",
                description="Сырой тупик с железной подвесной клеткой и цепями в стенах.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="smugglers_cache",
                side="w",
                passage_kind="door",
                passage_name="Кованая решётка",
                passage_state="locked",
                details=[
                    DetailIntent(
                        detail_ref="cage",
                        name="Железная клетка для пленников",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(detail_ref="bone_pile", name="Останки беглеца", kind="cover", cells=[[1, 4, 1, 4]]),
                    DetailIntent(detail_ref="wall_sconce", name="Факел на стене", kind="light", cells=[[4, 1, 4, 1]]),
                ],
            ),
            PartIntent(
                part_ref="captains_den",
                role="quarters",
                name="Каюта главаря",
                public_name="Потайная каморка главаря",
                description="Отделанный деревом потайной грот с резным столом, ковром и сундуком.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="smugglers_cache",
                side="e",
                passage_kind="door",
                passage_name="Маскировочная дверь",
                passage_state="closed",
                secret=True,
                details=[
                    DetailIntent(
                        detail_ref="desk",
                        name="Стол главаря с картами",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="chair", name="Резное капитанское кресло", kind="furniture", cells=[[2, 1, 3, 1]]
                    ),
                    DetailIntent(
                        detail_ref="iron_strongbox",
                        name="Сундук с золотом",
                        kind="object",
                        solid=True,
                        cells=[[1, 4, 1, 4]],
                    ),
                    DetailIntent(
                        detail_ref="carpet", name="Роскошный восточный ковёр", kind="furniture", cells=[[3, 3, 4, 4]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="tidal_harbor",
                side="s",
                kind="gap",
                public_name="Вход со стороны моря во время отлива",
                width=2,
            ),
        ],
    )
    return meta, intent


print("Temple C & D, Cave C & D defined successfully")

# ==============================================================================
# 4. ЛЕС (Forest C & D)
# ==============================================================================


def make_forest_druid_grove() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "forest_druid_grove",
        "version": "1.0.0",
        "archetype": "forest",
        "variant": "C",
        "variant_name": "Друидическая роща",
        "purpose": "Древнее святилище в сердце чащи со священным дубом, менгирами, чашей источников и поляной трав",
        "visual_concept": "Величественная поляна среди вековых деревьев: алтарный камень, круги менгиров, поваленные замшелые бревна и родник.",
        "environment": "outdoor",
        "materials": ["grass", "wood", "stone"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Ритуал с друидами Круга, исцеление ран священными водами источника.",
            "exploration": "Поиск редких целебных грибов, расшифровка огамических надписей на менгирах.",
            "combat": "Стволы деревьев и менгиры обеспечивают полное укрытие от стрелков; чаща замедляет движение.",
        },
        "allowable_adaptations": ["Осквернённая роща ведьм", "Эльфийский пограничный форпост"],
        "discovered_constraints": ["Полностью открытое окружение (outdoor=True)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="sacred_clearing",
        parts=[
            PartIntent(
                part_ref="sacred_clearing",
                role="clearing",
                name="Поляна менгиров",
                public_name="Священная поляна",
                description="Просторная поляна в кольце вековых дубов с алтарным камнем и замшелыми менгирами.",
                environment="outdoor",
                shape="open",
                cols=12,
                rows=10,
                level=0,
                material="grass",
                details=[
                    DetailIntent(
                        detail_ref="wayside_shrine",
                        name="Алтарь Первозданной Природы",
                        kind="object",
                        solid=True,
                        cells=[[5, 4, 6, 4]],
                    ),
                    DetailIntent(
                        detail_ref="standing_pillars",
                        name="Кольцо замшелых менгиров",
                        kind="object",
                        solid=True,
                        cells=[[3, 2, 3, 3], [8, 2, 8, 3]],
                    ),
                    DetailIntent(
                        detail_ref="stump",
                        name="Широкий древний пень",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 7, 2, 7]],
                    ),
                    DetailIntent(
                        detail_ref="log",
                        name="Поваленный поросший мхом ствол",
                        kind="cover",
                        solid=True,
                        cells=[[8, 7, 10, 7]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="spring_basin",
                role="water_edge",
                name="Чаша священного источника",
                public_name="Родник духов",
                description="Каменный бассейн с бьющей из-под корней чистой родниковой водой.",
                environment="outdoor",
                shape="open",
                cols=8,
                rows=8,
                level=0,
                material="grass",
                connects_to="sacred_clearing",
                side="n",
                passage_kind="passage",
                passage_name="Тропа к роднику",
                details=[
                    DetailIntent(
                        detail_ref="well",
                        name="Освящённый каменный родник",
                        kind="object",
                        solid=True,
                        cells=[[3, 3, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="mushrooms",
                        name="Россыпь синих лесных грибов",
                        kind="nature",
                        cells=[[1, 2, 2, 2], [5, 5, 6, 5]],
                    ),
                    DetailIntent(
                        detail_ref="brambles", name="Заросли дикого терновника", kind="cover", cells=[[1, 5, 2, 6]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="heartwood_sanctum",
                role="grove",
                name="Куща Древа Жизни",
                public_name="Роща Великого Дуба",
                description="Густая роща вокруг тысячелетнего дуба с алтарными подношениями.",
                environment="outdoor",
                shape="open",
                cols=8,
                rows=8,
                level=0,
                material="grass",
                connects_to="sacred_clearing",
                side="e",
                passage_kind="passage",
                passage_name="Звериная тропа в чащу",
                details=[
                    DetailIntent(
                        detail_ref="ancient_oak",
                        name="Исполинский дуб-хранитель",
                        kind="nature",
                        solid=True,
                        cells=[[3, 3, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="statue",
                        name="Деревянный идол Лесного Отца",
                        kind="object",
                        solid=True,
                        cells=[[2, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="dry_nest", name="Гнездо гигантского орла", kind="furniture", cells=[[5, 2, 6, 2]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="sacred_clearing", side="s", kind="gap", public_name="Вход на священную поляну", width=2
            ),
        ],
    )
    return meta, intent


def make_forest_bandit_hideout() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "forest_bandit_hideout",
        "version": "1.0.0",
        "archetype": "forest",
        "variant": "D",
        "variant_name": "Укреплённый лагерь разбойников",
        "purpose": "Лесной лагерь на поляне с частоколом, кострищем, телегой с добычей и потайной землянкой",
        "visual_concept": "Поляна с кострищем, ящиками, оружием на стойках и замаскированной землянкой главаря.",
        "environment": "mixed",
        "materials": ["earth", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Допрос захваченного разбойника, переговоры об освобождении заложников.",
            "exploration": "Обыск телеги с награбленным добром, поиск замаскированного входа в землянку.",
            "combat": "Кострище как источник огня; телега и брёвна служат стрелковыми баррикадами.",
        },
        "allowable_adaptations": ["Лагерь повстанцев", "Охотничья стоянка на пушного зверя"],
        "discovered_constraints": ["Поляна открытая (outdoor), навес и землянка деревянные (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="camp_clearing",
        parts=[
            PartIntent(
                part_ref="camp_clearing",
                role="clearing",
                name="Поляна лагеря",
                public_name="Лагерная поляна",
                description="Вытоптанная поляна с кострищем, грубо отёсанными брёвнами-скамьями и повозкой.",
                environment="outdoor",
                shape="open",
                cols=10,
                rows=8,
                level=0,
                material="earth",
                details=[
                    DetailIntent(
                        detail_ref="campfire",
                        name="Большое кострище с вертелом",
                        kind="light",
                        solid=True,
                        cells=[[4, 3, 5, 4]],
                    ),
                    DetailIntent(
                        detail_ref="log",
                        name="Брёвна для сидения вокруг огня",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 1, 5, 1], [4, 6, 5, 6]],
                    ),
                    DetailIntent(
                        detail_ref="cart", name="Нагруженная повозка", kind="object", solid=True, cells=[[1, 3, 2, 4]]
                    ),
                    DetailIntent(
                        detail_ref="stump",
                        name="Колода для колки дров с топором",
                        kind="furniture",
                        solid=True,
                        cells=[[8, 2, 8, 2]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="loot_shelter",
                role="warehouse",
                name="Навес для добычи",
                public_name="Склад под навесом",
                description="Дощатый навес со штабелями ящиков, бочками и стойками оружия.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="wood",
                connects_to="camp_clearing",
                side="n",
                passage_kind="arch",
                passage_name="Проход под навес",
                details=[
                    DetailIntent(
                        detail_ref="weapon_rack",
                        name="Стойки с мечами и луками",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="crate_stacks",
                        name="Ящики с купеческим товаром",
                        kind="object",
                        solid=True,
                        cells=[[5, 1, 6, 2]],
                    ),
                    DetailIntent(
                        detail_ref="sack", name="Мешки с мукой и вяленым мясом", kind="object", cells=[[1, 4, 2, 4]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="chieftain_dugout",
                role="quarters",
                name="Землянка главаря",
                public_name="Потайная землянка",
                description="Низкое укреплённое бревенчатое убежище под холмом со столом и сундуком атамана.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="wood",
                connects_to="camp_clearing",
                side="e",
                passage_kind="door",
                passage_name="Замаскированный лаз в землянку",
                passage_state="closed",
                secret=True,
                details=[
                    DetailIntent(
                        detail_ref="desk",
                        name="Стол главаря с добычей",
                        kind="furniture",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(detail_ref="chair", name="Стул атамана", kind="furniture", cells=[[2, 1, 3, 1]]),
                    DetailIntent(
                        detail_ref="iron_strongbox",
                        name="Сундук с атаманской долей",
                        kind="object",
                        solid=True,
                        cells=[[1, 4, 1, 4]],
                    ),
                    DetailIntent(
                        detail_ref="bunks_north",
                        name="Лежанка главаря",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 4, 5, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="camp_clearing", side="s", kind="passage", public_name="Потайная тропа в чаще", width=1
            ),
        ],
    )
    return meta, intent


# ==============================================================================
# 5. ПОРТ (Port C & D)
# ==============================================================================


def make_port_shipyard_drydock() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "port_shipyard_drydock",
        "version": "1.0.0",
        "archetype": "port",
        "variant": "C",
        "variant_name": "Корабельная верфь и сухой док",
        "purpose": "Портовый судоремонтный док со стапелями, кузницей корабельной оснастки и плотницким двором",
        "visual_concept": "Каменный док с деревянными подпорками, подъёмным краном, наковальней, горном и лесом брёвен.",
        "environment": "mixed",
        "materials": ["stone", "wood", "water"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Заказ ремонта корабля, наём плотников и матросов.",
            "exploration": "Поиск контрабанды в двойном дне ремонтируемого баркаса.",
            "combat": "Подъёмный кран и стапели позволяют атаковать с верхнего яруса; верстаки дают укрытие.",
        },
        "allowable_adaptations": ["Военный арсенал флота", "Логово саботажников"],
        "discovered_constraints": ["Бассейн открытый (outdoor), кузница закрытая (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="drydock_basin",
        parts=[
            PartIntent(
                part_ref="drydock_basin",
                role="pier",
                name="Сухой док со стапелями",
                public_name="Бассейн сухого дока",
                description="Глубокий каменный бассейн с деревянными кильблоками, балками и подъёмным краном.",
                environment="outdoor",
                shape="rect",
                cols=12,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="cargo_crane",
                        name="Тяжёлый кран для корабельных балок",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="log",
                        name="Дубовые корабельные брёвна",
                        kind="cover",
                        solid=True,
                        cells=[[7, 2, 9, 2]],
                    ),
                    DetailIntent(
                        detail_ref="cart",
                        name="Тележка с инструментами",
                        kind="object",
                        solid=True,
                        cells=[[9, 5, 10, 5]],
                    ),
                    DetailIntent(
                        detail_ref="tar_firepit",
                        name="Жаровня для варки смолы",
                        kind="light",
                        solid=True,
                        cells=[[2, 5, 3, 5]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="shipwright_forge",
                role="workshop",
                name="Кузница оснастки и цепей",
                public_name="Кузница верфи",
                description="Жаркая мастерская с горном, наковальней и верстаком для ковки якорей.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="stone",
                connects_to="drydock_basin",
                side="n",
                passage_kind="arch",
                passage_name="Широкий въезд в кузницу",
                details=[
                    DetailIntent(
                        detail_ref="forge", name="Кузнечный горн верфи", kind="light", solid=True, cells=[[6, 1, 6, 2]]
                    ),
                    DetailIntent(
                        detail_ref="anvil", name="Тяжёлая наковальня", kind="object", solid=True, cells=[[4, 2, 4, 2]]
                    ),
                    DetailIntent(
                        detail_ref="workbench",
                        name="Верстак слесаря",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="barrel", name="Бочки с водой для закалки", kind="object", cells=[[1, 4, 2, 4]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="timber_quay",
                role="quay",
                name="Причальная набережная пиломатериалов",
                public_name="Причал для разгрузки леса",
                description="Широкий гранитный причал с кнехтами, штабелями досок и мостками.",
                environment="outdoor",
                shape="rect",
                cols=10,
                rows=4,
                level=0,
                material="stone",
                connects_to="drydock_basin",
                side="s",
                passage_kind="passage",
                passage_name="Спуск на причал",
                details=[
                    DetailIntent(
                        detail_ref="mooring_bollards",
                        name="Швартовые кнехты",
                        kind="furniture",
                        cells=[[1, 2, 1, 2], [8, 2, 8, 2]],
                    ),
                    DetailIntent(
                        detail_ref="coiled_hawsers", name="Тяжелые канаты", kind="object", cells=[[4, 1, 5, 1]]
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="drydock_basin", side="w", kind="gate", public_name="Въезд на территорию верфи", width=2
            ),
        ],
    )
    return meta, intent


def make_port_lighthouse_isle() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "port_lighthouse_isle",
        "version": "1.0.0",
        "archetype": "port",
        "variant": "D",
        "variant_name": "Маячный остров и сторожевая вышка",
        "purpose": "Одинокий скалистый остров с каменным причалом, основанием маяка и домом смотрителя",
        "visual_concept": "Каменный пирс на ветреном утесе, круглая башня маяка с винтовой лестницей, дом смотрителя с очагом.",
        "environment": "mixed",
        "materials": ["stone", "water", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Расспросы старого смотрителя маяка о кораблекрушениях и морских чудовищах.",
            "exploration": "Подъём на сигнальную платформу маяка, обнаружение сигнальных кодов контрабандистов.",
            "combat": "Оборона узкой лестницы на скалу; сильный ветер и крутые обрывы в воду.",
        },
        "allowable_adaptations": ["Наблюдательный пост береговой артиллерии", "Тайный алтарь глубин"],
        "discovered_constraints": ["Причал открытый (outdoor), комнаты закрытые (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="rocky_jetty",
        parts=[
            PartIntent(
                part_ref="rocky_jetty",
                role="pier",
                name="Скалистый причал шлюпок",
                public_name="Причал маяка",
                description="Гранитный пирс, обдуваемый морскими ветрами, с кольцами для причаливания лодок.",
                environment="outdoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="mooring_bollards",
                        name="Швартовые тумбы",
                        kind="furniture",
                        cells=[[1, 4, 1, 4], [6, 4, 6, 4]],
                    ),
                    DetailIntent(
                        detail_ref="coiled_hawsers",
                        name="Рыболовные снасти и сети",
                        kind="object",
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="quay_lantern",
                        name="Направляющий фонарь причала",
                        kind="light",
                        cells=[[6, 1, 6, 1]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="lighthouse_tower",
                role="sanctuary",
                name="Основание башни маяка",
                public_name="Башня маяка",
                description="Круглая каменная башня с массивными стенами, винтовой лестницей и жаровней.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=8,
                level=0,
                material="stone",
                connects_to="rocky_jetty",
                side="n",
                passage_kind="door",
                passage_name="Тяжёлая железная дверь башни",
                details=[
                    DetailIntent(
                        detail_ref="spiral_stairs_center",
                        name="Винтовая лестница на вершину маяка",
                        kind="object",
                        solid=True,
                        cells=[[3, 3, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="watch_brazier",
                        name="Сигнальная чаша жаровни",
                        kind="light",
                        solid=True,
                        cells=[[1, 1, 1, 1]],
                    ),
                    DetailIntent(
                        detail_ref="armory_crates",
                        name="Ящики с маслом и фитилями",
                        kind="object",
                        solid=True,
                        cells=[[6, 1, 6, 2]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="keepers_dwelling",
                role="quarters",
                name="Жилище смотрителя",
                public_name="Дом смотрителя",
                description="Скромный каменный коттедж с тёплым камином, кроватью, столом и шкафом.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="wood",
                connects_to="lighthouse_tower",
                side="e",
                passage_kind="door",
                passage_name="Дверь в жилой отсек",
                details=[
                    DetailIntent(
                        detail_ref="hearth", name="Очаг смотрителя", kind="light", solid=True, cells=[[4, 0, 5, 0]]
                    ),
                    DetailIntent(
                        detail_ref="bunks_north",
                        name="Кровать с лоскутным одеялом",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="desk",
                        name="Стол с подзорной трубой и вахтенным журналом",
                        kind="furniture",
                        solid=True,
                        cells=[[1, 4, 2, 4]],
                    ),
                    DetailIntent(detail_ref="chair", name="Табурет смотрителя", kind="furniture", cells=[[3, 4, 3, 4]]),
                    DetailIntent(
                        detail_ref="wardrobe",
                        name="Шкаф для одежды и провианта",
                        kind="furniture",
                        solid=True,
                        cells=[[6, 4, 6, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="rocky_jetty", side="s", kind="passage", public_name="Каменная лестница от воды", width=1
            ),
        ],
    )
    return meta, intent


# ==============================================================================
# 6. РУИНЫ (Ruins C & D)
# ==============================================================================


def make_ruins_forgotten_crypt() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "ruins_forgotten_crypt",
        "version": "1.0.0",
        "archetype": "ruins",
        "variant": "C",
        "variant_name": "Забытая усыпальница",
        "purpose": "Обрушившийся древний мавзолей с оскверненными саркофагами, надгробиями, статуями и тайным реликварием",
        "visual_concept": "Расколотые плиты, треснувшие саркофаги, повалившиеся статуи королей и завалы щебня под лунным светом.",
        "environment": "indoor",
        "materials": ["stone", "earth"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Спиритический контакт с призраком древнего лорда.",
            "exploration": "Поиск гербовых печатей на саркофагах, разгадка барельефа тайника.",
            "combat": "Саркофаги и поваленные колонны создают лабиринт тактических преград.",
        },
        "allowable_adaptations": ["Склеп проклятой династии", "Логово вампира"],
        "discovered_constraints": ["Щебень и надгробия не блокируют проход между арками."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="collapsed_atrium",
        parts=[
            PartIntent(
                part_ref="collapsed_atrium",
                role="courtyard",
                name="Обрушившийся атриум мавзолея",
                public_name="Разрушенный атриум",
                description="Входной зал со сквозным провалом в куполе, осыпями и разбитыми статуями.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="rubble_piles",
                        name="Груды обвалившегося свода",
                        kind="nature",
                        cells=[[2, 2, 3, 2], [6, 2, 7, 2]],
                    ),
                    DetailIntent(
                        detail_ref="fallen_statue",
                        name="Расколотая статуя воина",
                        kind="object",
                        solid=True,
                        cells=[[2, 5, 3, 5]],
                    ),
                    DetailIntent(
                        detail_ref="tombstone", name="Потрескавшиеся надгробия", kind="cover", cells=[[7, 5, 8, 5]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="sepulcher_chamber",
                role="crypt",
                name="Зал древних саркофагов",
                public_name="Палата саркофагов",
                description="Главный погребальный покой с тремя резными гранитными саркофагами и чашами огня.",
                environment="indoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                connects_to="collapsed_atrium",
                side="n",
                passage_kind="arch",
                passage_name="Полуразрушенная входная арка",
                details=[
                    DetailIntent(
                        detail_ref="sarcophagus",
                        name="Саркофаги лордов",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 2], [6, 2, 7, 2]],
                    ),
                    DetailIntent(
                        detail_ref="statue", name="Статуя плакальщицы", kind="object", solid=True, cells=[[4, 1, 5, 1]]
                    ),
                    DetailIntent(
                        detail_ref="brazier",
                        name="Погребальная жаровня",
                        kind="light",
                        solid=True,
                        cells=[[4, 5, 5, 5]],
                    ),
                    DetailIntent(
                        detail_ref="bone_pile", name="Прах защитников гробницы", kind="cover", cells=[[1, 5, 2, 5]]
                    ),
                ],
            ),
            PartIntent(
                part_ref="secret_reliquary",
                role="vault",
                name="Потайной реликварий династии",
                public_name="Потайной реликварий",
                description="Скрытая комната с нетронутым золочёным ларцом и дарами богам.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="sepulcher_chamber",
                side="e",
                passage_kind="door",
                passage_name="Сдвижная плита с барельефом",
                passage_state="closed",
                secret=True,
                details=[
                    DetailIntent(
                        detail_ref="relic_chest",
                        name="Древний кованый ларец",
                        kind="object",
                        solid=True,
                        cells=[[2, 2, 3, 2]],
                    ),
                    DetailIntent(
                        detail_ref="statue",
                        name="Бронзовый идол предков",
                        kind="object",
                        solid=True,
                        cells=[[4, 4, 4, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="collapsed_atrium", side="s", kind="gap", public_name="Провал в наружной стене", width=2
            ),
        ],
    )
    return meta, intent


def make_ruins_fortified_gatehouse() -> tuple[dict, LayoutIntent]:
    meta = {
        "id": "ruins_fortified_gatehouse",
        "version": "1.0.0",
        "archetype": "ruins",
        "variant": "D",
        "variant_name": "Разрушенный барбакан и надвратная башня",
        "purpose": "Остатки циклопических крепостных ворот с пробитой аркой, караулкой, арсеналом и колодцем",
        "visual_concept": "Зубчатые стены в трещинах, поваленные опускные решётки, разбитые повозки и оружейные стойки.",
        "environment": "mixed",
        "materials": ["stone", "wood"],
        "selected_seed": SELECTED_SEED,
        "gameplay_opportunities": {
            "social": "Стычка или переговоры с заставой наёмников, занявшей ворота.",
            "exploration": "Поиск механизма подъёма решётки, обыск заваленного арсенала.",
            "combat": "Бойницы в караулке и пролом в воротах дают тактическое преимущество обороняющимся.",
        },
        "allowable_adaptations": ["Пограничный КПП", "Форпост орков"],
        "discovered_constraints": ["Барбакан открытый (outdoor), караулка и арсенал закрытые (indoor)."],
        "generation_model": {
            "provider": "deterministic",
            "builder_version": "layout-v1",
            "parameters": {"fallback": False},
        },
    }
    intent = LayoutIntent(
        schema_version=1,
        entry="breached_barbican",
        parts=[
            PartIntent(
                part_ref="breached_barbican",
                role="courtyard",
                name="Пробитый внешний барбакан",
                public_name="Двор перед воротами",
                description="Открытый мощёный двор перед воротами с разбитой повозкой и завалами камней.",
                environment="outdoor",
                shape="rect",
                cols=10,
                rows=8,
                level=0,
                material="stone",
                details=[
                    DetailIntent(
                        detail_ref="cart",
                        name="Разбитая осадная повозка",
                        kind="cover",
                        solid=True,
                        cells=[[2, 2, 3, 3]],
                    ),
                    DetailIntent(
                        detail_ref="rubble_piles",
                        name="Груды обвалившихся зубцов стены",
                        kind="nature",
                        cells=[[7, 2, 8, 3]],
                    ),
                    DetailIntent(
                        detail_ref="well",
                        name="Старый гарнизонный колодец",
                        kind="object",
                        solid=True,
                        cells=[[2, 5, 3, 5]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="gate_vault",
                role="hall",
                name="Сводчатый проезд ворот",
                public_name="Воротный проезд",
                description="Массивный каменный тоннель со сломанной железной герсой и настенными факелами.",
                environment="indoor",
                shape="rect",
                cols=8,
                rows=6,
                level=0,
                material="stone",
                connects_to="breached_barbican",
                side="n",
                passage_kind="arch",
                passage_name="Арка крепостных ворот",
                details=[
                    DetailIntent(
                        detail_ref="broken_gate_timber",
                        name="Останки створок ворот",
                        kind="cover",
                        solid=True,
                        cells=[[1, 1, 2, 1]],
                    ),
                    DetailIntent(
                        detail_ref="wall_sconce",
                        name="Кованые настенные факелы",
                        kind="light",
                        cells=[[6, 1, 6, 1], [6, 4, 6, 4]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="guard_casemate",
                role="quarters",
                name="Караульное помещение",
                public_name="Караулка",
                description="Каменное помещение стражи с очагом, столом караульного и оружейной стойкой.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="gate_vault",
                side="w",
                passage_kind="door",
                passage_name="Узкая дверь караулки",
                details=[
                    DetailIntent(
                        detail_ref="hearth", name="Очаг стражников", kind="light", solid=True, cells=[[2, 0, 3, 0]]
                    ),
                    DetailIntent(
                        detail_ref="desk", name="Караульный стол", kind="furniture", solid=True, cells=[[2, 2, 3, 2]]
                    ),
                    DetailIntent(detail_ref="chair", name="Табуреты", kind="furniture", cells=[[2, 3, 3, 3]]),
                    DetailIntent(
                        detail_ref="weapon_rack",
                        name="Оружейная стойка с алебардами",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 4, 4, 5]],
                    ),
                ],
            ),
            PartIntent(
                part_ref="collapsed_armory",
                role="warehouse",
                name="Заваленный арсенал",
                public_name="Оружейный склад",
                description="Склад оружия со следами обвала, коваными сундуками и ящиками со стрелами.",
                environment="indoor",
                shape="rect",
                cols=6,
                rows=6,
                level=0,
                material="stone",
                connects_to="gate_vault",
                side="e",
                passage_kind="door",
                passage_name="Кованая дверь арсенала",
                details=[
                    DetailIntent(
                        detail_ref="armory_crates",
                        name="Ящики с наконечниками стрел",
                        kind="object",
                        solid=True,
                        cells=[[2, 1, 3, 1]],
                    ),
                    DetailIntent(
                        detail_ref="weapon_rack",
                        name="Стойки для доспехов",
                        kind="furniture",
                        solid=True,
                        cells=[[4, 3, 4, 4]],
                    ),
                    DetailIntent(
                        detail_ref="rubble_piles",
                        name="Обвалившаяся потолочная балка",
                        kind="nature",
                        cells=[[1, 4, 2, 4]],
                    ),
                ],
            ),
        ],
        approaches=[
            ApproachIntent(
                part_ref="breached_barbican", side="s", kind="gap", public_name="Пролом во внешней стене", width=2
            ),
        ],
    )
    return meta, intent


# ==============================================================================
# СБОРКА И ПРОВЕРКА ВСЕХ 24 ШАБЛОНОВ (варианты A, B, C, D)
# ==============================================================================

ALL_TEMPLATES = [
    # Таверна
    make_tavern_roadside,
    make_tavern_urban_cellar,
    make_tavern_fortified_brewery,
    make_tavern_coastal_inn,
    # Храм
    make_temple_compact_shrine,
    make_temple_ruined_courtyard,
    make_temple_sunken_catacombs,
    make_temple_mountain_monastery,
    # Пещера
    make_cave_passages_grotto,
    make_cave_multilevel_grottos,
    make_cave_fungal_chasm,
    make_cave_smugglers_cove,
    # Лес
    make_forest_clearing_trail,
    make_forest_stream_crossing,
    make_forest_druid_grove,
    make_forest_bandit_hideout,
    # Порт
    make_port_quay_warehouse,
    make_port_fishing_pier,
    make_port_shipyard_drydock,
    make_port_lighthouse_isle,
    # Руины
    make_ruins_manor_estate,
    make_ruins_watchpost,
    make_ruins_forgotten_crypt,
    make_ruins_fortified_gatehouse,
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
    "chest": "traveler_chests iron_strongbox relic_chest hidden_safe sarcophagi_north sarcophagi_south burial_niche cargo_chest",
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
    "chair": "chair leather_chair armchair desk_chair bar_stools",
    "desk": "desk study_desk carved_desk overseer_desk ledger_desk interrogation_table",
    "wardrobe": "wardrobe vestment_wardrobe guest_wardrobe linen_press vestment_press",
    "weapon_rack": "weapon_rack weapon_racks armory_rack guard_rack weapon_rack_ruin",
    "workbench": "workbench alchemy_bench craft_table repair_bench prep_table tackle_table gutting_bench",
    "anvil": "anvil smith_anvil iron_anvil",
    "forge": "forge smithy_forge stone_forge",
    "cauldron": "cauldron brewing_cauldron iron_cauldron",
    "chandelier": "chandelier grand_chandelier brass_chandelier iron_chandelier fallen_chandelier",
    "brazier": "brazier watch_brazier fire_brazier temple_brazier coal_brazier incense_braziers",
    "statue": "statue marble_statue warrior_statue saint_statue stone_idol fallen_statue",
    "fountain": "fountain ruined_fountain courtyard_fountain stone_fountain holy_water_font garden_urn",
    "well": "well stone_well courtyard_well deep_well dry_well",
    "sarcophagus": "sarcophagus sarcophagi stone_sarcophagus marble_sarcophagus sarcophagi_north sarcophagi_south burial_niche",
    "tombstone": "tombstone grave_markers ancient_gravestones burial_headstones",
    "cart": "cart transport_cart supply_wagon supply_cart handcart",
    "cage": "cage iron_cage beast_cage gibbet hanging_cage iron_grate_cell",
    "carpet": "carpet tavern_carpet sanctuary_rug ornate_carpet prayer_mat",
    "stump": "stump mossy_stump ancient_stump hollow_stump",
    "log": "log fallen_log timber_log rotting_log fallen_trunk",
    "mushrooms": "mushrooms fungal_patch glowing_mushrooms spore_cluster",
    "sack": "sack grain_sacks flour_sacks supply_sacks spice_bags",
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
        furnish(
            "common_room",
            {
                "hearth": ([[5, 0, 6, 0]], True),
                "bar_counter": ([[1, 1, 1, 3], [2, 3, 3, 3]], True),
                "bar_stools": ([[2, 4, 2, 4], [4, 3, 4, 3]], False),
                "table_north": ([[8, 2, 9, 2]], True),
                "benches_north": ([[8, 1, 9, 1], [8, 3, 9, 3]], False),
                "table_south": ([[8, 7, 9, 7]], True),
                "benches_south": ([[8, 6, 9, 6], [8, 8, 9, 8]], False),
                "ale_casks": ([[1, 7, 1, 7], [2, 8, 2, 8]], True),
            },
        )
        parts["kitchen_pantry"].cols = 6
        parts["kitchen_pantry"].rows = 7
        furnish(
            "kitchen_pantry",
            {
                "stove": ([[0, 1, 0, 2]], True),
                "pantry_shelves": ([[2, 0, 4, 0]], True),
                "prep_table": ([[2, 4, 3, 4]], True),
            },
        )
        parts["guest_rooms"].cols = 7
        parts["guest_rooms"].rows = 8
        furnish(
            "guest_rooms",
            {
                "bunks_north": ([[4, 1, 5, 1]], True),
                "bunks_south": ([[4, 6, 5, 6]], True),
                "traveler_chests": ([[6, 1, 6, 1], [6, 6, 6, 6]], True),
            },
        )
    elif tid == "cave_passages_grotto":
        parts["great_grotto"].cols = 14
        parts["great_grotto"].rows = 12
        furnish(
            "great_grotto",
            {
                "stalagmite_pillars": ([[4, 3, 4, 4], [5, 4, 5, 4]], True),
                "glowing_lichen": ([[10, 2, 10, 2], [11, 3, 11, 3]], False),
                "rock_ledge": ([[3, 9, 4, 9]], False),
            },
        )
        parts["great_grotto"].details.extend(
            [
                DetailIntent(
                    detail_ref="grotto_rocks_east",
                    name="\u0421\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u043e\u0441\u0442\u0440\u043e\u0432\u043e\u043a",
                    kind="cover",
                    solid=True,
                    cells=[[9, 5, 10, 5], [10, 6, 10, 6]],
                ),
                DetailIntent(
                    detail_ref="grotto_rocks_south",
                    name="\u041d\u0438\u0437\u043a\u0438\u0435 \u0441\u0442\u0430\u043b\u0430\u0433\u043c\u0438\u0442\u044b",
                    kind="cover",
                    solid=True,
                    cells=[[6, 8, 6, 8]],
                ),
            ]
        )
        # L-shaped rock islands and offset wall accents retain the existing cave floor algorithm.
        furnish("entry_chasm", {"scree": ([[2, 2, 2, 2], [3, 1, 3, 1]], False)})
    elif tid == "port_quay_warehouse":
        parts["cargo_pier"].cols = 4
        parts["cargo_pier"].rows = 10
        furnish(
            "cargo_pier",
            {
                "cargo_crane": ([[1, 4, 1, 5]], True),
                "coiled_hawsers": ([[2, 3, 2, 3]], False),
                "cleats": ([[1, 8, 1, 8], [2, 8, 2, 8]], False),
            },
        )
        parts["harbor_water_west"].cols = 4
        parts["harbor_water_west"].rows = 10
        parts["harbor_water_east"].cols = 4
        parts["harbor_water_east"].rows = 10
        parts["harbor_water_east"].connects_to = "cargo_pier"
        parts["harbor_water_east"].side = "e"
        parts["harbor_warehouse"].cols = 10
        parts["harbor_warehouse"].rows = 8
        furnish(
            "harbor_warehouse",
            {
                "crate_stacks": ([[2, 1, 3, 2], [6, 1, 7, 2]], True),
                "storage_racks": ([[2, 6, 3, 6], [6, 6, 8, 6]], True),
                "overseer_desk": ([[8, 1, 8, 2]], True),
            },
        )
        # A bindable chest by the overseer's wall reserves generated cargo
        # without making a second decorative chest or blocking the working aisle.
        warehouse = parts["harbor_warehouse"]
        warehouse.scene_profile = "scene_profile.warehouse"
        warehouse.details.append(
            DetailIntent(
                detail_ref="cargo_chest",
                name="Сундук портовых грузов",
                kind="object",
                cells=[[9, 4, 9, 4]],
            )
        )
        warehouse.object_slots.append(
            ObjectSlotIntent(
                slot_ref="cargo_chest",
                role="container",
                detail_ref="cargo_chest",
                cells=[[9, 4, 9, 4]],
            )
        )
        furnish(
            "granite_quay",
            {
                "mooring_bollards": ([[2, 5, 2, 5], [9, 5, 9, 5]], True),
                "cargo_pallets": ([[1, 1, 2, 1], [8, 1, 9, 2]], True),
                "quay_lantern": ([[10, 0, 10, 0]], False),
            },
        )
    elif tid == "tavern_urban_cellar":
        furnish(
            "taproom",
            {"round_tables": ([[5, 2, 6, 2], [6, 5, 7, 5]], True), "ale_casks": ([[1, 1, 1, 1], [1, 4, 1, 4]], True)},
        )
    elif tid == "temple_ruined_courtyard":
        furnish("overgrown_courtyard", {"rubble_piles": ([[2, 2, 3, 2], [7, 6, 7, 6]], False)})
    elif tid == "forest_clearing_trail":
        furnish("sunlit_clearing", {"mushrooms": ([[2, 2, 2, 2], [6, 6, 6, 6]], False)})
    elif tid == "ruins_manor_estate":
        furnish("overgrown_park", {"overgrown_hedges": ([[1, 2, 1, 4], [7, 2, 7, 4]], True)})
    for part in intent.parts:
        for detail in part.details:
            if detail.detail_ref in VISUAL_KEYS:
                detail.visual_key = VISUAL_KEYS[detail.detail_ref]
            elif not detail.visual_key:
                detail.visual_key = f"feature:{detail.detail_ref}"


def author_quality_v3(meta: dict[str, Any], intent: LayoutIntent) -> None:
    """Add roughly 20% breathing room, translating complete furnishing groups.

    Touching props (tables with benches, beds with chests) share a translation.
    Every detail retains its exact footprint; walls retain their attached accents.
    Narrow piers and corridors keep their characteristic width.
    """
    major, minor, _ = meta["version"].split(".")
    meta["version"] = f"{major}.{int(minor) + 1}.0"

    def cells(rectangles):
        return {(x, y) for x1, y1, x2, y2 in rectangles for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)}

    def translation(footprint, old_cols, old_rows, new_cols, new_rows):
        result = []
        for axis, old_size, new_size in ((0, old_cols, new_cols), (1, old_rows, new_rows)):
            lo, hi = min(c[axis] for c in footprint), max(c[axis] for c in footprint)
            added = new_size - old_size
            if lo == 0:
                result.append(0)
            elif hi == old_size - 1:
                result.append(added)
            else:
                result.append(int((lo + hi) / 2 / (old_size - 1) * added + 0.5))
        return tuple(result)

    def shifted(rectangles, delta):
        dx, dy = delta
        return [[x1 + dx, y1 + dy, x2 + dx, y2 + dy] for x1, y1, x2, y2 in rectangles]

    entry = next(p for p in intent.parts if p.part_ref == intent.entry)
    entry_size = (entry.cols, entry.rows)
    for part in intent.parts:
        old_cols, old_rows = part.cols, part.rows
        narrow_pier = meta["id"] == "port_quay_warehouse" and old_cols == 4
        part.cols = old_cols if old_cols < 4 or narrow_pier else int(old_cols * 1.2 + 0.5)
        part.rows = old_rows if old_rows < 4 else int(old_rows * 1.2 + 0.5)
        remaining = {d.detail_ref: cells(d.cells) for d in part.details}
        deltas = {}
        while remaining:
            ref = next(iter(remaining))
            group = [ref]
            footprint = remaining.pop(ref)
            while True:
                neighbors = {
                    (x + dx, y + dy) for x, y in footprint for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
                }
                touching = [ref for ref, occupied in remaining.items() if occupied & neighbors]
                if not touching:
                    break
                for ref in touching:
                    group.append(ref)
                    footprint |= remaining.pop(ref)
            delta = translation(footprint, old_cols, old_rows, part.cols, part.rows)
            deltas.update({ref: delta for ref in group})
        for detail in part.details:
            detail.cells = shifted(detail.cells, deltas[detail.detail_ref])
        for slot in part.object_slots:
            delta = deltas.get(slot.detail_ref)
            if delta is None:
                delta = translation(cells(slot.cells), old_cols, old_rows, part.cols, part.rows)
            slot.cells = shifted(slot.cells, delta)
    # Bands use world coordinates relative to the entry, retaining their width.
    for band in intent.bands:
        scale = entry.rows / entry_size[1] if band.axis == "we" else entry.cols / entry_size[0]
        band.at = int(band.at * scale + 0.5)
        along_scale = entry.cols / entry_size[0] if band.axis == "we" else entry.rows / entry_size[1]
        if band.start is not None:
            band.start = int(band.start * along_scale + 0.5)
        if band.end is not None:
            band.end = int(band.end * along_scale + 0.5)


def build_and_save_template(factory_fn, output_dir: Path) -> dict[str, Any]:
    meta, intent = factory_fn()
    author_quality_v2(meta, intent)
    author_quality_v3(meta, intent)
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
        "detail_preservation": {},
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
    (tdir / "intent.json").write_text(
        json.dumps(intent.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (tdir / "blueprint.json").write_text(
        json.dumps(bp.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (tdir / "validation.json").write_text(
        json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

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
                "sketch": sketches[a.area_ref],
            }
            for a in bp.areas
        ],
    }
    (tdir / "render_payload.json").write_text(
        json.dumps(render_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    resource_path = ROOT / "app" / "content" / "layout_templates" / f"{tid}.json"
    if resource_path.exists():
        resource = json.loads(resource_path.read_text(encoding="utf-8"))
    else:
        envs = {p.environment for p in intent.parts}
        env = "mixed" if len(envs) > 1 else next(iter(envs))
        part_bindings = {"main": intent.entry}
        for p in intent.parts:
            if p.part_ref != intent.entry:
                part_bindings[f"part_{len(part_bindings)}"] = p.part_ref
        resource = {
            "schema_version": 1,
            "id": tid,
            "version": meta["version"],
            "archetype": meta["archetype"],
            "template_ids": [f"location.{meta['archetype']}"],
            "tags": [],
            "environment": env,
            "scale": "medium",
            "part_bindings": part_bindings,
            "intent": intent.model_dump(mode="json"),
        }
    resource["intent"] = intent.model_dump(mode="json")
    resource["version"] = meta["version"]
    resource_path.write_text(json.dumps(resource, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{tid}] Built! Areas: {len(bp.areas)}, Passages: {len(bp.passages)}, Levels: {validation_report['levels']}")
    return meta


def build_all():
    print(f"Building all {len(ALL_TEMPLATES)} templates...")
    manifest = {
        "version": "1.3.0",
        "description": f"Экспериментальная коллекция из {len(ALL_TEMPLATES)} шаблонов локаций для TaleForge",
        "templates": [],
    }
    for fn in ALL_TEMPLATES:
        meta = build_and_save_template(fn, TEMPLATES_DIR)
        manifest["templates"].append(
            {
                "id": meta["id"],
                "archetype": meta["archetype"],
                "variant": meta["variant"],
                "variant_name": meta["variant_name"],
                "purpose": meta["purpose"],
                "environment": meta["environment"],
                "materials": meta["materials"],
                "selected_seed": meta["selected_seed"],
                "tested_seeds": meta["tested_seeds"],
            }
        )
    manifest_path = EXP_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    build_all()
