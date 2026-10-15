# LLM turn efficiency: implementation and verification

## Task 1: telemetry

Baseline from the Docker PostgreSQL database, read-only, before behavior changes:
144 calls, $0.484081 stored estimate; 3,492,007 prompt tokens and 19,603 output tokens.
16 done turns, 1 failed. Cutoff: 2026-10-15T14:05:08.104446+00:00 (17:05:08 Moscow).
Matches the design baseline exactly. All 144 historical rows have unknown cache and price coverage;
the stored cost total is not evidence of full price coverage. Parse without turn_id stays visible.

Automated verification: 21 telemetry/report tests passed; 50 focused regression tests passed.
SQLite migration upgrade/downgrade passed, preserving historical NULL fields.
PostgreSQL 16 migration 0031 upgrade/downgrade passed in the isolated database
`taleforge_llm_coverage_test_20261015`, preserving the historical row.
The live game database was not migrated or restarted; no paid requests were made.

Pre-existing lint issues: five E501 lines in app/core/map_memory.py and one import ordering issue
in app/core/world_tx.py. No changes made to those unrelated files.

## Human verification

Not performed. Live model cost savings and prose quality remain unmeasured.
