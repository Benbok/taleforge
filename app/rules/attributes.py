"""Attribute keys and stored content reference labels; not a class or skill progression system.

The skill labels are retained only to read existing authored content metadata.
SRD 5.1 reference labels, Wizards of the Coast LLC, CC BY 4.0.
"""

from app.rules.universal.contracts import ABILITY_KEYS

ABILITIES = ABILITY_KEYS
SKILLS = {
    "acrobatics": "dex",
    "animal_handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}
