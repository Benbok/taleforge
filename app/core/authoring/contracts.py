"""Author API contracts. Public summaries never contain editor content."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import BriefIn, MasterIn


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AuthorProjectCreate(Contract):
    title: str = Field(min_length=1, max_length=128)
    brief: BriefIn = Field(default_factory=BriefIn)
    pack_id: str | None = None
    pack_version: str | None = None
    difficulty: Literal["easy", "normal", "hard", "deadly"] = "normal"
    master: MasterIn = Field(default_factory=MasterIn)
    budget_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class StageReceipt(Contract):
    job_id: str
    stage: str
    status: str
    source_revision: int


class ProjectSummary(Contract):
    id: str
    title: str
    draft_revision: int
    budget_usd: float | None = None


class ProjectDetail(ProjectSummary):
    brief: BriefIn = Field(default_factory=BriefIn)


class DraftPatch(Contract):
    operations: list[dict] = Field(default_factory=list, max_length=100)


class ValidationIssue(Contract):
    code: str
    object_ref: str | None = None
    related_refs: tuple[str, ...] = ()
    message: str = ""


class ValidationReport(Contract):
    source_revision: int
    source_digest: str
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()
    coverage: dict[str, int] = Field(default_factory=dict)


class AdventureBundle(Contract):
    schema_version: Literal[1] = 1


class InstanceOptions(Contract):
    name: str = Field(min_length=1, max_length=128)
    players: int = Field(default=4, ge=1, le=6)
    master: MasterIn = Field(default_factory=MasterIn)
    owner_plays: bool = True
    tts_enabled: bool = True


class StageStatus(Contract):
    stage: str
    status: str = "not_requested"
    job_id: str | None = None
    error_code: str | None = None
    source_revision: int | None = None


class PreparationView(Contract):
    project_id: str
    draft_revision: int
    stages: tuple[StageStatus, ...] = ()
    spent_usd: float = 0
    budget_usd: float | None = None
    cost_unknown: bool = False
    # Содержимое черновика отдаётся только редактору; режим без спойлеров его не включает.
    content: dict | None = None


class MaterializationReceipt(Contract):
    ref: str
    entity_id: str
    created: bool
    layout_ref: str | None = None


class PlacementSpec(Contract):
    """Where a key object or NPC starts: a concrete part of a location, optionally inside a container."""

    ref: str
    location_ref: str
    area_ref: str | None = None
    container_ref: str | None = None


class ItemSpec(Contract):
    ref: str
    template_id: str
    name: str = ""
    key: bool = False
    placement: PlacementSpec | None = None


class AreaStatus(Contract):
    ref: str
    entity_id: str | None = None
    status: str = "not_requested"  # not_requested | preparing | ready | blocked
    reasons: tuple[str, ...] = ()


class MaterializationReport(Contract):
    locations: tuple[AreaStatus, ...] = ()
    actors: tuple[AreaStatus, ...] = ()
    pending_rows: int = 0
    blocked_rows: int = 0

    @property
    def complete(self) -> bool:
        everything = (*self.locations, *self.actors)
        return bool(everything) and all(a.status == "ready" for a in everything) and not self.pending_rows


class LaunchReceipt(Contract):
    campaign_id: str
    adventure_version_id: str
    url: str
