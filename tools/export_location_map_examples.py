"""Пилотные снимки карты из отдельной временной SQLite, без рабочей БД и модели."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.campaigns import Viewer  # noqa: E402
from app.core.layout.geometry import build_area  # noqa: E402
from app.core.layout.provider import DeterministicLayoutProvider  # noqa: E402
from app.core.layout.validation import validate  # noqa: E402
from app.core.map import party_map  # noqa: E402
from app.core.map_memory import observe_area  # noqa: E402
from app.db.models import Base, Campaign, Character, Entity, Scene, Seat, User  # noqa: E402
from app.db.session import make_engine, make_sessionmaker  # noqa: E402
from app.gateway.protocol import MapState  # noqa: E402
from tests.layout_pilot import pilot_intent  # noqa: E402

OUT = ROOT / "docs" / "examples" / "location-maps"
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


async def export(directory: Path = OUT) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="taleforge-map-demo-") as tmp:
        engine = make_engine(f"sqlite+aiosqlite:///{Path(tmp) / 'demo.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with make_sessionmaker(engine)() as session:
                user = User(id="demo-user", name="Пример", password_hash="демо")
                campaign = Campaign(id="demo", owner_id=user.id, name="Старый храм", ruleset_version="5.1")
                session.add(user)
                await session.flush()
                session.add(campaign)
                await session.flush()
                village = Entity(id="demo-village", campaign_id=campaign.id, kind="location", name="Деревня")
                root = Entity(id="demo-temple", campaign_id=campaign.id, kind="location", name="Старый храм")
                intent = pilot_intent(village.id)
                next(part for part in intent.parts if part.part_ref == "sacristy").shape = "circle"
                bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id=root.id)
                errors = validate(bp)
                if errors:
                    raise ValueError(errors)
                ids = {area.area_ref: f"demo-{area.area_ref}" for area in bp.areas}
                root.state = {"blueprint": bp.to_json(), "areas": ids}
                entities = {root.id: root, village.id: village}
                for area in bp.areas:
                    entity = Entity(
                        id=ids[area.area_ref],
                        campaign_id=campaign.id,
                        kind="location",
                        location_id=root.id,
                        name=area.public_name,
                        state={
                            "complex": {"root_id": root.id, "area_ref": area.area_ref},
                            "secret": area.secret,
                            "sketch": build_area(bp, area, root_id=root.id, ids=ids),
                        },
                    )
                    entities[entity.id] = entity
                # порядок мест на карте идёт по created_at: фиксированное время делает экспорт воспроизводимым
                for i, entity in enumerate(entities.values()):
                    entity.created_at = EPOCH + timedelta(seconds=i)
                session.add_all(list(entities.values()))
                seats = [
                    Seat(
                        id=f"demo-seat-{i}",
                        campaign_id=campaign.id,
                        role="player",
                        position=i,
                        occupant_type="human",
                        user_id=user.id,
                    )
                    for i in (1, 2)
                ]
                session.add_all(seats)
                await session.flush()
                heroes = [
                    Character(
                        id=f"demo-hero-{i}",
                        campaign_id=campaign.id,
                        seat_id=seats[i - 1].id,
                        name=f"Герой {i}",
                        status="active",
                        location_id=ids["road"],
                        resources={"hp": 10, "hp_max": 10},
                    )
                    for i in (1, 2)
                ]
                scene = Scene(campaign_id=campaign.id, location_id=ids["road"])
                session.add_all([scene, *heroes])
                await session.flush()
                ctx = SimpleNamespace(
                    session=session,
                    campaign=campaign,
                    world=SimpleNamespace(
                        entities=entities,
                        characters={hero.id: hero for hero in heroes},
                        revealed={},
                        map_known={},
                        scene=scene,
                        # как World.place_of: своё место героя, иначе место сцены
                        place_of=lambda hero: hero.location_id or scene.location_id,
                    ),
                )
                await observe_area(ctx, ids["road"], [hero.id for hero in heroes], [])
                await observe_area(ctx, ids["nave"], [heroes[0].id], [], explicit=True)
                await observe_area(ctx, ids["sacristy"], [heroes[0].id], [], explicit=True)
                await session.commit()

                async def save(name: str, hero: Character, place: str) -> None:
                    hero.location_id = ids[place]
                    scene.location_id = ids[place]
                    await observe_area(ctx, ids[place], [hero.id], [])
                    await session.commit()
                    packet = MapState.model_validate(
                        await party_map(session, Viewer(user, campaign, seats[heroes.index(hero)]))
                    )
                    data = packet.model_dump(mode="json")
                    for area in (data.get("location_map") or {}).get("areas", []):
                        area["observed_at"] = None
                    (directory / f"{name}.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )

                await save("temple-known", heroes[0], "sacristy")
                await save("field-stream-bridge", heroes[0], "brook")
                await save("hero-memory", heroes[1], "road")
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(export())
