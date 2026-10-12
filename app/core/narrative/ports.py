"""Protocol ports for isolated narrative components.

Ports define the boundary between the pure narrative domain and infrastructure adapters.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    BoundaryRecord,
    NarrativeSnapshot,
    SnapshotRequest,
    Violation,
    WorkClaim,
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

    async def apply(
        self, proposal: AdaptationProposal, *, claim: WorkClaim | None = None
    ) -> AdaptationResult: ...


@runtime_checkable
class NarrativeJobs(Protocol):
    """Port for durable director job queue, lease management, and recovery."""

    async def enqueue(self, boundary: BoundaryRecord) -> str: ...

    async def claim(self, now: datetime, *, campaign_id: str | None = None) -> WorkClaim | None: ...

    async def reserve_call(self, claim: WorkClaim, now: datetime) -> WorkClaim | None: ...

    async def renew(self, claim: WorkClaim, now: datetime) -> bool: ...

    async def save_draft(
        self, claim: WorkClaim, proposal: AdaptationProposal, now: datetime | None = None
    ) -> None: ...

    async def finish(
        self,
        claim: WorkClaim,
        result: AdaptationResult,
        now: datetime | None = None,
        *,
        feedback: tuple[Violation, ...] | None = None,
    ) -> None: ...

    async def resnapshot(self, claim: WorkClaim, now: datetime) -> WorkClaim | None: ...

