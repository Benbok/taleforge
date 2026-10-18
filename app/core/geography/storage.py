"""Persist a compiled geography draft inside the caller's transaction."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geography.contracts import (
    GeographyDraft,
    GeographyError,
    GeographyView,
    LinkDraft,
    NodeDraft,
    RouteEndpoint,
)
from app.db.models import GeographyLink, GeographyNode


async def assert_same_world(session: AsyncSession, campaign_id: str, *node_ids: str) -> None:
    """A route never connects nodes from different worlds."""
    rows = await session.scalars(select(GeographyNode.campaign_id).where(GeographyNode.id.in_(node_ids)))
    found = list(rows)
    if len(found) != len(set(node_ids)) or any(owner != campaign_id for owner in found):
        raise GeographyError("cross_world_route", *node_ids)


async def sync_geography(
    session: AsyncSession,
    campaign_id: str,
    draft: GeographyDraft,
    entity_by_ref: dict[str, str] | None = None,
) -> GeographyView:
    """Make the stored geography equal to ``draft``; the caller owns the transaction and revision guard."""
    entity_by_ref = entity_by_ref or {}
    existing = {
        n.ref: n for n in await session.scalars(select(GeographyNode).where(GeographyNode.campaign_id == campaign_id))
    }
    nodes: dict[str, GeographyNode] = {}
    for draft_node in draft.nodes:
        row = existing.pop(draft_node.ref, None)
        if row is None:
            row = GeographyNode(campaign_id=campaign_id, ref=draft_node.ref)
            session.add(row)
        row.kind, row.name, row.plot_ref = draft_node.kind, draft_node.name, draft_node.plot_ref
        row.entity_id = entity_by_ref.get(draft_node.ref) or row.entity_id
        nodes[draft_node.ref] = row
    for stale in existing.values():  # removed from the draft; links cascade
        await session.delete(stale)
    await session.flush()
    for draft_node in draft.nodes:
        nodes[draft_node.ref].parent_id = nodes[draft_node.parent_ref].id if draft_node.parent_ref else None
    old_links = {
        link.ref: link
        for link in await session.scalars(select(GeographyLink).where(GeographyLink.campaign_id == campaign_id))
    }
    for link in draft.links:
        row = old_links.pop(link.ref, None)
        if row is None:
            row = GeographyLink(campaign_id=campaign_id, ref=link.ref)
            session.add(row)
        row.from_node_id, row.to_node_id = nodes[link.source.node_ref].id, nodes[link.target.node_ref].id
        row.from_area_ref, row.to_area_ref = link.source.area_ref, link.target.area_ref
        row.bidirectional, row.kind, row.hidden = link.bidirectional, link.kind, link.hidden
        row.constraints = dict(link.constraints)
    for stale_link in old_links.values():
        await session.delete(stale_link)
    await session.flush()
    return await load_geography(session, campaign_id, start_ref=draft.start_ref)


async def load_geography(session: AsyncSession, campaign_id: str, start_ref: str | None = None) -> GeographyView:
    rows = list(
        await session.scalars(
            select(GeographyNode).where(GeographyNode.campaign_id == campaign_id).order_by(GeographyNode.ref)
        )
    )
    by_id = {n.id: n for n in rows}
    links = await session.scalars(
        select(GeographyLink).where(GeographyLink.campaign_id == campaign_id).order_by(GeographyLink.ref)
    )
    return GeographyView(
        nodes=tuple(
            NodeDraft(
                ref=n.ref,
                kind=n.kind,
                name=n.name,
                plot_ref=n.plot_ref,
                entity_id=n.entity_id,
                parent_ref=by_id[n.parent_id].ref if n.parent_id in by_id else None,
            )
            for n in rows
        ),
        links=tuple(
            LinkDraft(
                ref=link.ref,
                source=RouteEndpoint(node_ref=by_id[link.from_node_id].ref, area_ref=link.from_area_ref),
                target=RouteEndpoint(node_ref=by_id[link.to_node_id].ref, area_ref=link.to_area_ref),
                bidirectional=link.bidirectional,
                kind=link.kind,
                hidden=link.hidden,
                constraints=link.constraints or {},
            )
            for link in links
        ),
        start_ref=start_ref,
    )
