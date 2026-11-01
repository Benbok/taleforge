"""The hero's grammatical gender is guessed from the name, the same way every time."""

import pytest

from app.core.universal.gender import hero_gender


@pytest.mark.parametrize(
    "name",
    ["Лира", "Сора", "Анна Каренина", "Мария", "Ольга", "Любовь", "Нанако", "Мицури", "Lira", "Katya", "Юлия"],
)
def test_a_name_that_ends_like_a_womans_is_taken_as_one(name):
    assert hero_gender(name) == "female"


@pytest.mark.parametrize(
    "name",
    ["Тандзиро", "Кунихико", "Иван Петров", "Никита", "Илья", "Лука", "Миша", "Олег", "Артём", "Игорь", "Roman", ""],
)
def test_other_names_and_mens_names_ending_in_a_are_taken_as_a_mans(name):
    assert hero_gender(name) == "male"


def test_only_the_first_name_counts_and_the_guess_is_stable():
    assert hero_gender("Сора  Дровосек") == hero_gender("Сора") == hero_gender("сора")
