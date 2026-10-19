from app.agents.master.outcomes import failed_item_action
from app.content.catalog import Catalog, Entry


def test_older_catalog_gets_engine_consumable_without_replacing_override():
    spell = Entry("spell.goodberry", "spell", "canon", "old-pack", {"name": "Добрая ягода"})
    old = Catalog({spell.id: spell}).view(False)
    assert old.get("item.goodberry", "item_template").data["modifiers"][0]["delta"] == 1
    override = Entry("item.goodberry", "item_template", "canon", "world", {"name": "Ягода мира"})
    assert Catalog({spell.id: spell, override.id: override}).view(False).get(override.id).name == "Ягода мира"


def test_inventory_failure_recovery_is_scoped_to_item_and_recipient():
    failed = {
        "tool": "pass_item",
        "args": {"character_id": "hero", "inventory_id": "berry", "to_entity_id": "npc"},
        "result": {"ok": False},
    }
    recovered = {**failed, "result": {"ok": True}}
    other = {**recovered, "args": {**failed["args"], "inventory_id": "rope"}}
    assert failed_item_action([failed])
    assert not failed_item_action([failed, recovered])
    assert failed_item_action([failed, other])


def test_master_extra_item_call_refused_for_no_request_is_not_a_failed_player_action():
    # плейтест 19.10: «даю ягоду стражнику» — передача прошла, а лишний use_item мастера (скормить ягоду, чего
    # игрок не заявлял) отклонён как no_matching_action; ответ заменялся сводкой «часть действий не выполнена»
    extra = {
        "tool": "use_item",
        "args": {"character_id": "hero", "inventory_id": "berry", "target_id": "npc"},
        "result": {"ok": False, "failure": {"code": "no_matching_action", "category": "rule_denial"}},
    }
    passed = {
        "tool": "pass_item",
        "args": {"character_id": "hero", "inventory_id": "berry", "to_entity_id": "npc"},
        "result": {"ok": True},
    }
    assert not failed_item_action([extra, passed])
    assert failed_item_action([{**passed, "result": {"ok": False}}])
