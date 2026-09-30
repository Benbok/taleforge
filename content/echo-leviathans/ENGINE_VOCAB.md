# Словарь движка (сгенерирован tools/vocab.py)

Всё, что встречается в данных пакета. Движок должен поддерживать каждую строку, иначе запись не исполнится. `custom` — механики, которые движку ещё предстоит поддержать (в живую игру не идут).

## Операции op

| Значение | Раз |
|---|---|
| `resource` | 190 |
| `set` | 172 |
| `save` | 126 |
| `run` | 96 |
| `immunity` | 95 |
| `advantage` | 84 |
| `add` | 82 |
| `custom` | 67 |
| `disadvantage` | 60 |
| `extra_damage` | 58 |
| `sense` | 54 |
| `condition` | 40 |
| `grant_action` | 37 |
| `vulnerability` | 33 |
| `resistance` | 25 |
| `remove_condition` | 21 |
| `check` | 15 |
| `multiply` | 15 |
| `proficiency` | 14 |
| `choose` | 7 |
| `move` | 6 |
| `natural_weapon` | 6 |
| `behavior` | 4 |
| `cast` | 2 |
| `clock` | 1 |
| `revert_form` | 1 |
| `spawn` | 1 |
| `unlock_story` | 1 |

## События триггеров on

| Значение | Раз |
|---|---|
| `hit` | 48 |
| `hit_by` | 37 |
| `enter_area` | 10 |
| `long_rest` | 9 |
| `turn_start` | 7 |
| `day_end` | 6 |
| `resource_changed` | 6 |
| `reduce_target_to_0` | 5 |
| `scene_end` | 5 |
| `spell_cast` | 4 |
| `drop_to_0` | 3 |
| `hour_passed` | 3 |
| `short_rest` | 3 |
| `effect_end` | 2 |
| `feature_used` | 2 |
| `shot` | 2 |
| `ally_drop_to_0_nearby` | 1 |
| `attack` | 1 |
| `channel_divinity_used` | 1 |
| `critical_hit` | 1 |
| `deal_damage` | 1 |
| `echo_technique_used` | 1 |
| `grappled_or_restrained` | 1 |
| `key_deed` | 1 |
| `key_deed_emotional` | 1 |
| `kill` | 1 |
| `liquor_dose` | 1 |
| `loud_sound` | 1 |
| `subclass_gained` | 1 |
| `target_failed_save` | 1 |
| `turn_end` | 1 |

## Ключи условий if / adv_if / dis_if

| Значение | Раз |
|---|---|
| `in_area` | 40 |
| `source_tag` | 35 |
| `all` | 27 |
| `attack_name` | 23 |
| `not` | 18 |
| `any` | 16 |
| `target_tag` | 9 |
| `spell_level_gte` | 6 |
| `stat_gte` | 6 |
| `target_stage` | 6 |
| `cylinder_charged` | 4 |
| `outside_ship_hours_gte` | 4 |
| `source` | 4 |
| `attack` | 3 |
| `caster_tag` | 3 |
| `has_effect` | 3 |
| `in_zone` | 3 |
| `lineage` | 3 |
| `location_belt` | 3 |
| `normal_hearing` | 3 |
| `on_hazard` | 3 |
| `attunement_lte` | 2 |
| `creature_tag` | 2 |
| `has_darkvision` | 2 |
| `injections_since_rest_gt` | 2 |
| `killed_outright` | 2 |
| `liquor_caster` | 2 |
| `marched_today` | 2 |
| `once_per_turn` | 2 |
| `side` | 2 |
| `ally_in_area` | 1 |
| `attacker_within_ft` | 1 |
| `bell_or_howler_nearby` | 1 |
| `bonded_ally_nearby` | 1 |
| `choice` | 1 |
| `corruption_lte` | 1 |
| `creature_stage` | 1 |
| `critical` | 1 |
| `crowded_place` | 1 |
| `damage_dealt` | 1 |
| `damage_type` | 1 |
| `days_since_marker` | 1 |
| `dealt_damage_this_turn` | 1 |
| `distance_over` | 1 |
| `gifts_min_tier_2_count_gte` | 1 |
| `has_effect_ref` | 1 |
| `has_tool` | 1 |
| `healed_hp` | 1 |
| `held` | 1 |
| `holding` | 1 |
| `in_combat` | 1 |
| `location_tag` | 1 |
| `mother_within_miles` | 1 |
| `no_armor` | 1 |
| `no_swarm_kill_days` | 1 |
| `not_wearing` | 1 |
| `once_per_scene_per_creature` | 1 |
| `origin` | 1 |
| `payload_loaded` | 1 |
| `size` | 1 |
| `sleeper_cocoon_nearby` | 1 |
| `sneak_attack` | 1 |
| `source_ref` | 1 |
| `spend_charge` | 1 |
| `spent_echo_on_response_yesterday` | 1 |
| `str_lt` | 1 |
| `target_has_item` | 1 |
| `target_has_natural_armor` | 1 |
| `target_is` | 1 |
| `target_unaware` | 1 |
| `target_wears_armor` | 1 |
| `unconscious` | 1 |
| `unmasked` | 1 |
| `wearing` | 1 |

