"""Author API contracts. Public summaries never contain editor content."""

from typing import Annotated, Literal

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
    # publication: draft (never published) | published (the current draft is a version) | changed (edited after)
    status: Literal["draft", "published", "changed"] = "draft"
    latest_version: int | None = None


class ProjectDetail(ProjectSummary):
    brief: BriefIn = Field(default_factory=BriefIn)


Ref = Field(min_length=1, max_length=64)
Text = Field(max_length=2000)


class SetLore(Contract):
    op: Literal["set_lore"]
    fields: dict[str, str | list[str] | list[dict[str, str]]]


class UpdatePlotObject(Contract):
    op: Literal["update_plot_object"]
    ref: str = Ref
    fields: dict[str, str]


class SetPlotText(Contract):
    op: Literal["set_plot_text"]
    fields: dict[str, str]


class UpdateItem(Contract):
    op: Literal["update_item"]
    ref: str = Ref
    fields: dict[str, str]


class SetPlacement(Contract):
    op: Literal["set_placement"]
    ref: str = Ref
    location_ref: str = Ref
    area_ref: str | None = None
    container_ref: str | None = None


class UpsertRoute(Contract):
    op: Literal["upsert_route"]
    ref: str = Ref
    source: str = Field(alias="from", min_length=1, max_length=130)
    target: str = Field(alias="to", min_length=1, max_length=130)
    bidirectional: bool = True
    hidden: bool = False


class RemoveObject(Contract):
    op: Literal["remove_object"]
    ref: str = Ref


class EditMap(Contract):
    op: Literal["edit_map"]
    location_ref: str = Ref
    spatial: dict


PatchOp = Annotated[
    SetLore | SetPlotText | UpdatePlotObject | UpdateItem | SetPlacement | UpsertRoute | RemoveObject | EditMap,
    Field(discriminator="op"),
]


class DraftPatch(Contract):
    operations: list[PatchOp] = Field(default_factory=list, max_length=100)


class ResultRef(Contract):
    kind: str  # layout | geometry | placement | route_port | stage
    ref: str


class EditResult(Contract):
    applied: bool
    draft_revision: int
    affected: tuple[ResultRef, ...] = ()
    blocked_by: tuple[ResultRef, ...] = ()  # objects that still use a removed one
    event_id: str | None = None


class EditRequest(Contract):
    instruction: str = Field(min_length=1, max_length=2000)
    base_revision: int


class EditProposal(Contract):
    base_revision: int
    patch: DraftPatch
    affected: tuple[ResultRef, ...] = ()
    summary: str = ""


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


class BundleEntity(Contract):
    ref: str
    kind: str
    name: str
    template_id: str | None = None
    description: str = ""
    zone: str | None = None
    location: str | None = None  # entity ref, never a workspace id
    state: dict = Field(default_factory=dict)


class BundleGeneration(Contract):
    ref: str
    target: str
    phase: str
    status: str
    quality: str | None = None
    generator_version: str | None = None
    profile_ref: str | None = None
    source_versions: dict = Field(default_factory=dict)
    context_digest: str | None = None
    reservation: dict = Field(default_factory=dict)
    seed: int | None = None
    result_digest: str | None = None
    result_manifest: dict | None = None


class BundleAnchor(Contract):
    anchor_id: str
    plot_ref: str
    holder: str | None = None
    target_location: str | None = None
    state: str
    source_snapshot: dict = Field(default_factory=dict)
    replacement_ref: str | None = None


class BundleGeographyNode(Contract):
    ref: str
    kind: str
    name: str
    plot_ref: str | None = None
    parent_ref: str | None = None
    entity: str | None = None


class BundleGeographyLink(Contract):
    ref: str
    from_node: str
    to_node: str
    from_area_ref: str | None = None
    to_area_ref: str | None = None
    bidirectional: bool = True
    kind: str = "path"
    state: str = "open"
    hidden: bool = False
    constraints: dict = Field(default_factory=dict)


class AdventureBundle(Contract):
    schema_version: Literal[1] = 1
    meta: dict = Field(default_factory=dict)
    brief: dict = Field(default_factory=dict)
    plot: dict = Field(default_factory=dict)
    setting: dict = Field(default_factory=dict)
    entities: list[BundleEntity] = Field(default_factory=list)
    generations: list[BundleGeneration] = Field(default_factory=list)
    anchors: list[BundleAnchor] = Field(default_factory=list)
    geography_nodes: list[BundleGeographyNode] = Field(default_factory=list)
    geography_links: list[BundleGeographyLink] = Field(default_factory=list)


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
    stale: tuple[str, ...] = ()  # results the author changed under; publication stays blocked until resolved
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
    container: bool = False  # an authored container; other items may name it in container_ref
    placement: PlacementSpec | None = None


