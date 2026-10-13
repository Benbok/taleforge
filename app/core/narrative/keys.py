"""Stable adaptation identity shared by receipts and durable jobs."""

import hashlib

from app.core.narrative.contracts import NarrativeSource


def narrative_key(source: NarrativeSource) -> str:
    return hashlib.sha256(source.source_key().encode("utf-8")).hexdigest()
