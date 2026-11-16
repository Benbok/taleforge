"""Ways between places: a deed that succeeds can unlock or break one, on both of its sides."""

from __future__ import annotations

from app.db.models import Entity
from app.rules.universal.exploration import EffectChange

# (from, to): a locked way is unlocked (closed: the party may walk through) or broken (open); a blocked way is cleared.
ALLOWED = frozenset({("locked", "closed"), ("locked", "open"), ("blocked", "open")})
_NAMES = {"closed": "отперт", "open": "открыт"}


def _entries(state):
    sketch = state.get("sketch") or {}
    return [*(state.get("links") or []), *(sketch.get("exits") or []), *(sketch.get("unplaced_exits") or [])]


def place_passages(place) -> dict[str, dict]:
    """The ways of a place the party may know of (not hidden), by their passage id."""
    return {
        link["universal_passage"]: link
        for link in _entries((place.state if place else None) or {})
        if isinstance(link, dict) and link.get("universal_passage") and not link.get("hidden")
    }


def _rewrite(place, passage_id, to_state):
    def fix(link):
        if isinstance(link, dict) and link.get("universal_passage") == passage_id:
            return {**link, "state": to_state}
        return link

    state = dict(place.state or {})
    if "links" in state:
        state["links"] = [fix(link) for link in state["links"]]
    if isinstance(state.get("sketch"), dict):
        state["sketch"] = {
            **state["sketch"],
            **{
                key: [fix(x) for x in state["sketch"][key]]
                for key in ("exits", "unplaced_exits")
                if key in state["sketch"]
            },
        }
    place.state = state


async def check_passage(session, location_id, passage_id, to_state):
    """The way and its place, or a ValueError the model can repair: unknown way, or a change the rules do not allow."""
    place = await session.get(Entity, location_id) if location_id else None
    link = place_passages(place).get(passage_id or "")
    if link is None:
        raise ValueError(
            f"passage_id «{passage_id}» нет среди известных проходов этого места: возьми его из known_exits"
        )
    current = link.get("state", "open")
    if (current, to_state) not in ALLOWED:
        raise ValueError(
            f"passage нельзя перевести из «{current}» в «{to_state}»: "
            "отпереть можно запертый, выбить — запертый или заваленный"
        )
    return place, link


async def set_passage_state(session, campaign_id, location_id, passage_id, to_state) -> EffectChange:
    place, link = await check_passage(session, location_id, passage_id, to_state)
    _rewrite(place, passage_id, to_state)
    far = await session.get(Entity, link.get("to") or "")
    if far is not None and far.campaign_id == campaign_id:
        _rewrite(far, passage_id, to_state)
    return EffectChange(
        kind="passage",
        subject_id=passage_id,
        description=f"Проход «{link.get('label') or 'без названия'}» теперь {_NAMES[to_state]}.",
        data=dict(state=to_state),
    )
