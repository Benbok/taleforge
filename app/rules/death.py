"""Shared class-independent death-save arithmetic."""

from dataclasses import replace

from app.rules.base import DeathSaves


def apply_death_roll(hp, natural):
    if type(natural) is not int or not 1 <= natural <= 20 or not hp.dying:
        raise ValueError("Недопустимый спасбросок")
    saves = hp.death_saves
    regained = 0
    if natural == 20:
        hp.current = 1
        hp.death_saves = DeathSaves()
        regained = 1
    elif natural == 1:
        hp.death_saves = replace(saves, failures=saves.failures + 2)
    elif natural >= 10:
        hp.death_saves = replace(saves, successes=saves.successes + 1)
    else:
        hp.death_saves = replace(saves, failures=saves.failures + 1)
    if hp.death_saves.dead:
        hp.dead = True
    return regained