class AreaStatus(Contract):
    ref: str
    entity_id: str | None = None
    status: str = "not_requested"  # not_requested | preparing | ready | blocked
    reasons: tuple[str, ...] = ()


class MaterializationReport(Contract):
    locations: tuple[AreaStatus, ...] = ()
    actors: tuple[AreaStatus, ...] = ()
    items: tuple[AreaStatus, ...] = ()
    pending_rows: int = 0
    blocked_rows: int = 0

    @property
    def complete(self) -> bool:
        everything = (*self.locations, *self.actors, *self.items)
        return bool(everything) and all(a.status == "ready" for a in everything) and not self.pending_rows


class PrepareRequest(Contract):
    stage: str
    target_ref: str | None = None
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class EditsRequest(Contract):
    patch: DraftPatch
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)


class AcceptStaleRequest(Contract):
    refs: list[str] = Field(min_length=1, max_length=50)
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)


class PublishRequest(Contract):
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)


class JobOut(Contract):
    id: str
    stage: str
    status: str
    error_code: str | None = None
    source_revision: int
    attempt_count: int = 0


class ValidationSummary(Contract):
    source_revision: int
    errors: int
    warnings: int
    current: bool  # made for the current draft revision; a later edit makes it outdated


class PublishedBrief(Contract):
    id: str
    version: int
    source_revision: int
    published_at: str


class ProjectView(Contract):
    """Summary and full are different DTOs: the spoiler-free one has no ``content`` field at all."""

    project: ProjectDetail
    preparation: PreparationView
    validation: ValidationSummary | None = None
    published: list[PublishedBrief] = Field(default_factory=list)  # newest first


class VersionOut(Contract):
    id: str
    project_id: str
    version: int
    source_revision: int
    public_summary: dict
    published_at: str


class AuthorMapArea(Contract):
    area_ref: str
    name: str
    sketch: dict
    ports: dict = Field(default_factory=dict)


class AuthorMapOut(Contract):
    location_ref: str
    name: str
    areas: list[AuthorMapArea]
    layout_quality: str | None = None  # normal: planned by the model; fallback: deterministic template


class OverviewArea(Contract):
    area_ref: str
    name: str
    entry: bool = False
    secret: bool = False
    npcs: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class OverviewPassage(Contract):
    """A passage inside one place, between two of its areas, or out of the place (``to_area`` is None)."""

    from_area: str
    to_area: str | None = None
    name: str = ""
    kind: str = ""
    hidden: bool = False


class OverviewLocation(Contract):
    ref: str
    name: str
    region: str | None = None
    areas: list[OverviewArea] = Field(default_factory=list)
    passages: list[OverviewPassage] = Field(default_factory=list)


class OverviewRoute(Contract):
    ref: str
    from_ref: str
    from_area: str | None = None
    to_ref: str
    to_area: str | None = None
    bidirectional: bool = True
    hidden: bool = False


class WorldOverview(Contract):
    locations: list[OverviewLocation] = Field(default_factory=list)
    routes: list[OverviewRoute] = Field(default_factory=list)
    regions: dict[str, str] = Field(default_factory=dict)


class IntroVoiceOut(Contract):
    id: str
    duration: float | None = None


class IntroOut(Contract):
    text: str = ""
    voices: list[IntroVoiceOut] = Field(default_factory=list)
    provider: str | None = None
    voice: str | None = None
    parts: int = 0
    current: bool = False  # written for the current plot version
    providers: dict[str, bool] = Field(default_factory=dict)  # source -> available on this server


class IntroRequest(Contract):
    provider: Literal["voicestudio", "gemini", "none"]
    voice: str | None = Field(default=None, max_length=128)
    rewrite: bool = True  # write a new text
    voiced: bool = True  # voice it; rewrite without voice changes only the text
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)


class IntroTextRequest(Contract):
    text: str = Field(min_length=1, max_length=8000)
    expected_revision: int


class LaunchRequest(Contract):
    options: InstanceOptions
    request_key: str = Field(min_length=1, max_length=128)


class ImportPlotRequest(Contract):
    plan: dict
    expected_revision: int
    request_key: str = Field(min_length=1, max_length=128)


class ImportResult(Contract):
    plan_version_id: str
    cleared_entities: int = 0
    source: str = "import"


class StageTask(Contract):
    stage: str
    system: str
    user: str
    schema_: dict = Field(alias="schema")
    how: str


class LaunchReceipt(Contract):
    campaign_id: str
    adventure_version_id: str
    url: str
