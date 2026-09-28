import asyncio
import shutil

import pytest
from sqlalchemy import func, select

from app.content import PackError
from app.content.importer import import_pack, latest_version
from app.db.models import ContentPack, ContentRecord
from app.db.session import make_engine, make_sessionmaker
from tests.test_content import BASE


def run(settings, fn):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_import_base_pack_once(settings):
    assert run(settings, lambda s: import_pack(s, BASE)) == [("dnd5e-srd", "0.4.0", "imported")]
    assert run(settings, lambda s: import_pack(s, BASE)) == [("dnd5e-srd", "0.4.0", "unchanged")]

    async def check(s):
        n = await s.scalar(select(func.count()).select_from(ContentRecord).where(ContentRecord.kind == "dc_scale"))
        pack = await latest_version(s, "dnd5e-srd")
        rec = await s.get(ContentRecord, ("dnd5e-srd", "0.4.0", "condition.exhaustion"))
        return n, pack, rec

    n, pack, rec = run(settings, check)
    assert n == 6 and isinstance(pack, ContentPack) and pack.import_report["counts"]["item_template"] == 64
    assert rec.data["levels"]["6"][0]["target"] == "alive"


def test_same_version_other_content_is_refused(settings, tmp_path):
    copy = tmp_path / "dnd5e-srd"
    shutil.copytree(BASE, copy)
    run(settings, lambda s: import_pack(s, copy))
    (copy / "data" / "dc_scale.yaml").write_text(
        (copy / "data" / "dc_scale.yaml").read_text().replace("value: 5,", "value: 6,")
    )
    with pytest.raises(PackError, match="поднимите версию"):
        run(settings, lambda s: import_pack(s, copy))


def test_invalid_pack_is_not_written(settings, tmp_path):
    copy = tmp_path / "dnd5e-srd"
    shutil.copytree(BASE, copy)
    (copy / "data" / "bad.yaml").write_text("kind: dragon_lair\nitems: []\n")
    with pytest.raises(PackError):
        run(settings, lambda s: import_pack(s, copy))
    assert run(settings, lambda s: s.scalar(select(func.count()).select_from(ContentPack))) == 0
