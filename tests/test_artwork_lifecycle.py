import asyncio
import types
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agents.portraits import ImageReply, PortraitError
from app.core.artwork import service
from app.core.artwork.recipe import ArtworkRecipe
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.db.models import Artwork, Entity, LlmCall, now
from tests.test_api import make_campaign
from tests.test_hero_portraits import PNG


def make_recipe(**over):
    def source(viewer, subject):
        return {"identity": subject.name, "appearance": subject.description or "", "personality": "", "x": 1}

    base = dict(
        kind="test_kind",
        media_subdir="test-art",
        purpose="test_art",
        noun="картинку",
        source=source,
        permitted=lambda viewer: viewer.admin,
        blocker=lambda src: None if src["appearance"].strip() else "сначала дождитесь описания",
        init_image=lambda src: b"init-" + src["identity"].encode(),
        prompt_source=lambda src: {k: src[k] for k in ("identity", "appearance", "personality")},
        url=lambda cid, sid, image: f"/api/test/{cid}/{sid}/{image}",
    )
    return ArtworkRecipe(**{**base, **over})


class FakeGenerator:
    model = "comfyui/test"
    timeout_seconds = 600

    def __init__(self):
        self.calls, self.inits, self.fail = 0, [], False

    async def generate(self, description, *, init_image=None):
        self.calls += 1
        self.inits.append(init_image)
        if self.fail:
            raise PortraitError("comfyui_unavailable")
        return ImageReply(PNG, "image/png", self.model, cost_known=True)


class FakeTranslator:
    timeout_seconds = 20

    def __init__(self):
        self.payloads = []

    async def translate(self, session, description, campaign_id=None):
        self.payloads.append(description)
        return {**description, "appearance": "english " + description["appearance"]}


@pytest.fixture
def world(client, root, tmp_path):
    cid = make_campaign(client, root)["id"]
    maker = client.app.state.sessionmaker

    def run(function):
        async def go():
            async with maker() as session:
                session.add(
                    Entity(id="lc_room", campaign_id=cid, kind="location", name="Двор", description="Двор таверны.")
                )
                await session.commit()
            async with maker() as session:
                viewer = types.SimpleNamespace(campaign=types.SimpleNamespace(id=cid), admin=True)
                subject = await session.get(Entity, "lc_room")
                result = await function(session, viewer, subject)
                await session.commit()
                return result

        return asyncio.run(go())

    return cid, maker, run, tmp_path


