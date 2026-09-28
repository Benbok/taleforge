# Базовый пакет правил dnd5e-srd

Общая для всех кампаний механика из SRD 5.1: характеристики и ресурсы героя, 15 состояний, оружие, доспехи, шкала сложностей, монстры, классы и расы.

Файлы `data/`:

- `stats.yaml`, `conditions.yaml`, `weapons.yaml`, `armor.yaml`, `dc_scale.yaml` — написаны вручную;
- `monsters.yaml` — все монстры SRD 5.1 (`creature_template`, 334 записи): имена по-русски, статблок, действия с разобранными атаками, уроном и спасбросками;
- `classes.yaml` — 12 классов SRD (`class`): кость хитов, владения, стартовое снаряжение, таблица уровней 1–20 с ячейками заклинаний, умения класса (без подклассов);
- `races.yaml` — 9 рас SRD как происхождения (`origin`): подраса — отдельная запись с уже слитыми бонусами и чертами базовой расы.

Три последних файла сгенерированы скриптом `tools/import_srd.py` из базы [5e-bits/5e-database](https://github.com/5e-bits/5e-database) (SRD 5.1, CC BY 4.0), версия зафиксирована коммитом в скрипте. Руками их не правят: чтобы обновить, поправьте генератор (или коммит) и запустите из корня репозитория

```
python tools/import_srd.py            # JSON кэшируется в tools/.cache/ (вне git)
python tools/import_srd.py --refresh  # перекачать JSON
```

Формат полей описан в шапке каждого файла.
Пакет сеттинга подключает его через `ruleset_base: srd-5.1` и может переопределить запись тем же `id` или выключить её через `excludes`.

Формат записей и язык модификаторов — как в пакете «Эхо Левиафанов» (ТЗ, раздел 3.2). Дополнения этого пакета:

- `who: attackers` у `advantage` / `disadvantage` — бросок атаки **по** существу с этим эффектом, а не его собственный;
- `within_ft` — условие дистанции для такого броска;
- `auto: fail` у `set` с `target: save_result` или `check_result` — автоматический провал;
- `levels` у `condition.exhaustion` — модификаторы по уровням истощения, накопительно.

Проверка: `python -m app.content validate content/dnd5e-srd`.

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.
