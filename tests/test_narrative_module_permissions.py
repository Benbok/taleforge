"""Tests for module narrative permissions parsing and validation (Task 18)."""

import pytest

from app.core.modules import parse_narrative_permissions, validate_used_fact_refs
from app.core.narrative.contracts import (
    FactRef,
    NarrativePermissions,
    NarrativeSnapshot,
    SnapshotRef,
)
from tests.narrative_helpers import fact, snapshot


def test_missing_metadata_returns_strict_permissions():
    """Missing or empty narrative permissions metadata produces strict permissions."""
    perms1 = parse_narrative_permissions({}, catalog=None)
    assert perms1.anchors == ()
    assert perms1.mutable_fact_addresses == ()
    assert perms1.operation_kinds == ()
    assert perms1.supplement_scopes == ()

    perms2 = parse_narrative_permissions({"other_key": 123}, catalog=None)
    assert perms2 == perms1


def test_valid_metadata_parses_permissions():
    """Valid metadata schema_version=1 parses all explicit permission lists."""
    module_data = {
        "narrative_permissions": {
            "schema_version": 1,
            "anchors": ["place.crypt:core", "npc.inquisitor:identity"],
            "mutable_fact_addresses": ["module:npc.scout:motivation"],
            "operation_kinds": ["revise_draft_fact", "introduce_actor"],
            "supplement_scopes": ["future"],
        }
    }
    perms = parse_narrative_permissions(module_data, catalog=None)
    assert perms.anchors == ("place.crypt:core", "npc.inquisitor:identity")
    assert perms.mutable_fact_addresses == ("module:npc.scout:motivation",)
    assert perms.operation_kinds == ("revise_draft_fact", "introduce_actor")
    assert perms.supplement_scopes == ("future",)


def test_unsupported_schema_version_rejected():
    """Unsupported metadata schema_version raises ValueError."""
    module_data = {
        "narrative_permissions": {
            "schema_version": 99,
            "anchors": [],
        }
    }
    with pytest.raises(ValueError, match="schema_version"):
        parse_narrative_permissions(module_data, catalog=None)


def test_invalid_fact_address_rejected():
    """Malformed mutable fact addresses are rejected during parsing."""
    module_data = {
        "narrative_permissions": {
            "schema_version": 1,
            "mutable_fact_addresses": ["malformed_address_without_colons"],
        }
    }
    with pytest.raises(ValueError, match="address"):
        parse_narrative_permissions(module_data, catalog=None)


def test_validate_used_fact_refs():
    """validate_used_fact_refs filters and returns validated tuple of FactRefs."""
    f1 = fact(ref=FactRef(
        campaign_id="c1",
        namespace="module",
        subject_id="npc.scout",
        key="motivation",
        version=1,
        snapshot_ref=SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.scout:motivation"),
    ))
    snap = snapshot(facts=(f1,))

    valid_ref = f1.ref
    unrelated_ref = FactRef(
        campaign_id="other_campaign",
        namespace="module",
        subject_id="npc.stranger",
        key="role",
        version=1,
        snapshot_ref=SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.stranger:role"),
    )

    validated = validate_used_fact_refs(snap, (valid_ref, unrelated_ref))
    assert valid_ref in validated
    assert unrelated_ref not in validated