## Цели target у операций

| Значение | Раз |
|---|---|
| `set: disguised` | 24 |
| `add: ac` | 10 |
| `add: hp` | 10 |
| `set: speed` | 7 |
| `set: spell_source` | 7 |
| `add: hp_max` | 6 |
| `set: hazard_state` | 6 |
| `add: speed` | 5 |
| `set: hp_max` | 5 |
| `set: size` | 5 |
| `add: corruption_save_dc` | 4 |
| `add: echo_response_cost` | 4 |
| `run: hit_target` | 4 |
| `set: ac` | 4 |
| `set: hp` | 4 |
| `set: known_location_to` | 4 |
| `set: temp_hp` | 4 |
| `set: vision` | 4 |
| `add: check` | 3 |
| `add: check_dc` | 3 |
| `add: con` | 3 |
| `add: dc` | 3 |
| `add: echo_hunger_cost` | 3 |
| `add: echo_hunger_dice` | 3 |
| `add: str` | 3 |
| `set: air_supply` | 3 |
| `set: last_liquor_dose_day` | 3 |
| `set: revealed` | 3 |
| `set: sonic_strike_dice` | 3 |
| `add: attack` | 2 |
| `add: damage` | 2 |
| `add: echo_response_dice` | 2 |
| `add: initiative` | 2 |
| `add: save_dc` | 2 |
| `add: temp_hp` | 2 |
| `multiply: damage` | 2 |
| `multiply: price_index.substances` | 2 |
| `resource: revived` | 2 |
| `save: hit_target` | 2 |
| `set: alteration` | 2 |
| `set: corruption` | 2 |
| `set: creature_type` | 2 |
| `set: damage_ignores_resistance` | 2 |
| `set: echo_hunger_available` | 2 |
| `set: echo_response_available` | 2 |
| `set: speed_climb` | 2 |
| `set: spell_slot_top_locked` | 2 |
| `set: spellcasting` | 2 |
| `set: telepathy` | 2 |
| `set: terrain` | 2 |
| `add: blindsight` | 1 |
| `add: cr` | 1 |
| `add: darkvision_range` | 1 |
| `add: diagnost_doses` | 1 |
| `add: echo_hunger_corruption_dc` | 1 |
| `add: echo_pool_max` | 1 |
| `add: encounter_danger_step` | 1 |
| `add: healing_done` | 1 |
| `add: silence_threshold_dc` | 1 |
| `add: spell_attack` | 1 |
| `advantage: allies_in_30ft` | 1 |
| `condition: target` | 1 |
| `condition: victim` | 1 |
| `disadvantage: allies_in_area` | 1 |
| `disadvantage: triggering_attacker` | 1 |
| `multiply: carrying_capacity` | 1 |
| `multiply: damage_taken` | 1 |
| `multiply: echo_pool` | 1 |
| `multiply: exhaustion_recovery` | 1 |
| `multiply: flesh_cutting_time` | 1 |
| `multiply: hive_call_gain` | 1 |
| `multiply: hp_max` | 1 |
| `multiply: price_index.anti_resonance_weapons` | 1 |
| `multiply: price_index.fuel` | 1 |
| `multiply: price_index.liquor` | 1 |
| `multiply: shop_price_house` | 1 |
| `remove_condition: patient` | 1 |
| `resource: patient` | 1 |
| `resource: victim` | 1 |
| `run: contained_body` | 1 |
| `run: patient` | 1 |
| `run: self` | 1 |
| `run: target` | 1 |
| `run: victim` | 1 |
| `run: wearer` | 1 |
| `save: echoed_in_30ft` | 1 |
| `save: entering_creature` | 1 |
| `save: patient` | 1 |
| `save: target` | 1 |
| `save: triggering_creature` | 1 |
| `set: ac_base` | 1 |
| `set: access` | 1 |
| `set: action:slow` | 1 |
| `set: alteration_min` | 1 |
| `set: area` | 1 |
| `set: area_obscurity` | 1 |
| `set: attacks_per_action` | 1 |
| `set: blindsight_range` | 1 |
| `set: brood_release_counter` | 1 |
| `set: can_hide` | 1 |
| `set: can_speak` | 1 |
| `set: carcass_state` | 1 |
| `set: casting_time` | 1 |
| `set: damage_dice` | 1 |
| `set: damage_immunity_as_resistance` | 1 |
| `set: damage_type:bites` | 1 |
| `set: damage_type:lightning_breath` | 1 |
| `set: dependency` | 1 |
| `set: doses_max` | 1 |
| `set: draconic_ancestry_damage_type` | 1 |
| `set: echo_opposite_side_penalty_from` | 1 |
| `set: echo_pool` | 1 |
| `set: echo_technique.is_magic` | 1 |
| `set: escape_dc` | 1 |
| `set: formulas_known` | 1 |
| `set: grenade_range` | 1 |
| `set: habitat` | 1 |
| `set: heads` | 1 |
| `set: highest_available_slot_usable` | 1 |
| `set: hive_call_enabled` | 1 |
| `set: hold_breath_minutes` | 1 |
| `set: igniter_lit` | 1 |
| `set: implant_active` | 1 |
| `set: item_state` | 1 |
| `set: light` | 1 |
| `set: loadable_payload` | 1 |
| `set: location.passage_shortcut` | 1 |
| `set: location.tide_delayed` | 1 |
| `set: location.valve` | 1 |
| `set: max_spell_level` | 1 |
| `set: max_spell_level_cap` | 1 |
| `set: noise_radius` | 1 |
| `set: obscurement` | 1 |
| `set: patient.implant_installed` | 1 |
| `set: prepared_spells` | 1 |
| `set: price_index.substances` | 1 |
| `set: provokes_opportunity_attacks` | 1 |
| `set: psychic_resist_vuln_cancel` | 1 |
| `set: reaction_before_first_turn` | 1 |
| `set: repaired` | 1 |
| `set: skill_expertise` | 1 |
| `set: spell_list` | 1 |
| `set: spell_slot_max_level` | 1 |
| `set: stable` | 1 |
| `set: str` | 1 |
| `set: swarm_gifts_allowed` | 1 |
| `set: target.diagnosed_by` | 1 |
| `set: trait:gibbering` | 1 |
| `set: trait:magic_resistance` | 1 |
| `set: trait:undead_fortitude` | 1 |
| `set: victim.dies` | 1 |
| `set: victim.stable` | 1 |
| `set: weapon.coating` | 1 |
| `set: wielded_weapon` | 1 |

