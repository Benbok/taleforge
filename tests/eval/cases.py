"""Fixed, versioned expectations for two independent worlds."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Expect:
    effect_kinds: set[str] = field(default_factory=set)
    destination: str | None = None
    resolution: str | None = None
    recipient: bool = False
    forbid_kinds: set[str] = field(default_factory=set)
    quotes_from_source: bool = True
    source: str | None = None
    forbid_introductions: bool = False


@dataclass(frozen=True)
class EvalCase:
    name: str
    fixture: str
    source: str
    expect: Expect


CASES = (
    EvalCase("shire_kitchen", "shire", "Иду на кухню.", Expect({"move"}, "en_7676b2ea4eea28b4f44970d0")),
    EvalCase(
        "shire_closed_door",
        "shire",
        "Выхожу через боковую дверь на задворки.",
        Expect({"move"}, "en_08f52a8495398b3be8b49644"),
    ),
    EvalCase(
        "shire_cellar", "shire", "Спускаюсь по лестнице в подвал.", Expect({"move"}, "en_9e77dfaec4debdb96a1d7313")
    ),
    EvalCase("shire_typo", "shire", "ахожу на кухню", Expect({"move"}, "en_7676b2ea4eea28b4f44970d0")),
    EvalCase(
        "shire_speech",
        "shire",
        "Говорю хозяину с кружками: добрый вечер!",
        Expect({"speak"}, resolution="automatic", recipient=True),
    ),
    EvalCase(
        "shire_question",
        "shire",
        "Спрашиваю хозяина с кружками: что сегодня на ужин?",
        Expect({"speak"}, resolution="automatic", recipient=True),
    ),
    EvalCase("shire_observe", "shire", "Осматриваю зал.", Expect({"observe"}, resolution="automatic")),
    EvalCase("shire_approach", "shire", "Подхожу к дубовому столу внутри зала.", Expect({"move"})),
    EvalCase("shire_wait", "shire", "Жду минуту.", Expect({"wait"}, resolution="automatic")),
    EvalCase(
        "shire_magic",
        "shire",
        "Колдовством зажигаю светлячков над ладонью.",
        Expect({"illumination"}, source="supernatural"),
    ),
    EvalCase(
        "station_closed", "station", "Захожу в лабораторию через закрытую дверь.", Expect({"move"}, "station_lab")
    ),
    EvalCase("station_locked", "station", "Иду через запертый шлюз без ключа.", Expect(forbid_kinds={"move"})),
    EvalCase(
        "station_speech",
        "station",
        "Говорю технику Илье: привет!",
        Expect({"speak"}, resolution="automatic", recipient=True),
    ),
    EvalCase(
        "station_question",
        "station",
        "Спрашиваю техника Илью, где лаборатория.",
        Expect({"speak"}, resolution="automatic", recipient=True),
    ),
    EvalCase("station_take", "station", "Беру гаечный ключ со стола.", Expect({"take"})),
    EvalCase(
        "station_absent_gift",
        "station",
        "Отдаю технику золотую корону, которой у меня нет.",
        Expect(forbid_kinds={"give"}),
    ),
    EvalCase(
        "station_no_magic",
        "station",
        "Колдовством зажигаю светлячков над ладонью.",
        Expect(source="mundane", forbid_kinds={"illumination", "create_object", "change_form"}),
    ),
    EvalCase(
        "station_sound", "station", "Прислушиваюсь к стуку за стеной.", Expect({"observe"}, forbid_introductions=True)
    ),
    EvalCase("station_observe", "station", "Осматриваюсь.", Expect({"observe"}, resolution="automatic")),
    EvalCase("station_wait", "station", "Жду минуту.", Expect({"wait"}, resolution="automatic")),
    # The long game: twenty narrations of evidence and a campaign summary, as in a session of dozens of turns.
    EvalCase("long_inn", "long", "Иду к постоялому двору.", Expect({"move"}, "en_9e68635719537689352550e6")),
    EvalCase("long_goat_path", "long", "Сворачиваю на козью тропку.", Expect({"move"}, "en_6b3f4fb27cdc4d778d0ba837")),
    EvalCase("long_observe", "long", "Осматриваюсь вокруг.", Expect({"observe"}, resolution="automatic")),
    EvalCase("long_wait", "long", "Жду, пока гонец отдышится.", Expect({"wait"}, resolution="automatic")),
    EvalCase(
        "long_recall_promise",
        "long",
        "Вспоминаю, что я обещал гонцу.",
        Expect(forbid_kinds={"move"}, resolution="automatic", forbid_introductions=True),
    ),
    EvalCase(
        "long_recall_letter",
        "long",
        "Вспоминаю, что мы знаем о письме.",
        Expect(forbid_kinds={"move"}, resolution="automatic", forbid_introductions=True),
    ),
)
