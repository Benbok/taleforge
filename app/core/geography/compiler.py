"""Pure plan -> geography conversion. No database access and no materialization."""

from app.core.geography.contracts import (
    GeographyDraft,
    GeographyError,
    LinkDraft,
    NodeDraft,
    RouteEndpoint,
)


def parse_endpoint(raw: str) -> RouteEndpoint:
    """``loc_cave/part_crawl`` names a concrete part; a bare node ref means no explicit part (legacy)."""
    node, _, area = str(raw).partition("/")
    if not node:
        raise GeographyError("bad_endpoint", str(raw))
    return RouteEndpoint(node_ref=node, area_ref=area or None)


def compile_plan(plan: dict) -> GeographyDraft:
    nodes: list[NodeDraft] = []
    parts: dict[str, set[str]] = {}
    for region in plan.get("regions") or []:
        nodes.append(NodeDraft(ref=region["id"], kind="region", name=region["name"], parent_ref=region.get("parent")))
    for loc in plan.get("locations") or []:
        nodes.append(
            NodeDraft(
                ref=loc["id"],
                kind="location",
                name=loc["name"],
                plot_ref=loc["id"],
                parent_ref=loc.get("region"),
            )
        )
        spatial = loc.get("spatial") or {}
        if spatial.get("parts"):
            parts[loc["id"]] = {p["ref"] for p in spatial["parts"]}
    refs = [n.ref for n in nodes]
    dup = sorted({r for r in refs if refs.count(r) > 1})
    if dup:
        raise GeographyError("duplicate_ref", *dup)
    known = set(refs)
    parents = {n.ref: n.parent_ref for n in nodes}
    for ref, parent in parents.items():
        if parent is not None and parent not in known:
            raise GeographyError("unknown_parent", ref, parent)
    for ref in parents:
        seen, cur = {ref}, parents[ref]
        while cur is not None:
            if cur in seen:
                raise GeographyError("parent_cycle", ref)
            seen.add(cur)
            cur = parents.get(cur)

    links: list[LinkDraft] = []
    pairs: set[frozenset[str]] = set()
    for loc in plan.get("locations") or []:
        for other in (loc.get("spatial") or {}).get("links") or []:
            pair = frozenset((loc["id"], other))
            # A legacy link from one side means mutual adjacency; the reverse link is not a second route.
            if other not in known or other == loc["id"] or pair in pairs:
                continue
            pairs.add(pair)
            a, b = sorted(pair)
            links.append(
                LinkDraft(ref=f"legacy:{a}:{b}", source=RouteEndpoint(node_ref=a), target=RouteEndpoint(node_ref=b))
            )
    for route in plan.get("routes") or []:
        link = LinkDraft(
            ref=route["ref"],
            source=parse_endpoint(route["from"]),
            target=parse_endpoint(route["to"]),
            bidirectional=bool(route.get("bidirectional", True)),
            kind=route.get("kind", "path"),
            hidden=bool(route.get("hidden", False)),
            constraints=dict(route.get("constraints") or {}),
        )
        links.append(link)
    link_refs = [link.ref for link in links]
    dup_links = sorted({r for r in link_refs if link_refs.count(r) > 1})
    if dup_links:
        raise GeographyError("duplicate_route_ref", *dup_links)
    for link in links:
        for end in (link.source, link.target):
            if end.node_ref not in known:
                raise GeographyError("unknown_node", link.ref, end.node_ref)
            if end.area_ref is not None and end.node_ref in parts and end.area_ref not in parts[end.node_ref]:
                raise GeographyError("unknown_part", link.ref, f"{end.node_ref}/{end.area_ref}")
        if link.source == link.target:
            raise GeographyError("self_route", link.ref)
    start = plan.get("start_ref") or next((n.ref for n in nodes if n.kind == "location"), None)
    if start is not None and start not in known:
        raise GeographyError("unknown_start", start)
    return GeographyDraft(nodes=tuple(nodes), links=tuple(links), start_ref=start)
