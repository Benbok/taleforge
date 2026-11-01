"""The grammatical gender of a hero, guessed once from the name the player gave: the story is told in Russian, where
every past-tense verb and adjective needs it, and a writer left to guess changes its mind from one paragraph to the
next. The guess is by the ending of the first name, with a short list of the common names that break the rule."""

# Men's names that end like women's ones (and the short forms of men's names).
MALE_ENDING_IN_A = frozenset(
    "никита илья лука фома кузьма савва данила дима миша гоша вова коля толя петя ваня паша лёша леша лёня "
    "серёжа сережа вася витя костя гена жора юра слава алёша алеша тима тёма тема".split()
)
# Women's names that end in a consonant or a soft sign.
FEMALE_OTHER = frozenset("любовь нинель адель рашель эстер жизель ингрид".split())
FEMALE_ENDINGS = ("а", "я", "a", "ya")
MALE_ENDINGS_JAPANESE = ("хико", "бико")  # Кунихико, Нобухико: ends in -ко, yet a man
FEMALE_ENDINGS_JAPANESE = ("ко", "ми", "ка", "ри")  # Нанако, Тамаки, Сакура... only when the name is long


def hero_gender(name: str) -> str:
    """Either female or male, guessed from the name; a name that gives no hint falls to male."""
    first = (name or "").strip().split(" ")[0].strip(",.").casefold()
    if not first:
        return "male"
    if first in FEMALE_OTHER:
        return "female"
    if first in MALE_ENDING_IN_A:
        return "male"
    if first.endswith(MALE_ENDINGS_JAPANESE):
        return "male"
    if first.endswith(FEMALE_ENDINGS):
        return "female"
    if len(first) > 4 and first.endswith(FEMALE_ENDINGS_JAPANESE):
        return "female"
    return "male"
