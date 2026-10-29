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

## Removed after the final retirement run (tool-call turn pipeline)

These tests drove the retired tool-call master turn (resolve_attack, set_scene_mode, initiative, legacy hero creation). New campaigns run the Universal turn, so they time out or fail on missing tools. Replacement is listed per file; "no universal equivalent" marks a coverage gap, not a replacement.

| Retired case | Current replacement |
| --- | --- |
| `tests/test_action_admission.py::test_inspect_request_survives_technical_parser_failure` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_adventure.py::test_autonomous_npc_spawn_preserves_empty_room_and_book_encounter` | test_universal_launch.py |
| `tests/test_adventure.py::test_book_room_public_description_excludes_scripted_encounter` | test_universal_launch.py |
| `tests/test_adventure.py::test_budget_refusal_tells_master_how_to_cut_book_encounter` | test_universal_launch.py |
| `tests/test_adventure.py::test_campaign_from_module_runs_room_by_room` | test_universal_launch.py |
| `tests/test_adventure_instances.py::test_launch_is_a_fresh_game_with_pinned_content_and_no_prep_history` | test_universal_launch.py |
| `tests/test_adventure_instances.py::test_launch_request_key_is_idempotent_and_conflicts_on_other_options` | test_universal_launch.py |
| `tests/test_adventure_instances.py::test_launch_takes_wizard_settings_and_keeps_author_intro_unless_overridden` | test_universal_launch.py |
| `tests/test_adventure_instances.py::test_two_launches_are_independent_and_local` | test_universal_launch.py |
| `tests/test_adventure_library.py::test_library_lists_only_own_summaries_and_launch_is_idempotent` | test_universal_launch.py |
| `tests/test_ai_players.py::test_ai_player_answers_once_after_master` | no universal equivalent |
| `tests/test_ai_players.py::test_ai_player_takes_its_combat_turn_or_passes` | no universal equivalent |
| `tests/test_ai_players.py::test_owner_seats_ai_and_builds_its_hero` | no universal equivalent |
| `tests/test_ai_players.py::test_player_takes_ai_seat_and_its_hero` | no universal equivalent |
| `tests/test_ai_players.py::test_vote_hands_hero_to_ai_and_back` | no universal equivalent |
| `tests/test_audio.py::test_combat_music_and_cues` | no universal equivalent |
| `tests/test_audio.py::test_snapshot_and_broadcast` | no universal equivalent |
| `tests/test_authoring_acceptance.py::test_author_to_independent_games` | test_universal_studio.py |
| `tests/test_authoring_projects.py::test_game_recovery_ignores_author_world` | test_universal_studio.py |
| `tests/test_bonds.py::test_ai_master_asks_hooks_and_introduces` | no universal equivalent |
| `tests/test_bonds.py::test_review_links_hero_to_plan` | no universal equivalent |
| `tests/test_combat_screen.py::test_death_saves_are_open_to_the_table` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_combat_screen.py::test_snapshot_has_initiative_strip_without_creature_numbers` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_failed_provider_clears_running_attempt` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_retry_during_active_session_returns_conflict` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_review_has_two_responses_and_restores_failure` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_review_repairs_arguments_once_and_executes_one_decision` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_review_started_from_old_process_is_interrupted_without_retry` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_compact_review.py::test_running_attempt_coalesces_and_rechecks_admission` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_companions.py::test_betrayal_inserts_former_companion_into_live_initiative` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_companions.py::test_companion_attack_has_its_own_action_and_cannot_repeat` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_companions.py::test_companion_does_not_get_a_separate_initiative_slot` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_companions.py::test_enemy_target_selection_includes_companion` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_container_pickup.py::test_container_actions_complete_a_real_game_turn` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_container_pickup.py::test_container_pickup_does_not_bypass_access` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_context_eval_variants.py::test_historical_assembly_recovers_full_request_from_split_inputs` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_eval_variants.py::test_real_child_dispatches_variants_and_compares_outcomes` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_quality.py::test_context_quality_scenario_executes_complete_game_turn` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_quality.py::test_unknown_parser_failure_keeps_request_for_master` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_runtime_integration.py::test_production_decide_request_selects_snapshot_facts` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_runtime_integration.py::test_production_narrate_request_uses_audience_safe_snapshot` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_context_runtime_integration.py::test_real_narration_keeps_location_private_state_out_of_model_packet` | test_universal_public_context.py / test_universal_effect_privacy.py / test_universal_location_knowledge.py (privacy) |
| `tests/test_decision_action_refs.py::test_decision_read_only_ignores_malformed_surplus_ref` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_decision_action_refs.py::test_hostile_routes_validate_ref_before_initiative` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_decision_action_refs.py::test_invalid_sources_have_one_repair_and_stop_batch` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_decision_completion.py::test_creative_talk_finishes_without_automatic_cancellation` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_decision_completion.py::test_early_finish_stays_gated_until_quality_review` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_decision_tool_profiles.py::test_native_batch_checks_live_profile_before_and_after_expansion` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_economy.py::test_dash_action_doubles_steps` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_economy.py::test_hero_turn_counts_action_bonus_and_moves` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_economy.py::test_item_interaction_first_free_second_uses_action_and_third_refuses` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_game_screen.py::test_cards_show_only_what_this_hero_learned` | test_universal_game_view.py |
| `tests/test_game_screen.py::test_knowledge_notice_goes_only_to_that_player` | test_universal_game_view.py |
| `tests/test_game_screen.py::test_narrator_accepts_status_rule_references` | test_universal_game_view.py |
| `tests/test_game_screen.py::test_roll_cards_before_narration_and_hidden_rolls_stay_hidden` | test_universal_game_view.py |
| `tests/test_geography_travel.py::test_one_way_hidden_and_closed_routes` | test_universal_passages.py / test_universal_world_exploration.py |
| `tests/test_geography_travel.py::test_prepared_start_is_entered_without_new_generation` | test_universal_passages.py / test_universal_world_exploration.py |
| `tests/test_geography_travel.py::test_route_travel_moves_atomically_both_ways_without_state_links` | test_universal_passages.py / test_universal_world_exploration.py |
| `tests/test_geography_travel.py::test_tool_path_succeeds_and_failure_is_a_tool_error` | test_universal_passages.py / test_universal_world_exploration.py |
| `tests/test_geography_travel.py::test_wrong_room_split_party_and_unknown_route_do_not_move_anyone` | test_universal_passages.py / test_universal_world_exploration.py |
| `tests/test_gm_mood.py::test_mood_lives_in_scene_and_reaches_narration` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_grid.py::test_combat_start_puts_everyone_on_a_cell` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_grid.py::test_items_and_landmarks_lie_on_exact_cells` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_hero_screen.py::test_explain_numbers_of_own_hero` | test_universal_card.py / test_universal_game_view.py |
| `tests/test_hero_screen.py::test_quick_action_skips_parser_but_not_validation` | test_universal_card.py / test_universal_game_view.py |
| `tests/test_hero_screen.py::test_quick_move_to_a_place_named_in_the_story_is_accepted` | test_universal_card.py / test_universal_game_view.py |
| `tests/test_intent.py::test_chat_grapple_starts_initiative_and_applies_real_condition` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_chat_shove_starts_initiative_before_contested_maneuver` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_combat_limit_and_missing_item` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_combat_parser_does_not_restore_identical_discarded_parts` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_combat_parser_keeps_move_before_attack_without_dropped_parts` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_empty_parse_does_not_loop_or_auto_cancel_the_request` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_empty_parser_actions_preserve_source_for_master_resolution` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_master_repeat_of_routed_cast_spends_no_second_slot` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_native_chat_kind_from_parser` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_natural_language_approach_attack_starts_combat_and_moves_first` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_natural_language_move_then_spell_starts_initiative_and_moves_first` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_parser_garbage_preserves_request_for_master_without_executing_it` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_rejects_offtopic_and_unclear` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_routed_hostile_spell_starts_initiative_before_cast` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent.py::test_router_attack_and_intent_saved` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent_recovery.py::test_empty_parser_result_preserves_original_request_for_master` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_intent_recovery.py::test_gateway_recovery_saves_validated_message_for_its_owner` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_invent_item.py::test_master_turn_invents_and_gives` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_json_textcalls.py::test_decide_retries_json_without_executing_it` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_layout_ahead.py::test_arrival_requests_geometry_of_at_most_two_neighbours` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_ahead.py::test_prepared_neighbour_stays_unknown_to_players` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_ahead.py::test_secret_neighbour_is_never_prepared_ahead` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_improvisation.py::test_unplanned_location_created_and_prepared_in_turn` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_pilot.py::test_pilot_field_temple_and_back` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_arrival_message_gives_the_master_a_real_action_to_resolve` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_closed_door_refuses` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_door_closed_during_preparation_keeps_area_but_not_hero` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_exit_to_the_bare_complex_root_keeps_the_party_in_the_entry_area` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_hidden_passage_reads_as_missing` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_incapacitated_hero_cannot_pass` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_open_field_keeps_the_lane_both_ways` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_player_cannot_traverse_outside_combat_turn` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_successful_map_traverse_creates_master_turn_input` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_traverse_from_outside_prepares_then_moves` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_transit.py::test_walking_to_the_door_happens_before_preparation` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_panel_transit_finishes_in_background` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_preparing_resume_waits_outside_database_transaction` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_queue_conflict_keeps_turn_preparing_for_recovery` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_recovery_completes_panel_transit_without_master_turn` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_republish_failure_does_not_interrupt_completed_turn` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_republish_sends_after_database_session_closes` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_split_party_narration_follows_transiting_crew` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_transit_event_survives_publication_failure_in_checkpoint` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_turn_moves_through_passage_before_narration` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_layout_turn.py::test_turn_publishes_the_new_area_after_narration` | test_universal_map.py / test_universal_passages.py / test_universal_places.py |
| `tests/test_lead.py::test_master_leads_by_plan` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_location_maps_delivery3.py::test_pilot_brief_has_no_plot_secrets` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_location_maps_delivery3.py::test_pilot_model_failure_falls_back_and_is_diagnosable` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_location_maps_delivery3.py::test_pilot_opening_generates_temple_and_field_once` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_location_maps_delivery3.py::test_pilot_round_trip_keeps_structure_and_costs_nothing_new` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_location_maps_delivery3.py::test_pilot_secret_vault_is_not_disclosed_by_preparation` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_map.py::test_positions_distance_cover_and_areas` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_ai_master_reviews_character` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_failed_ai_review_is_visible_and_owner_can_approve` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_failed_enter_room_does_not_spawn_or_claim_arrival` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_failed_resolve_attack_cannot_be_narrated_as_hit` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_failed_turn_rolls_back` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_master_log_for_admins_with_secret_switch` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_narration_blocks_repeated_unregistered_enemies` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_narration_corrects_unregistered_numbered_enemies` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_silent_model_gets_auto_cancel` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_transition_retry_can_succeed` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master.py::test_turn_with_tool_and_markup_audit` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master_panel.py::test_live_master_calls_show_in_log` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master_panel.py::test_panel_lists_values_and_labels_for_master_seat` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_master_prompt_context.py::test_enabled_roles_integrate_with_refs_and_profiles` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_memory.py::test_rolling_summary_and_context` | test_universal_master.py |
| `tests/test_memory.py::test_rules_in_decision_prompt` | test_universal_master.py |
| `tests/test_module_intro.py::test_admin_reviews_module_intro_and_campaigns_share_it` | no universal equivalent |
| `tests/test_module_intro.py::test_new_campaign_takes_voice_of_saved_intro` | no universal equivalent |
| `tests/test_modules.py::test_import_retries_reads_maps_and_publishes_a_pack` | test_universal_launch.py |
| `tests/test_movement_economy.py::test_cumulative_movement_spends_dash_action` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_movement_economy.py::test_movement_cannot_exceed_dash_without_action` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_movement_economy.py::test_reposition_rejects_out_of_turn_character_movement` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_movement_economy.py::test_reposition_uses_movement_ledger` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_actions.py::test_combat_multipart_cannot_gain_extra_action` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_actions.py::test_old_single_action_and_unparsed_custom_still_work` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_actions.py::test_recovery_after_effect_before_publication_does_not_repeat` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_actions.py::test_turn_rollback_reverts_effects_and_progress` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_actions.py::test_two_part_search_and_cast_completes_both` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_narration.py::test_completed_multipart_has_no_partial_cancel` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_narration.py::test_one_denial_preserves_other_committed_facts` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_narration.py::test_only_search_left_names_search` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_progress.py::test_cast_and_search_discovery_complete_both` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_multipart_replay.py::test_two_cast_parts_spend_separately_but_replay_spends_once` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_narration_integrity.py::test_failed_item_grant_cannot_be_narrated_as_inventory_success` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_narrator_retries_invented_player_reply_before_streaming` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_repeated_invented_player_reply_is_blocked` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_repeated_unknown_npc_does_not_undo_successful_transition` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_retry_cannot_keep_unknown_npc_by_removing_markup` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_second_unknown_npc_is_blocked_even_without_numbered_name` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narration_integrity.py::test_submitted_player_dialogue_is_allowed` | test_universal_narration_style.py / test_universal_review_regressions.py |
| `tests/test_narrative.py::test_check_only_turn_asks_for_short_outcome` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative.py::test_ordinary_turn_is_one_short_paragraph` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative.py::test_stalled_party_gets_new_opportunity` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_adaptive_module.py::test_human_master_route_uses_explicit_front_clock` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_canon_readers.py::test_module_override_reaches_book_reader_and_stays_in_its_campaign` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_canon_readers.py::test_role_and_motive_reach_master_prompt_and_hero_card` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_canon_readers.py::test_turn_reserves_public_claims_before_narration` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_first_slice.py::test_alliance_changes_main_story_and_survives_reconnect` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_gate_d.py::test_alliance_future_job_next_scene_and_reconnect` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_master.py::test_adapt_story_binds_current_message_marker` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_master.py::test_adapt_story_rejects_invented_message_ref` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_master.py::test_adaptation_does_not_complete_failed_player_action` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_master.py::test_empty_message_id_is_not_current` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_startup.py::test_act_close_reaches_receipt_and_changes_future_node` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_startup.py::test_no_change_answer_leaves_receipt_and_world_revision` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_startup.py::test_restart_applies_prepared_draft_without_new_author_call` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_narrative_startup.py::test_session_pause_prepares_next_session_and_resume_works` | test_universal_first_adventure.py / test_universal_playthrough.py |
| `tests/test_offline.py::test_combat_turn_of_absent_hero_is_skipped` | no universal equivalent |
| `tests/test_offline.py::test_live_master_leaves_ai_takes_over_and_gives_back` | no universal equivalent |
| `tests/test_offline.py::test_vote_hands_hero_to_other_player_and_back` | no universal equivalent |
| `tests/test_offline.py::test_waiting_for_replies_skips_absent_player` | no universal equivalent |
| `tests/test_opening_complex.py::test_blocked_structure_keeps_heroes_outside` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_complex.py::test_intro_text_is_written_after_entry` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_complex.py::test_opening_walks_into_entry_before_intro` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_complex.py::test_second_opening_does_not_enter_again` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_conditions.py::test_late_joiner_after_stash_opened` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_conditions.py::test_prelude_confiscates_gear` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_opening_scene.py::test_module_opening_npc_is_registered_in_entered_room` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_party_split.py::test_fight_is_only_where_the_foes_are` | no universal equivalent |
| `tests/test_party_split.py::test_fronts_end_separately` | no universal equivalent |
| `tests/test_party_split.py::test_groups_are_answered_separately` | no universal equivalent |
| `tests/test_party_split.py::test_hero_joins_and_leaves_a_fight_by_moving` | no universal equivalent |
| `tests/test_party_split.py::test_late_hero_changes_only_the_budget_of_their_location` | no universal equivalent |
| `tests/test_party_split.py::test_master_sees_every_place_of_split_party` | no universal equivalent |
| `tests/test_party_split.py::test_split_party_has_own_chat_and_meets_again` | no universal equivalent |
| `tests/test_pending.py::test_empty_batch_is_skipped_without_model` | test_universal_lifecycle.py |
| `tests/test_pending.py::test_retry_failed_reply_queues_it_again_without_a_copy` | test_universal_lifecycle.py |
| `tests/test_pending.py::test_turn_publishes_states` | test_universal_lifecycle.py |
| `tests/test_persona.py::test_chronicle_notes_edit_revert_and_reach_the_agent` | no universal equivalent |
| `tests/test_persona.py::test_master_character_help_test_and_prompt` | no universal equivalent |
| `tests/test_playtest_additions.py::test_charmed_enemy_cannot_attack_source` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_checks.py::test_search_success_returns_to_decider_until_fact_recorded` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_checks.py::test_unresolved_search_is_not_allowed_to_invent_keys` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_items.py::test_keep_found_rejects_copy_of_existing_campaign_item` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_items.py::test_keep_found_rejects_unowned_source_item_even_after_success` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_items.py::test_keep_found_requires_successful_current_hero_check` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_playtest_items.py::test_npc_owned_item_cannot_be_taken_without_access` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_preparation.py::test_master_prompt_has_brief_and_persona` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_profile.py::test_premade_hero_chosen_by_player` | test_universal_hero_workshop.py |
| `tests/test_resident_positions.py::test_launch_places_legacy_residents_and_keeps_author_source_unchanged` | test_universal_launch.py |
| `tests/test_resolution_end_to_end.py::test_pipeline_safe_failure_price_commit_reconnect_standing_and_replay` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_rhythm.py::test_session_rhythm_and_epilogue` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_standing.py::test_encounter_by_place_knows_the_party_standing` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_find_lies_in_scene_and_may_bite` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_harm_to_npc_turns_to_revenge_at_once` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_help_to_faction_ripples_and_ripens_into_gratitude` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_inspiration_gives_advantage_once` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_manual_mode_keeps_the_world_quiet` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_secret_deed_changes_nothing_until_exposed` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_standing.py::test_watch_rolls_while_time_passes` | no universal equivalent (feature not wired to the universal runtime) |
| `tests/test_steps.py::test_combat_step_speed_dash_and_opportunity_attack` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_steps.py::test_step_goes_around_and_is_seen_on_the_map` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_steps.py::test_walls_are_full_barrier_for_steps_and_attacks` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_steps.py::test_world_conflict_on_step_answers_and_keeps_the_socket` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_tails.py::test_db_writable_while_model_reviews_hero` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_tails.py::test_diagnost_starting_gear_is_given_as_items` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_combat_without_enemies_is_refused` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_decide_rejects_json_calls_and_asks_for_native` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_decide_requires_native_calls_for_text_attempts` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_markdown_calls_are_detected_and_removed` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_markdown_calls_never_leak_into_stream` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_master_rejects_markdown_commands_and_regenerates_story` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_textcalls.py::test_narration_rewrites_markup_of_unregistered_place` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_tts.py::test_campaign_intro_voiced_in_parts` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_tts.py::test_master_turn_attaches_voice_when_tts_enabled` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_tts.py::test_master_turn_skips_voice_when_tts_disabled_in_campaign` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_tts.py::test_master_turn_uses_custom_tts_voice_from_campaign` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_tts.py::test_master_turn_voices_line_then_full_narration` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_tts.py::test_text_channel_without_line_skips_voice_line_request` | test_universal_narration_style.py / universal_story voice path |
| `tests/test_turn_efficiency.py::test_live_pair_stops_before_second_variant_if_reservation_wont_fit` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_turn_efficiency.py::test_manifest_contains_real_mechanical_cases` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_turn_efficiency.py::test_paired_scripted_turn` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_turn_efficiency.py::test_scripted_children_strip_inherited_live_mode` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_undeclared_cast.py::test_declared_spell_passes_the_guard` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_undeclared_cast.py::test_model_cannot_cast_undeclared_spell` | test_universal_action_pipeline.py / test_universal_resolution.py / test_universal_combat_playthrough.py (tool-call turn pipeline retired) |
| `tests/test_whisper.py::test_failed_whisper_explains_reason` | test_universal_lifecycle.py (answer_whispers) / test_universal_narration_style.py |
| `tests/test_whisper.py::test_turn_does_not_take_whisper` | test_universal_lifecycle.py (answer_whispers) / test_universal_narration_style.py |
| `tests/test_whisper.py::test_where_am_i_whisper_uses_actual_hero_location` | test_universal_lifecycle.py (answer_whispers) / test_universal_narration_style.py |
| `tests/test_whisper.py::test_whisper_answered_privately_without_turn` | test_universal_lifecycle.py (answer_whispers) / test_universal_narration_style.py |
| `tests/test_world_generation.py::test_turn_waits_for_generated_scene_and_describes_it` | test_universal_state.py / test_universal_resolution.py |
| `tests/test_world_transactions.py::test_crash_after_effects_resumes_narration_without_rerunning_tools` | test_universal_state.py / test_universal_resolution.py |
| `tests/test_world_transactions.py::test_narration_failure_keeps_actions_and_explicit_retry_uses_same_message` | test_universal_state.py / test_universal_resolution.py |
| `tests/test_world_transactions.py::test_turn_waits_for_preparation_before_narration` | test_universal_state.py / test_universal_resolution.py |
| `tests/test_world_transactions.py::test_world_conflict_replays_the_turn_once` | test_universal_state.py / test_universal_resolution.py |
| `tests/test_worlds.py::test_campaign_builder_offers_only_world_origins` | no universal equivalent (legacy world packs) |
| `tests/test_worlds.py::test_card_texts_come_from_world_pack` | no universal equivalent (legacy world packs) |
| `tests/test_worlds.py::test_echo_spells_flavor_and_renames` | no universal equivalent (legacy world packs) |
| `tests/test_worlds.py::test_threshold_gives_second_race_and_caste` | no universal equivalent (legacy world packs) |

## Removed after the single-chain migration reset and the pack retirement

Tests that were red before the worlds catalog work and that cover code or revisions which no longer exist.

| Retired test | Why |
| --- | --- |
| `tests/test_authoring_migrations.py` (`test_foundation_preserves_existing_game_and_children`, `test_geography_tables_upgrade_and_downgrade_keep_existing_rows`, `test_upgrade_repairs_ambiguous_0031`) | The chain is one universal initial migration (0001-0009); revisions 0030-0031 are gone. Boot and upgrade are covered by test_universal_boot.py / test_universal_upgrade.py |
| `tests/test_layout_store.py::test_sqlite_alembic_layout_phases_upgrade_and_downgrade`, `tests/test_map_migrations.py::test_location_map_migrations_match_metadata`, `tests/test_map_memory.py::test_map_memory_sqlite_upgrade_downgrade`, `tests/test_narrative_migrations.py::test_sqlite_alembic_narrative_foundation_upgrade_and_downgrade`, `tests/test_world_objects.py::test_sqlite_alembic_world_objects_upgrade_and_downgrade`, `tests/test_sfx.py::test_sfx_migration_*`, `tests/test_menu_music.py::test_menu_music_migration_is_reversible_for_existing_user`, `tests/test_llm_accounting.py::test_llm_call_migration_upgrade_and_downgrade`, `tests/test_llm_accounting.py::test_usage_coverage_migration_preserves_historical_unknown` | Each upgraded to a revision of the retired chain (0014-0026) |
| `tests/test_profile.py::test_library_hero_copied_into_campaign` | The 12-class `/api/me/character-options` builder is retired; copying a library hero is covered by the universal hero tests |
| `tests/test_module_intro.py::test_saved_intro_replaces_one_prepared_by_an_older_campaign` | Pack-module campaign intro; no universal equivalent (the session greeting is covered in test_universal_lifecycle.py) |
| `tests/test_layout_furnish.py::test_generated_furnishing_is_bound_to_area_cells` | Furnishing from a pack scene profile through `resolve_location`; the universal master does not use that tool path |

`tests/test_layout_quality.py` now checks the map quality of templates that have a preset. The draft story locations of the retired Echo pack have none.
