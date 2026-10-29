"""Authorized cache scopes for campaign inventories and a user's library equipment."""

from dataclasses import dataclass

from sqlalchemy import or_, select

from app.core.campaigns import NotFound
from app.core.universal.inventory import starting_profiles
from app.core.universal.state import load_library_hero
from app.db.models import Character, EquipmentArtwork
from app.rules.universal.contracts import UniversalSheet


@dataclass(frozen=True)
class ArtworkScope:
    campaign_id: str | None
    owner_id: str | None = None
    linked_campaigns: tuple[str, ...] = ()

    @property
    def values(self):
        return dict(
            campaign_id=self.campaign_id,
            owner_user_id=None if self.campaign_id else self.owner_id,
            pending_scope="owner:" + self.owner_id if self.owner_id else "campaign:" + self.campaign_id,
        )

    def own_filter(self):
        if self.campaign_id:
            return EquipmentArtwork.campaign_id == self.campaign_id
        if not self.owner_id:
            raise ValueError("An artwork scope needs an owner or campaign")
        return EquipmentArtwork.owner_user_id == self.owner_id

    def read_filter(self):
        clauses = [self.own_filter()]
        if self.owner_id:
            clauses.append(EquipmentArtwork.owner_user_id == self.owner_id)
        if self.linked_campaigns:
            clauses.append(EquipmentArtwork.campaign_id.in_(self.linked_campaigns))
        return or_(*clauses)

    def permits(self, row):
        return bool(
            (self.campaign_id and row.campaign_id == self.campaign_id)
            or (self.owner_id and row.owner_user_id == self.owner_id)
            or row.campaign_id in self.linked_campaigns
        )


def as_scope(value):
    return value if isinstance(value, ArtworkScope) else ArtworkScope(value)


async def library_item(session, owner_id, hero_id, kind):
    hero = await load_library_hero(session, owner_id, hero_id)
    await session.refresh(hero)
    for profile in starting_profiles(UniversalSheet.model_validate(hero.sheet)):
        if profile.kind == kind:
            return profile.model_dump(mode="json")
    raise NotFound("Предмет недоступен")


async def library_scope(session, owner_id, hero_id):
    # Only campaign copies of this user's exact library hero may supply existing art.
    copies = await session.scalars(select(Character).where(Character.owner_user_id == owner_id))
    campaigns = tuple(
        {
            hero.campaign_id
            for hero in copies
            if hero.campaign_id and (hero.sheet or {}).get("source_library_id") == hero_id
        }
    )
    return ArtworkScope(None, owner_id, campaigns)
