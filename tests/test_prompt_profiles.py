"""Профильные секции системного промпта мастера: общий текст для всех ролей, сокращение только в решающей фазе."""

from app.agents.master.common import render

KW = dict(
    campaign_name="Т",
    style=None,
    brief="",
    excluded_themes="",
    public_intro="",
    secrets="",
    has_plot=False,
    pacing="",
    dc_scale="",
    max_calls=8,
    difficulty="medium",
    leveling="milestone",
    random_events=False,
    critical_checks=True,
    audio="",
)
GRAPPLE, REST, CONTAINER = "resolve_grapple", "set_rest_place", "search_container"


def prompt(profile=None):
    return render("master_system.j2", **KW, **({"profile": profile} if profile else {}))


def test_general_profile_keeps_every_rule():
    text = prompt("general")
    assert GRAPPLE in text and REST in text and CONTAINER in text


def test_combat_profile_drops_rest_and_containers_only():
    text = prompt("combat")
    assert GRAPPLE in text and "use_feature" in text and "cast_spell" in text
    assert REST not in text and CONTAINER not in text


def test_exploration_and_social_profiles_drop_combat_rules():
    for profile in ("exploration", "social"):
        text = prompt(profile)
        assert GRAPPLE not in text and "use_feature" not in text
        assert len(text) < len(prompt("general"))
    assert REST in prompt("exploration") and REST not in prompt("social")


def test_roles_without_a_profile_get_the_full_text():
    # шёпот, повествование и проверка не знают профиля хода: им нужен весь свод правил
    assert prompt() == prompt("general") and GRAPPLE in prompt()
