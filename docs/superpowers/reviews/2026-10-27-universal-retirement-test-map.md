# Retired gameplay test inventory

Only tests for the removed constructor/class/fixed-spell/initiative and split-XP interfaces are retired here. Shared fixtures remain for retained infrastructure tests. Current ownership, transaction, replay, private-card and admission checks run against the real Universal APIs.

| Retired case | Current replacement |
| --- | --- |
| `tests/test_character_admission.py::test_admission_allowed_in_lobby` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_admission_allowed_on_calm_pause` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_admission_forbidden_during_active_session` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_admission_forbidden_in_ended_campaign` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_admission_forbidden_on_paused_with_combat` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_ai_review_finishes_after_resume` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_claim_atomicity_on_rejection` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_original_reserved_seat_cannot_submit_during_active_session` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_paused_secondary_combat_front_blocks_admission` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_pending_turn_blocks_admission` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_session_start_does_not_wait_for_ai_character_review` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_character_admission.py::test_start_races_with_admission` | `test_universal_admission_safety.py / test_universal_growth_playthrough.py` |
| `tests/test_characters.py::test_auto_review_gives_equipment_and_hp` | `test_universal_creation.py / test_equipment_api.py public-card boundary` |
| `tests/test_characters.py::test_master_review_and_visibility` | `test_universal_creation.py / test_equipment_api.py public-card boundary` |
| `tests/test_characters.py::test_options_and_draft_validation` | `test_universal_creation.py / test_equipment_api.py public-card boundary` |
| `tests/test_characters.py::test_roll_abilities_once` | `test_universal_creation.py / test_equipment_api.py public-card boundary` |
| `tests/test_combat.py::test_agent_turn_runs_creatures_and_reaction` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_aggressive_creature_closes_in_then_attacks` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_compound_attack_refusal_keeps_remaining_turn` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_compound_opener_out_of_reach_preserves_turn` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_compound_opening_approach_and_attack_runs_in_order` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_cowardly_flees_and_opportunity_attack` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_ending_combat_discards_unresolved_opening_actions` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_failed_grapple_escape_leaves_condition` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_failed_shove_and_out_of_reach_preserve_rules` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_feature_flags_refuse_unsupported_class_without_burning_attack` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_fight_ends_when_enemies_down` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_fled_creature_leaves_fight_for_hero_with_own_place` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_gate_and_turn_pass` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_grapple_breaks_on_distance_and_incapacitation` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_grapple_escape_consumes_action_and_restores_speed` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_grapple_requires_free_hand_and_melee` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_grapple_success_creates_link_and_zero_speed` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_grappled_creature_cannot_flee_by_skipping_movement_rules` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_multiattack` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_opening_attack_is_resolved_only_in_initiative_order` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_opening_attack_out_of_range_is_not_fabricated_as_miss` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_opening_attack_waits_for_creatures_that_win_initiative` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_opportunity_attack_uses_the_equipped_weapon` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_reaction_declined` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_reckless_attack_uses_real_advantage_for_barbarian` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_round_advance_expires_and_game_time` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_shove_prone_is_contested_and_consumes_single_attack` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_shove_push_moves_target_one_cell_without_damage` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_combat.py::test_timeout_default_action` | `test_universal_combat_actions.py / test_universal_exchange.py / test_universal_combat_playthrough.py` |
| `tests/test_equipment.py::test_composite_switch_is_atomic_when_no_action_remains` | `test_equipment_api.py / test_universal_inventory.py` |
| `tests/test_equipment.py::test_equipment_is_rejected_outside_hero_turn_and_armor_is_rejected_in_combat` | `test_equipment_api.py / test_universal_inventory.py` |
| `tests/test_equipment.py::test_switching_weapon_in_hero_turn_uses_free_interaction_then_action` | `test_equipment_api.py / test_universal_inventory.py` |
| `tests/test_equipment.py::test_two_handed_weapon_displaces_held_weapon_and_shield` | `test_equipment_api.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_defeat_without_kill` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_fallen_hero_gets_no_xp` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_keep_anything_found_in_the_world` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_kill_gives_xp_split_equally` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_leveling_setting_and_sheet_progress` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_milestone_campaign_has_no_xp` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_odd_xp_carries_over` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_only_items_can_be_picked_up` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_picked_up_item_stays_in_inventory` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_progress.py::test_quest_levels_up_the_party` | `test_universal_progression.py / test_universal_rewards.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_ends_when_item_is_dropped` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_equips_unequipped_weapon_from_inventory` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_expires_after_one_world_minute` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_improves_only_held_club_and_preserves_proficiency` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_recasting_and_releasing_weapon` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
| `tests/test_shillelagh.py::test_shillelagh_rejects_empty_hand_and_nonwooden_weapon` | `test_exploration_master.py / test_universal_effects.py / test_universal_inventory.py` |
