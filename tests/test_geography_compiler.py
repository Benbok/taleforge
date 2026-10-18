import asyncio

import pytest

from app.core.authoring.contracts import AuthorProjectCreate
from app.core.authoring.projects import create_project
from app.core.geography.compiler import compile_plan
from app.core.geography.contracts import GeographyError
from app.core.geography.storage import assert_same_world, load_geography, sync_geography
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author


def loc(ref, name, parts=("main",), links=(), region=None):
    return {
        "id": ref,
        "name": name,
        "region": region,
        "spatial": {"parts": [{"ref": p} for p in parts], "links": list(links)},
    }


def plan(**extra):
    return {
        "regions": [{"id": "reg_hills", "name": "Холмы"}, {"id": "reg_deep", "name": "Глубина", "parent": "reg_hills"}],
        "locations": [
            loc("loc_cave", "Пещера", ("main", "part_fall", "part_crawl"), links=("loc_tunnels",), region="reg_hills"),
            loc("loc_tunnels", "Гладкие туннели", ("part_junction",), region="reg_deep"),
            loc("loc_hall", "Зал Ничто", region="reg_deep"),
        ],
        **extra,
    }


def test_three_regions_locations_and_one_legacy_route():
    draft = compile_plan(plan())
    assert {n.ref: n.kind for n in draft.nodes} == {
        "reg_hills": "region",
        "reg_deep": "region",
        "loc_cave": "location",
        "loc_tunnels": "location",
        "loc_hall": "location",
    }
    assert draft.start_ref == "loc_cave"
    assert [(link.ref, link.bidirectional) for link in draft.links] == [("legacy:loc_cave:loc_tunnels", True)]


def test_reverse_legacy_link_does_not_make_second_route():
    p = plan()
    p["locations"][1]["spatial"]["links"] = ["loc_cave"]
    assert len(compile_plan(p).links) == 1


def test_explicit_one_way_route_between_parts_and_parallel_routes():
    p = plan(
        routes=[
            {
                "ref": "r_crawl",
                "from": "loc_cave/part_crawl",
                "to": "loc_tunnels/part_junction",
                "bidirectional": False,
            },
            {"ref": "r_second", "from": "loc_cave/part_fall", "to": "loc_tunnels/part_junction"},
        ]
    )
    links = {link.ref: link for link in compile_plan(p).links}
    assert links["r_crawl"].bidirectional is False
    assert links["r_crawl"].source.area_ref == "part_crawl"
    assert {"r_crawl", "r_second", "legacy:loc_cave:loc_tunnels"} == set(links)


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"routes": [{"ref": "r", "from": "loc_cave/nope", "to": "loc_tunnels/part_junction"}]}, "unknown_part"),
        ({"routes": [{"ref": "r", "from": "loc_cave/main", "to": "loc_missing/main"}]}, "unknown_node"),
        (
            {
                "routes": [
                    {"ref": "r", "from": "loc_cave/main", "to": "loc_hall/main"},
                    {"ref": "r", "from": "loc_cave/part_fall", "to": "loc_hall/main"},
                ]
            },
            "duplicate_route_ref",
        ),
        ({"routes": [{"ref": "r", "from": "loc_cave/main", "to": "loc_cave/main"}]}, "self_route"),
    ],
)
def test_invalid_routes_are_rejected(extra, code):
    with pytest.raises(GeographyError) as raised:
        compile_plan(plan(**extra))
    assert raised.value.code == code


def test_parent_cycle_is_rejected():
    p = plan()
    p["regions"][0]["parent"] = "reg_deep"
    with pytest.raises(GeographyError) as raised:
        compile_plan(p)
    assert raised.value.code == "parent_cycle"


def test_storage_round_trip_replaces_and_rejects_cross_world(settings):
    async def run():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                owner = await author(s)
                a = await create_project(s, owner, AuthorProjectCreate(title="A"))
                b = await create_project(s, owner, AuthorProjectCreate(title="B"))
                draft = compile_plan(
                    plan(routes=[{"ref": "r", "from": "loc_cave/part_crawl", "to": "loc_tunnels/part_junction"}])
                )
                view = await sync_geography(s, a.workspace_campaign_id, draft)
                assert len(view.nodes) == 5 and len(view.links) == 2
                parents = {n.ref: n.parent_ref for n in view.nodes}
                assert parents["reg_deep"] == "reg_hills" and parents["loc_cave"] == "reg_hills"
                smaller = compile_plan({"locations": [loc("loc_cave", "Пещера")]})
                view = await sync_geography(s, a.workspace_campaign_id, smaller)
                assert [n.ref for n in view.nodes] == ["loc_cave"] and view.links == ()
                other = await sync_geography(s, b.workspace_campaign_id, draft)
                assert len(other.nodes) == 5  # тот же ref в другом мире — независимые строки
                from sqlalchemy import select

                from app.db.models import GeographyNode

                foreign = (
                    await s.scalars(
                        select(GeographyNode.id).where(GeographyNode.campaign_id == b.workspace_campaign_id)
                    )
                ).first()
                with pytest.raises(GeographyError):
                    await assert_same_world(s, a.workspace_campaign_id, foreign)
                assert (await load_geography(s, a.workspace_campaign_id)).nodes
        finally:
            await engine.dispose()

    asyncio.run(run())