## Нужно движку (need у op: custom)

| Значение | Раз |
|---|---|
| `immunity к эффекту пакета по ссылке (effect_ref), а не только к состоянию SRD; эффекта «приглашение» в пакете нет` | 4 |
| `канон не даёт числа для «почти слепы» и не задаёт зону «абсолютной тишины» (нужен эффект/hazard тишины и величина штрафа)` | 4 |
| `значение sense: telepathy (в enum sense только darkvision|blindsight|tremorsense)` | 2 |
| `иммунитет заклинаний существа к конкретным заклинаниям (Dispel Magic) по источнику spell_source; у immunity есть только damage/condition` | 2 |
| `наложение подавления эффекта (effect.brood_resonance_link) на союзных выводков в радиусе 60 футов на 1 раунд: у run/condition нет area + фильтра целей и длительности` | 2 |
| `переопределить условие SRD-черт Аболета («под водой» → in_area: hazard.blight); канон не уточняет, какие именно бонусы переносятся` | 2 |
| `условие «заклинатель ликвора» (класс: wizard, cleric, paladin, sorcerer, diagnost) и target блокировки ячейки самого высокого доступного круга (spell_slot_top_locked)` | 2 |
| `op reveal_knowledge (следующая ступень «лестницы тайн», living-lore.md 4); оформить как grant_action action с cost: {charges: 1}` | 1 |
| `op возврата экземпляра к исходному шаблону (revert: снять стадию и кокон) с установкой ресурса corruption 5 спасённому` | 1 |
| `op добавления записи в список-стат (list_add: {stat: debt, creditor_ref, amount}); сумма долга в rules.md#3.3 не задана` | 1 |
| `op замены базового шаблона экземпляра существа (rebase: {creature_ref штамма}) при выходе из кокона` | 1 |
| `op записи события в журнал кампании (log_event: {kind, subject})` | 1 |
| `op записи события фракции и изменения state фракции (log_event + faction_state: wanted) со счётчиком использований` | 1 |
| `op записи флагов в state другой сущности (state_flag: {owner: mother, flags: [knows_party_composition, knows_route, knows_weaknesses]}) и событие «разведка» (scout), когда скрытое существо видит/слышит отряд` | 1 |
| `op открытия сюжета/квеста (unlock_story: <id>) и запись квеста в пакете; триггер resource_changed с if stat_gte {echo_attunement: 5} уже выразим` | 1 |
| `op отношения фракции к носителю (attitude: {faction_ref, value}) — чисел в rules.md#3.5 нет, только настрой` | 1 |
| `op перевода листа героя в шаблон NPC (convert_to_npc: {faction: pilots}) — герой уходит из отряда` | 1 |
| `op перевода листа героя в шаблон NPC (convert_to_npc: {template_tags: [echoed], faction: swarm}) — герой уходит из отряда` | 1 |
| `op применения эффекта SRD-заклинания по srd_ref (cast: {srd_ref: Goodberry}) — плоды как «Добрая ягода»` | 1 |
| `op принуждения героя (compel: {action: attack, target: nearest, duration: turn}) — выбор цели отнимается у игрока; op behavior рассчитан на NPC` | 1 |
| `op принуждения героя (compel: {forbid: help_ally, target: triggering_ally, duration: turn}) — op behavior рассчитан на NPC` | 1 |
| `op размещения опасности в локациях (place_hazard: hazard_ref + location_ref/belt), например налёт за Пепельной чертой` | 1 |
| `op размещения/замены опасности в локациях (place_hazard: hazard.blight вместо hazard.bloom)` | 1 |
| `op размещения/замены опасности в локациях (place_hazard: hazard.bloom вместо hazard.blight)` | 1 |
| `op раскрытия знания/направления (reveal: nearest_exit) и условие location_tag: carcass` | 1 |
| `op раскрытия знания/направления (reveal: nearest_vein_or_stash) и условие location_tag: carcass` | 1 |
| `op раскрытия направления игроку (reveal: direction_to, filter: nearest mother, range_miles: 50)` | 1 |
| `op раскрытия сведений о цели игроку (reveal: [resistances, immunities, vulnerabilities, hp_band, corruption])` | 1 |
| `op случайного выбора из списка записи (pick: {from: desire_table}) с сохранением в state героя, либо kind таблицы желаний для op run` | 1 |
| `op смены хозяина локации-туши (owner: crew|resonance) и правило выбора (в каноне не задано)` | 1 |
| `op сотворения SRD-заклинания по srd_ref (cast: {srd_ref, slot: none, save_dc})` | 1 |
| `stat_definition даты последнего флакона ФК (как stat.last_liquor_dose_day) и условие по нему в if; снятие помехи событием «выпит флакон»` | 1 |
| `stat_definition даты последней дозы стимулятора (как stat.last_liquor_dose_day) и условие по нему в if; снятие помехи событием «введён стимулятор»` | 1 |
| `uses.per: campaign; op раскрытия lore_fact (reveal_knowledge с фильтром тега islands и уровня «слухи»); появление NPC-знакомого в порту (условие location_tag: port)` | 1 |
| `в outcomes check — result success_by_10 и nat_20 (20 на кости); у op run — вариант записи (variant: rupture у lineage.kept_self)` | 1 |
| `встречная проверка (check с dc: contest {stat: cha, skill: deception} цели) и событие резкого громкого звука (on: loud_sound — колокол, ревун, выстрел над ухом); target revealed` | 1 |
| `замена заклинаний SRD-шаблона на действие с оплатой ячейками заклинаний (grant_action не умеет cost: spell_slot) и цель target_tag: ship_organism` | 1 |
| `значение sense: detect (или parasite_sense) с фильтром цели (target_tag: parasite) — чувство присутствия, не зрение` | 1 |
| `модель роста опасности (поле growth у hazard_template: скорость/событие) и её подавления (stops_growth_refs у эффектов-зон и радиус)` | 1 |
| `новый вид чувства в op sense (например creature_sense) с полем penetrates: {material: [flesh, bone], thickness_ft: 5}` | 1 |
| `обратное чувство: op sense с полем by (кто чувствует носителя: target_tag mother|invited), range в милях` | 1 |
| `поле closed: true у op check — движок игнорирует все внешние бонусы к броску и снижения сложности (умения, препараты, предметы, заклинания вроде Guidance/Bless, вдохновение), кроме модификаторов самой записи` | 1 |
| `поле closed: true у op check — движок игнорирует все внешние бонусы к броску и снижения сложности (умения, препараты, предметы, заклинания), кроме модификаторов самой записи` | 1 |
| `поле formation у op behavior (formation: dispersed) без смены профиля (у выводков остаётся capturer)` | 1 |
| `поле uses у триггера ({count: 1, per: short_rest}) — лимит срабатывания триггера` | 1 |
| `событие on: liquor_dose (или тег источника dose в if) — чтобы только доза, а не заклинание 5+ или рубка, обновляла stat.last_liquor_dose_day; ломка снимается сама (duration until_dose)` | 1 |
| `событие урона по участку опасности с условиями damage_type и damage_gte (on: area_damaged, if: {damage_type: fire, damage_gte: 10}); op удаления опасности с участка (clear_hazard: {size_ft: 5, regrow: scene_end})` | 1 |
| `событие-таймер с интервалом в игровых минутах (например on: interval, every: {unit: minute, value: 10}); есть только turn_*/round_end/hour_passed. Действие было бы {op: run, ref: hazard.blight, area: square_10}` | 1 |
| `события heal_from_0 (вы вернули хиты существу с 0 хитов) и condition_removed (вы сняли состояние с союзника); поле uses у триггера` | 1 |
| `таймер мира с интервалом (поле every_days у триггера day_end; интервал в rules.md не задан — «раз в несколько дней»); выбор таблицы encounter.ash_line_wave_* по resonance_min/max; запись исхода волны (отбита/прорыв/пленные) событием с clock-дельтой; на 10 цель волн — Средний пояс` | 1 |
| `у op run — параметры повтора: сложность прошлого броска (dc: previous) и переопределённые исходы (success → lineage.kept_self, fail и fail_by_5 → Поглощён)` | 1 |
| `условие «заклинатель ликвора, продолжает колдовать» (liquor_caster + заклинания с последней дозы) для нижней границы Перемены 1` | 1 |
| `условие «значение часов держится N сессий» (clock_held: {clock_ref, value, sessions}; N в каноне не задано — «несколько»); op открытия сюжета (unlock_story) и включения часов (clock_ref активен)` | 1 |
| `условие «цель не знала, что это рой» (target_unaware_of: revealed) и состояние surprised (нет в списке состояний SRD)` | 1 |
| `условие размера (size: medium) для кости natural_weapon; тип урона оружия стадии II в rules.md#6.4 не задан (канон)` | 1 |
| `числа взрыва газового кармана (урон, радиус, спасбросок) в hazard.corpse_gas или в шаблоне локации — в каноне их нет; затем trigger enter_area + in_area: hazard.corpse_gas → run` | 1 |
