"""Create an independent game from a published adventure version: fresh ids, fresh runtime state."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import plot as plot_module
from app.core.authoring.contracts import AdventureBundle, InstanceOptions, LaunchReceipt
from app.core.authoring.references import find_leaks, restore_plot, restore_state
from app.core.campaigns import Conflict, NotFound, create_world
from app.db.models import (
    AdventureVersion,
    Campaign,
    CampaignPlan,
    CampaignSecret,
    ContentPack,
    Entity,
    GeographyLink,
    GeographyNode,
    PlotAnchorBinding,
    User,
    WorldGenerationState,
    new_id,
)

LAUNCH_FLAGS = ("scene_generation", "scene_generation_llm", "location_layouts")


def _digest(version_id: str, options: InstanceOptions) -> str:
    body = json.dumps({"v": version_id, "o": options.model_dump(mode="json")}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


async def instantiate_adventure(
    session: AsyncSession, owner: User, version: AdventureVersion, options: InstanceOptions, request_key: str
) -> LaunchReceipt:
    digest = _digest(version.id, options)
    same = await session.scalar(
        select(Campaign).where(Campaign.owner_id == owner.id, Campaign.launch_request_key == request_key)
    )
    if same is not None:
        if same.launch_input_digest != digest:
            raise Conflict("request_key уже использован для другого запуска")
        return LaunchReceipt(campaign_id=same.id, adventure_version_id=version.id, url=f"/c/{same.id}")
    bundle = AdventureBundle.model_validate(version.bundle)
    meta = bundle.meta
    pack = None
    if meta.get("pack_id"):
        pack = await session.get(ContentPack, (meta["pack_id"], meta["pack_version"]))
        if pack is None:
            raise NotFound("пакет контента версии недоступен")
    # Hero and master settings come from the launch options, never from the author's workbench.
    flags = {k: v for k, v in (meta.get("flags") or {}).items() if k in LAUNCH_FLAGS}
    game = await create_world(
        session,
        owner,
        name=options.name,
        ruleset_version=meta["ruleset_version"],
        pack=pack,
        difficulty=meta.get("difficulty") or "normal",
        players=options.players,
        master=options.master.model_dump(exclude_none=True),
        public_intro=meta.get("public_intro") or "",
        settings={**flags, "tts_enabled": options.tts_enabled},
        owner_plays=options.owner_plays,
        brief=bundle.brief,
        purpose="game",
    )
    game.content_chain = list(meta.get("content_chain") or [])  # the version's pinned content, not today's latest
    game.adventure_version_id = version.id
    game.launch_request_key = request_key
    game.launch_input_digest = digest

    ids = {e.ref: new_id("en") for e in bundle.entities}
    gen_ids = {g.ref: new_id("wg") for g in bundle.generations}
    all_ids = {**ids, **gen_ids}
    for e in bundle.entities:
        session.add(
            Entity(
                id=ids[e.ref],
                campaign_id=game.id,
                kind=e.kind,
                name=e.name,
                template_id=e.template_id,
                description=restore_plot({"d": e.description}, ids)["d"],
                zone=e.zone,
                location_id=ids.get(e.location or ""),
                state=restore_state(e.state, all_ids),
            )
        )
    await session.flush()  # entities first: generation rows and anchors point at them
    now = datetime.now(UTC)
    for g in bundle.generations:
        session.add(
            WorldGenerationState(
                id=gen_ids[g.ref],
                campaign_id=game.id,
                target_entity_id=ids[g.target],
                phase=g.phase,
                status=g.status,
                quality=g.quality,
                revision=0,
                attempt_count=0,
                generator_version=g.generator_version,
                profile_ref=g.profile_ref,
                source_versions=g.source_versions,
                context_digest=g.context_digest,
                reservation=_restore_blob(g.reservation, all_ids),
                seed=g.seed,
                result_digest=g.result_digest,
                completed_at=now if g.status == "ready" else None,
                llm_attempt_count=0,
                conflict_count=0,
                result_manifest=_restore_blob(g.result_manifest, all_ids) if g.result_manifest is not None else None,
            )
        )
    for a in bundle.anchors:
        session.add(
            PlotAnchorBinding(
                campaign_id=game.id,
                anchor_id=a.anchor_id,
                plot_ref=a.plot_ref,
                holder_entity_id=ids.get(a.holder or ""),
                target_location_id=ids.get(a.target_location or ""),
                state=a.state,
                source_snapshot=_restore_blob(a.source_snapshot, all_ids),
                replacement_ref=a.replacement_ref,
            )
        )
    nodes: dict[str, GeographyNode] = {}
    for n in bundle.geography_nodes:
        nodes[n.ref] = GeographyNode(
            campaign_id=game.id,
            ref=n.ref,
            kind=n.kind,
            name=n.name,
            plot_ref=n.plot_ref,
            entity_id=ids.get(n.entity or ""),
        )
        session.add(nodes[n.ref])
    await session.flush()
    for n in bundle.geography_nodes:
        nodes[n.ref].parent_id = nodes[n.parent_ref].id if n.parent_ref else None
    for link in bundle.geography_links:
        session.add(
            GeographyLink(
                campaign_id=game.id,
                ref=link.ref,
                from_node_id=nodes[link.from_node].id,
                to_node_id=nodes[link.to_node].id,
                from_area_ref=link.from_area_ref,
                to_area_ref=link.to_area_ref,
                bidirectional=link.bidirectional,
                kind=link.kind,
                state=link.state,
                hidden=link.hidden,
                constraints=link.constraints,
            )
        )
    plan = restore_plot(bundle.plot, ids)
    secret = await session.get(CampaignSecret, game.id)
    secret.plot = plan
    secret.setting = _restore_blob(bundle.setting, all_ids)
    if plot_module.has_plan(plan):
        session.add(CampaignPlan(campaign_id=game.id, version=1, content=plan, note="published adventure"))
        settings = dict(game.settings or {})
        settings["plan"] = {"status": "ready", "version": 1, "error": None, "updated_at": now.isoformat()}
        settings["poster"] = plot_module.poster(plan)
        game.settings = settings
    await session.flush()
    foreign = find_leaks(
        {"plot": plan, "setting": secret.setting}, {i for i in (*ids, *gen_ids)}
    )  # logical refs must not survive into the new world
    if foreign:
        raise Conflict(f"unresolved_ref: {foreign[0]}")
    return LaunchReceipt(campaign_id=game.id, adventure_version_id=version.id, url=f"/c/{game.id}")


def _restore_blob(value, ids: dict[str, str]):
    from app.core.authoring.references import remap

    return remap(value, ids)
