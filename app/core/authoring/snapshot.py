"""Typed adventure snapshot: logical refs instead of workspace ids, no player or runtime state."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authoring.contracts import (
    AdventureBundle,
    BundleAnchor,
    BundleEntity,
    BundleGeneration,
    BundleGeographyLink,
    BundleGeographyNode,
    ValidationIssue,
)
from app.core.authoring.references import (
    RefMap,
    UnsupportedReference,
    adapt_plot,
    adapt_state,
    adapt_text,
    find_leaks,
    remap,
)
from app.db.models import (
    AuthorProject,
    Campaign,
    CampaignSecret,
    Entity,
    GeographyLink,
    GeographyNode,
    PlotAnchorBinding,
    WorldGenerationState,
)

CAMPAIGN_FIELDS = (
    "name", "ruleset_id", "ruleset_version", "pack_id", "pack_version", "difficulty", "party_size_recommended",
    "public_intro", "content_chain",
)  # fmt: skip
SETTING_FLAGS = ("narrative_mode", "scene_generation", "scene_generation_llm", "location_layouts")


class SnapshotError(Exception):
    def __init__(self, code: str, where: str = ""):
        super().__init__(f"{code}: {where}")
        self.code = code
        self.where = where


async def export_bundle(session: AsyncSession, project: AuthorProject) -> AdventureBundle:
    cid = project.workspace_campaign_id
    world = await session.get(Campaign, cid)
    secret = await session.get(CampaignSecret, cid)
    entities = list(
        await session.scalars(
            select(Entity).where(Entity.campaign_id == cid).order_by(Entity.kind, Entity.name, Entity.id)
        )
    )
    rows = list(
        await session.scalars(
            select(WorldGenerationState)
            .where(WorldGenerationState.campaign_id == cid)
            .order_by(WorldGenerationState.phase, WorldGenerationState.target_entity_id)
        )
    )
    refs = RefMap()
    for n, entity in enumerate(entities, 1):
        refs.entities[entity.id] = f"e{n:04d}"
    for n, row in enumerate(rows, 1):
        refs.generations[row.id] = f"g{n:04d}"
    ids = {**refs.entities, **refs.generations}

    try:
        bundle_entities = [
            BundleEntity(
                ref=refs.entities[e.id],
                kind=e.kind,
                name=e.name,
                template_id=e.template_id,
                description=adapt_text(e.description, refs),
                zone=e.zone,
                location=refs.entity(e.location_id),
                state=adapt_state(e.state or {}, refs),
            )
            for e in entities
        ]
    except UnsupportedReference as exc:
        raise SnapshotError("unsupported_reference", exc.where) from exc
    generations = [
        BundleGeneration(
            ref=refs.generations[r.id],
            target=refs.entities.get(r.target_entity_id, r.target_entity_id),
            phase=r.phase,
            status=r.status,
            quality=r.quality,
            generator_version=r.generator_version,
            profile_ref=r.profile_ref,
            source_versions=r.source_versions or {},
            context_digest=r.context_digest,
            reservation=remap(r.reservation or {}, ids),
            seed=r.seed,
            result_digest=r.result_digest,
            result_manifest=remap(r.result_manifest, ids) if r.result_manifest is not None else None,
        )
        for r in rows
    ]
    anchors = [
        BundleAnchor(
            anchor_id=a.anchor_id,
            plot_ref=a.plot_ref,
            holder=refs.entity(a.holder_entity_id),
            target_location=refs.entity(a.target_location_id),
            state=a.state,
            source_snapshot=remap(a.source_snapshot or {}, ids),
            replacement_ref=a.replacement_ref,
        )
        for a in await session.scalars(
            select(PlotAnchorBinding).where(PlotAnchorBinding.campaign_id == cid).order_by(PlotAnchorBinding.anchor_id)
        )
    ]
    nodes = list(
        await session.scalars(select(GeographyNode).where(GeographyNode.campaign_id == cid).order_by(GeographyNode.ref))
    )
    by_id = {n.id: n for n in nodes}
    links = list(
        await session.scalars(select(GeographyLink).where(GeographyLink.campaign_id == cid).order_by(GeographyLink.ref))
    )
    plot = adapt_plot((secret.plot if secret else None) or {}, refs)
    settings = world.settings or {}
    bundle = AdventureBundle(
        meta={
            **{f: getattr(world, f) for f in CAMPAIGN_FIELDS},
            "flags": {k: settings[k] for k in SETTING_FLAGS if k in settings},
            "source_revision": project.draft_revision,
        },
        brief=world.brief or {},
        plot=plot,
        setting=remap((secret.setting if secret else None) or {}, ids),
        entities=bundle_entities,
        generations=generations,
        anchors=anchors,
        geography_nodes=[
            BundleGeographyNode(
                ref=n.ref,
                kind=n.kind,
                name=n.name,
                plot_ref=n.plot_ref,
                parent_ref=by_id[n.parent_id].ref if n.parent_id in by_id else None,
                entity=refs.entity(n.entity_id),
            )
            for n in nodes
        ],
        geography_links=[
            BundleGeographyLink(
                ref=lk.ref,
                from_node=by_id[lk.from_node_id].ref,
                to_node=by_id[lk.to_node_id].ref,
                from_area_ref=lk.from_area_ref,
                to_area_ref=lk.to_area_ref,
                bidirectional=lk.bidirectional,
                kind=lk.kind,
                state=lk.state,
                hidden=lk.hidden,
                constraints=lk.constraints or {},
            )
            for lk in links
        ],
    )
    leaks = find_leaks(bundle.model_dump(mode="json"), refs.known())
    if leaks:
        raise SnapshotError("unsupported_reference", leaks[0])
    return bundle


def validate_bundle(bundle: AdventureBundle) -> tuple[ValidationIssue, ...]:
    """Every reference resolves inside the bundle; nothing points at a workspace id."""
    issues: list[ValidationIssue] = []
    entity_refs = {e.ref for e in bundle.entities}
    gen_refs = {g.ref for g in bundle.generations}

    def need(ok: bool, code: str, ref: str) -> None:
        if not ok:
            issues.append(ValidationIssue(code=code, object_ref=ref))

    for e in bundle.entities:
        need(e.location is None or e.location in entity_refs, "unresolved_ref", e.ref)
        root = (e.state.get("complex") or {}).get("root_id")
        need(root is None or root in entity_refs, "unresolved_ref", e.ref)
        for area_ref, target in (e.state.get("areas") or {}).items():
            need(target in entity_refs, "unresolved_ref", f"{e.ref}/{area_ref}")
        gen = (e.state.get("world_object") or {}).get("generation_ref")
        need(gen is None or gen in gen_refs, "unresolved_ref", e.ref)
    for g in bundle.generations:
        need(g.target in entity_refs, "unresolved_ref", g.ref)
    for a in bundle.anchors:
        need(a.holder is None or a.holder in entity_refs, "unresolved_ref", a.anchor_id)
        need(a.target_location is None or a.target_location in entity_refs, "unresolved_ref", a.anchor_id)
    node_refs = {n.ref for n in bundle.geography_nodes}
    for n in bundle.geography_nodes:
        need(n.entity is None or n.entity in entity_refs, "unresolved_ref", n.ref)
        need(n.parent_ref is None or n.parent_ref in node_refs, "unresolved_ref", n.ref)
    for link in bundle.geography_links:
        need(link.from_node in node_refs and link.to_node in node_refs, "unresolved_route", link.ref)
    for loc in bundle.plot.get("locations") or []:
        need(loc.get("entity_id") is None or loc["entity_id"] in entity_refs, "unresolved_ref", loc.get("id", ""))
    return tuple(issues)