def test_generate_once_and_cache(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        first = await service.generate(session, viewer, recipe, subject, "k1", False, generator, translator, tmp)
        second = await service.generate(session, viewer, recipe, subject, "k2", False, generator, translator, tmp)
        again = await service.generate(session, viewer, recipe, subject, "k1", False, generator, translator, tmp)
        return first, second, again, await service.status(session, viewer, recipe, subject, True)

    first, second, again, status = run(go)
    assert first["status"] == "ready" and first["image_url"] == second["image_url"] == again["image_url"]
    assert status["can_generate"] is True and status["stale"] is False
    assert generator.calls == 1 and generator.inits == ["init-Двор".encode()]
    assert translator.payloads == [{"identity": "Двор", "appearance": "Двор таверны.", "personality": ""}]


def test_regenerate_and_failure_keep_previous_image(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        before = await service.generate(session, viewer, recipe, subject, "ok", False, generator, translator, tmp)
        generator.fail = True
        for _ in range(2):
            with pytest.raises(Conflict):
                await service.generate(session, viewer, recipe, subject, "bad", True, generator, translator, tmp)
        return before, await service.status(session, viewer, recipe, subject, True)

    before, after = run(go)
    assert after["image_url"] == before["image_url"] and generator.calls == 2


def test_changed_source_marks_stale_and_new_attempt_replaces(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        before = await service.generate(session, viewer, recipe, subject, "a", False, generator, translator, tmp)
        subject.description = "Идёт снег."
        stale = await service.status(session, viewer, recipe, subject, True)
        same = await service.generate(session, viewer, recipe, subject, "b", False, generator, translator, tmp)
        fresh = await service.generate(session, viewer, recipe, subject, "c", True, generator, translator, tmp)
        return before, stale, same, fresh

    before, stale, same, fresh = run(go)
    assert stale["stale"] is True and same["image_url"] == before["image_url"]
    assert fresh["image_url"] != before["image_url"] and fresh["stale"] is False


def test_pending_attempt_blocks_a_second_one_until_lease_expires(world):
    cid, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        session.add(
            Artwork(
                campaign_id=cid,
                kind="test_kind",
                subject_id="lc_room",
                request_key="held",
                source_digest="d",
                status="pending",
                lease_until=now() + timedelta(minutes=5),
            )
        )
        await session.commit()
        with pytest.raises(service.ArtworkPending):
            await service.generate(session, viewer, recipe, subject, "other", False, generator, translator, tmp)
        await session.refresh(subject)
        held = (await session.execute(select(Artwork).where(Artwork.request_key == "held"))).scalar_one()
        held.lease_until = now() - timedelta(minutes=1)
        await session.commit()
        return await service.generate(session, viewer, recipe, subject, "other", False, generator, translator, tmp)

    assert run(go)["status"] == "ready" and generator.calls == 1


def test_failed_receipt_is_not_replayed(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        generator.fail = True
        with pytest.raises(Conflict):
            await service.generate(session, viewer, recipe, subject, "same", False, generator, translator, tmp)
        generator.fail = False
        with pytest.raises(Conflict):
            await service.generate(session, viewer, recipe, subject, "same", False, generator, translator, tmp)

    run(go)
    assert generator.calls == 1


def test_source_changing_midway_is_not_published(world):
    _, _, run, tmp = world
    recipe, translator = make_recipe(), FakeTranslator()

    class Moving(FakeGenerator):
        async def generate(self, description, *, init_image=None):
            self.subject.description = "Другое описание."
            await self.session.flush()
            return await super().generate(description, init_image=init_image)

    generator = Moving()

    async def go(session, viewer, subject):
        generator.subject, generator.session = subject, session
        with pytest.raises(Conflict):
            await service.generate(session, viewer, recipe, subject, "k", False, generator, translator, tmp)
        return await service.status(session, viewer, recipe, subject, True)

    status = run(go)
    assert status["image_url"] is None and status["status"] == "failed"
    assert not (tmp / "test-art").exists() or not list((tmp / "test-art").iterdir())


def test_not_permitted_viewer_is_denied_and_generator_untouched(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        viewer.admin = False
        status = await service.status(session, viewer, recipe, subject, True)
        with pytest.raises(AccessDenied):
            await service.generate(session, viewer, recipe, subject, "k", False, generator, translator, tmp)
        viewer.admin = True
        with pytest.raises(Conflict):
            await service.generate(session, viewer, recipe, subject, "k", False, None, translator, tmp)
        return status

    assert run(go)["can_generate"] is False and generator.calls == 0


def test_blocked_source_gives_conflict_and_no_generation(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        subject.description = " "
        status = await service.status(session, viewer, recipe, subject, True)
        with pytest.raises(Conflict, match="описания"):
            await service.generate(session, viewer, recipe, subject, "k", False, generator, translator, tmp)
        return status

    assert run(go)["can_generate"] is False and generator.calls == 0


def test_audit_row_uses_recipe_purpose(world):
    _, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        await service.generate(session, viewer, recipe, subject, "k", False, generator, translator, tmp)
        return (await session.execute(select(LlmCall).where(LlmCall.purpose == "test_art"))).scalars().all()

    rows = run(go)
    assert len(rows) == 1 and rows[0].error is None and rows[0].model == "comfyui/test"


def test_read_image_rejects_foreign_subject_and_campaign(world):
    cid, _, run, tmp = world
    recipe, generator, translator = make_recipe(), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        ready = await service.generate(session, viewer, recipe, subject, "k", False, generator, translator, tmp)
        image_id = ready["image_url"].rsplit("/", 1)[1]
        path, mime = await service.read_image(session, viewer, recipe, subject, image_id, tmp)
        assert path.read_bytes() == PNG and mime == "image/png"
        other = Entity(id="lc_other", campaign_id=cid, kind="location", name="Иной", description="x")
        session.add(other)
        await session.commit()
        with pytest.raises(NotFound):
            await service.read_image(session, viewer, recipe, other, image_id, tmp)
        viewer.campaign = types.SimpleNamespace(id="elsewhere")
        with pytest.raises(NotFound):
            await service.read_image(session, viewer, recipe, subject, image_id, tmp)
        viewer.campaign = types.SimpleNamespace(id=cid)
        with pytest.raises(NotFound):
            await service.read_image(session, viewer, recipe, subject, "missing", tmp)

    run(go)


def test_async_source_with_session_is_awaited_and_its_digest_decides_staleness(world):
    _, _, run, tmp = world
    extra = {"value": 1}

    async def source(viewer, subject, session):
        assert session is not None
        return {"identity": subject.name, "appearance": subject.description, "personality": "", "extra": extra["value"]}

    recipe, generator, translator = make_recipe(source=source, source_needs_session=True), FakeGenerator(), FakeTranslator()

    async def go(session, viewer, subject):
        ready = await service.generate(session, viewer, recipe, subject, "a", False, generator, translator, tmp)
        extra["value"] = 2
        return ready, await service.status(session, viewer, recipe, subject, True)

    ready, after = run(go)
    assert ready["stale"] is False and after["stale"] is True and after["image_url"] == ready["image_url"]
