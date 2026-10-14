"""Public spatial defaults for base templates; scenery has no game mechanics."""

# Enclosed places in Echo Leviathans whose broad district/landmark tags also
# describe their parent region. Reviewed against their public descriptions.
INDOOR_LOCATIONS = {
    "location.landmark_treasury", "location.landmark_veche_bell",
    "location.hook_bell_tower_no_ringer", "location.hook_nameless",
    "location.hook_hospital_mercy", "location.hook_unceasing", "location.hook_tower_17",
    "location.hook_league_archive", "location.hook_bell_monastery", "location.hook_echolite_heart",
    "location.old_mother_skull", "location.old_mother_womb", "location.old_mother_heart",
    "location.drowned_lighthouse", "location.drowned_throat", "location.drowned_flooded_womb",
    "location.drowned_abyss_tail", "location.whisperer", "location.whisperer_vault",
    "location.whisperer_choirs", "location.whisperer_reliquary", "location.whisperer_ascension",
    "location.whisperer_neck_cells", "location.rib_forest_skull_chapel",
    "location.rib_forest_marrow_canal",
}

MATERIALS = {
    "location.ship": ("wood", "wood", "wood"),
    "location.port": ("stone", "wood", "wood"),
    "location.market": ("stone", "stone", "earth"),
    "location.city_slums": ("stone", "earth", "stone"),
    "location.road": ("earth", "earth", "earth"),
    "location.cave": ("earth", "earth", "earth"),
}

# (public area name, shape/environment, two decorative landmarks).
# below means a room one level below the entry.
PRESETS = {
    "location.tavern": [
        ("Общий зал", "rect", ("Стойка", "Скамьи")),
        ("Гостевые комнаты", "rect", ("Кровати", "Занавески")),
        ("Погреб", "below", ("Бочки", "Полки")),
    ],
    "location.market": [
        ("Торговая площадь", "open", ("Навес", "Вывески")),
        ("Ряды лавок", "open", ("Прилавки", "Тенты")),
        ("Задний двор", "open", ("Пустые ящики", "Тележка")),
    ],
    "location.temple": [
        ("Притвор", "rect", ("Скамья", "Светильник")),
        ("Святилище", "rect", ("Алтарь", "Резные колонны")),
        ("Кельи", "rect", ("Лежанки", "Ниши")),
    ],
    "location.keep": [
        ("Двор крепости", "open", ("Колодец", "Каменная кладка")),
        ("Казармы", "rect", ("Койки", "Стойки")),
        ("Донжон", "rect", ("Лестничная площадка", "Узкие окна")),
    ],
    "location.port": [
        ("Набережная", "open", ("Причальные тумбы", "Канаты")),
        ("Причалы", "open", ("Деревянный настил", "Сваи")),
        ("Склад", "rect", ("Пустые ящики", "Стеллажи")),
    ],
    "location.village": [
        ("Деревенская площадь", "open", ("Колодец", "Изгородь")),
        ("Улица дворов", "open", ("Заборы", "Скамьи")),
        ("Околица", "open", ("Кустарник", "Дорожный столб")),
    ],
    "location.city_slums": [
        ("Переулок", "open", ("Водосток", "Навес")),
        ("Тесный двор", "open", ("Бельевые верёвки", "Пустые бочки")),
        ("Ночлежка", "rect", ("Лежанки", "Занавески")),
    ],
    "location.manor": [
        ("Приёмный зал", "rect", ("Кресла", "Гобелен")),
        ("Кабинет", "rect", ("Письменный стол", "Книжные полки")),
        ("Сад", "open", ("Клумбы", "Садовая скамья")),
    ],
    "location.library": [
        ("Читальный зал", "rect", ("Столы", "Светильники")),
        ("Книжные ряды", "rect", ("Стеллажи", "Лестница для полок")),
        ("Архив", "rect", ("Шкафы", "Связки бумаг")),
    ],
    "location.road": [
        ("Участок тракта", "open", ("Дорожный столб", "Колея")),
        ("Поворот дороги", "open", ("Валун", "Кустарник")),
        ("Место привала", "open", ("Брёвна", "Следы кострища")),
    ],
    "location.forest": [
        ("Опушка", "open", ("Деревья", "Папоротник")),
        ("Лесная тропа", "open", ("Корни", "Поваленное дерево")),
        ("Поляна", "open", ("Кустарник", "Мшистые камни")),
    ],
    "location.swamp": [
        ("Край болота", "open", ("Камыш", "Кочки")),
        ("Гать", "open", ("Настил из брёвен", "Гнилые пни")),
        ("Островок суши", "open", ("Кривое дерево", "Мох")),
    ],
    "location.mountain_pass": [
        ("Подступ к перевалу", "open", ("Осыпь", "Каменные выступы")),
        ("Горная тропа", "open", ("Скальная стенка", "Камни")),
        ("Площадка перевала", "open", ("Валун", "Редкий кустарник")),
    ],
    "location.cave": [
        ("Входной грот", "cave", ("Сталактиты", "Щебень")),
        ("Каменный проход", "cave", ("Скальные выступы", "Трещины")),
        ("Глубокий грот", "cave", ("Сталагмиты", "Влажный камень")),
    ],
    "location.crypt": [
        ("Входной зал", "rect", ("Каменная плита", "Потухшие светильники")),
        ("Погребальные ниши", "rect", ("Саркофаги", "Резные ниши")),
        ("Дальний склеп", "below", ("Надгробные плиты", "Каменные скамьи")),
    ],
    "location.ruins": [
        ("Разрушенный двор", "open", ("Обломки кладки", "Сорная трава")),
        ("Остатки зала", "open", ("Остатки колонн", "Каменные плиты")),
        ("Уцелевшее помещение", "rect", ("Трещины в стенах", "Обломки балок")),
    ],
    "location.dungeon": [
        ("Входной зал", "rect", ("Ниши", "Ржавые скобы")),
        ("Проход между камерами", "rect", ("Решётки", "Каменные скамьи")),
        ("Нижняя камера", "below", ("Кольца в стене", "Трещины кладки")),
    ],
    "location.lair": [
        ("Вход в логово", "cave", ("Следы на земле", "Камни")),
        ("Основной грот", "cave", ("Лежанка", "Кости")),
        ("Дальняя ниша", "cave", ("Скальные выступы", "Щебень")),
    ],
    "location.ship": [
        ("Палуба", "open", ("Мачта", "Свёрнутые канаты")),
        ("Каюты", "rect", ("Койки", "Иллюминаторы")),
        ("Трюм", "below", ("Пустые бочки", "Деревянные стойки")),
    ],
    "location.camp": [
        ("Вход в лагерь", "open", ("Коновязь", "Колышки")),
        ("Площадка костра", "open", ("Кострище", "Брёвна")),
        ("Ряд палаток", "open", ("Полотнища палаток", "Верёвки")),
    ],
}
