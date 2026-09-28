"""Словарь ядра: что движок обязан уметь исполнять. Пакет может использовать только это.

Список взят из языка модификаторов пакета «Эхо Левиафанов» (README пакета, раздел «Язык модификаторов»).
Новая операция — это правка движка и этого файла, а не пакета.
"""

ENGINE_VERSION = "0.1.0"

MODIFIER_OPS = frozenset(
    {
        "advantage",
        "disadvantage",
        "add",
        "multiply",
        "set",
        "resistance",
        "vulnerability",
        "immunity",
        "sense",
        "extra_damage",
        "condition",
        "resource",
        "save",
        "check",
        "run",
        "proficiency",
        "move",
        "remove_condition",
        "choose",
        "grant_action",
        "natural_weapon",
        "clock",
        "spawn",
        "behavior",
        "custom",
    }
)

# op: custom — механика не формализована. Такая запись в живую игру не попадает (ТЗ, раздел 3.2).
CUSTOM_OP = "custom"

TRIGGER_EVENTS = frozenset(
    {
        "turn_start",
        "turn_end",
        "round_end",
        "scene_end",
        "short_rest",
        "long_rest",
        "day_end",
        "hour_passed",
        "hit",
        "hit_by",
        "miss",
        "crit",
        "deal_damage",
        "take_damage",
        "drop_to_0",
        "reduce_target_to_0",
        "ally_drop_to_0_nearby",
        "spell_cast",
        "echo_technique_used",
        "feature_used",
        "effect_end",
        "enter_area",
        "resource_changed",
        "clock_threshold",
        "key_deed",
    }
)
