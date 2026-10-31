"""Campaign world cover: the latest ready artwork of kind campaign_cover, built only from public world data."""

import asyncio
import io

from PIL import Image
from sqlalchemy import select

from app.agents.portraits import PortraitError, validate_image
from app.core.artwork import service
from app.core.artwork.recipe import ArtworkRecipe
from app.core.campaigns import NotFound, Viewer
from app.db.models import AdventureVersion, Artwork, AuthorProject, Campaign, ContentPack

KIND = "campaign_cover"
THUMBNAIL_SIZE = (640, 360)


def url(campaign_id, subject_id, image_id) -> str:
    return f"/api/campaigns/{campaign_id}/cover/{image_id}"


def thumbnail_url(campaign_id, image_id) -> str:
    return f"{url(campaign_id, campaign_id, image_id)}/thumbnail"


async def world_source(viewer, campaign, session) -> dict:
    """Name and public introduction; a world without one falls back to its public catalog entry."""
    text = (campaign.public_intro or "").strip()
    if not text and campaign.adventure_version_id:
        version = await session.get(AdventureVersion, campaign.adventure_version_id)
        summary = (version.public_summary or {}) if version else {}
        text = " ".join(
            part for part in (summary.get("title"), summary.get("tagline"), summary.get("intro")) if part
        ).strip()
    if not text and campaign.pack_id:
        text = (
            await session.scalar(
                select(ContentPack.name).where(
                    ContentPack.id == campaign.pack_id, ContentPack.version == campaign.pack_version
                )
            )
            or ""
        )
    return {"identity": campaign.name, "appearance": text or campaign.name, "personality": ""}


RECIPE = ArtworkRecipe(
    kind=KIND,
    media_subdir="campaign-covers",
    purpose="campaign_cover_illustration",
    noun="обложку",
    source=world_source,
    source_needs_session=True,
    permitted=lambda viewer: viewer.is_owner,
    blocker=lambda source: None,
    init_image=lambda source: None,
    prompt_source=lambda source: source,
    url=url,
    denied="обложку создаёт владелец кампании",
)


async def world_workspaces(session, campaign_ids) -> dict[str, str]:
    """Studio workspace of the world each campaign was launched from: its cover is the default one."""
    rows = await session.execute(
        select(Campaign.id, AuthorProject.workspace_campaign_id)
        .join(AdventureVersion, AdventureVersion.id == Campaign.adventure_version_id)
        .join(AuthorProject, AuthorProject.id == AdventureVersion.project_id)
        .where(Campaign.id.in_(list(campaign_ids)))
    )
    return dict(rows.all())


async def ready_covers(session, owner_ids) -> dict[str, str]:
    rows = await session.execute(
        select(Artwork.campaign_id, Artwork.id)
        .where(Artwork.kind == KIND, Artwork.status == "ready", Artwork.campaign_id.in_(list(owner_ids)))
        .order_by(Artwork.created_at.asc(), Artwork.id.asc())
    )
    return dict(rows.all())  # later rows overwrite earlier ones


async def latest_cover_ids(session, campaign_ids) -> dict[str, str]:
    """Newest ready cover per campaign, else the one of its world; a previous image stays while a replacement fails."""
    if not campaign_ids:
        return {}
    worlds = await world_workspaces(session, campaign_ids)
    found = await ready_covers(session, {*campaign_ids, *worlds.values()})
    return {cid: image for cid in campaign_ids if (image := found.get(cid) or found.get(worlds.get(cid)))}


def cover_urls(campaign_id, image_id) -> dict:
    return {
        "cover_url": url(campaign_id, campaign_id, image_id) if image_id else None,
        "cover_thumbnail_url": thumbnail_url(campaign_id, image_id) if image_id else None,
    }


async def status(session, viewer, enabled, base=None) -> dict:
    # base: where the files are served, e.g. the studio route of a world project
    result = await service.status(session, viewer, RECIPE, viewer.campaign, enabled)
    cid = viewer.campaign.id
    shown = (await latest_cover_ids(session, [cid])).get(cid)
    own = result["image_url"] is not None
    return {
        **result,
        "image_url": (f"{base}/{shown}" if base else url(cid, cid, shown)) if shown else None,
        "thumbnail_url": (f"{base}/{shown}/thumbnail" if base else thumbnail_url(cid, shown)) if shown else None,
        "inherited": bool(shown) and not own,
    }


async def source_viewer(session, viewer, image_id):
    """Viewer of the campaign that owns the image: the campaign itself or the studio workspace of its world."""
    image = await session.get(Artwork, image_id)
    if image is None or image.campaign_id == viewer.campaign.id:
        return viewer
    if (await world_workspaces(session, [viewer.campaign.id])).get(viewer.campaign.id) != image.campaign_id:
        return viewer
    return Viewer(viewer.user, await session.get(Campaign, image.campaign_id), None)


async def read_cover(session, viewer, image_id, media_dir):
    owner = await source_viewer(session, viewer, image_id)
    return await service.read_image(session, owner, RECIPE, owner.campaign, image_id, media_dir)


def make_thumbnail(data: bytes, mime: str) -> bytes:
    validate_image(data, mime)
    try:
        with Image.open(io.BytesIO(data), formats=("PNG", "JPEG", "WEBP")) as image:
            image.load()
            image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.convert("RGB").save(output, "WEBP", quality=80)
            return output.getvalue()
    except Exception as exc:
        raise PortraitError("invalid_image") from exc


async def read_thumbnail(session, viewer, image_id, media_dir):
    path, mime = await read_cover(session, viewer, image_id, media_dir)
    small = path.with_suffix(".webp")
    if not small.is_file():
        data = await asyncio.to_thread(path.read_bytes)
        try:
            preview = await asyncio.to_thread(make_thumbnail, data, mime)
        except PortraitError as exc:
            raise NotFound("файл картинки не найден") from exc
        partial = small.with_name(f"{small.name}.part")
        await asyncio.to_thread(partial.write_bytes, preview)
        await asyncio.to_thread(partial.replace, small)
    return small, "image/webp"
