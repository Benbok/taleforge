"""Protocol ports for isolated narrative components.

Ports define the boundary between the pure narrative domain and infrastructure adapters.
"""

from typing import Protocol, runtime_checkable

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    NarrativeSnapshot,
    SnapshotRequest,
)


@runtime_checkable
class NarrativeReader(Protocol):
    """Port for loading verified bounded narrative snapshots from storage."""

    async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot: ...


@runtime_checkable
class NarrativeAuthor(Protocol):
    """Port for generating structured narrative adaptation proposals."""

    async def propose(self, snapshot: NarrativeSnapshot) -> AdaptationProposal: ...


@runtime_checkable
class NarrativeApplier(Protocol):
    """Port for validating and executing adaptation proposals atomically."""

    async def apply(self, proposal: AdaptationProposal) -> AdaptationResult: ...
