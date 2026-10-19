"""The single mutation path for author content: manual forms and applied AI proposals both land here."""

import copy
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authoring.contracts import (
    DraftPatch,
    EditMap,
    EditProposal,
    EditResult,
    RemoveObject,
    ResultRef,
    SetLore,
    SetPlacement,
    SetPlotText,
    UpdateItem,
    UpdatePlotObject,
    UpsertRoute,
)
from app.core.authoring.dependencies import KINDS, affected_results, users_of
from app.core.authoring.projects import author_write
from app.core.campaigns import Conflict
from app.core.geography.compiler import compile_plan
from app.core.geography.contracts import GeographyError
from app.core.layout.spatial import SpatialPlan
from app.db.models import AuthorProject, CampaignSecret, Entity, Event, GeographyNode

LORE_TEXT = {"overview", "era_and_magic", "current_situation", "tone", "world"}  # world: legacy one-line lore
LORE_STRINGS = {"mysteries", "taboos"}
LORE_RECORDS = {
    "regions": {"id", "name", "description"},
    "history": {"when", "event"},
    "factions": {"name", "goal", "resources", "relations", "secret"},
    "figures": {"name", "role", "motive"},
}
LORE_KEYS = LORE_TEXT | LORE_STRINGS | set(LORE_RECORDS)


def _check_lore_field(key: str, value) -> object:
    if key in LORE_TEXT:
        if not isinstance(value, str) or len(value) > 6000:
            raise EditError("invalid_field", key)
        return value.strip()
    if not isinstance(value, list) or len(value) > 20:
        raise EditError("invalid_field", key)
    if key in LORE_STRINGS or (key == "factions" and all(isinstance(v, str) for v in value)):
        if not all(isinstance(v, str) and len(v) <= 600 for v in value):
            raise EditError("invalid_field", key)
        return [v.strip() for v in value if v.strip()]
    allowed = LORE_RECORDS.get(key, set())
    if not all(
        isinstance(v, dict) and set(v) <= allowed and all(len(str(x)) <= 1200 for x in v.values()) for v in value
    ):
        raise EditError("invalid_field", key)
    return [{k: str(x).strip() for k, x in v.items()} for v in value]


# Editable text fields per plot kind. Structure (id, template_id, status, entity_id, spatial) is not editable here.
TEXT_FIELDS = {
    "locations": {"name", "mood", "role", "secret"},
    "npcs": {
        "name",
        "role",
        "want",
        "fear",
        "secret",
        "attitude",
        "look",
        "character",
        "speech",
        "knows",
        "ties",
        "sways",
    },
    "antagonists": {"name", "goal", "methods", "weakness", "secret", "character", "speech", "on_meeting", "if_foiled"},
}
ITEM_FIELDS = {"name", "description", "template_id"}
TEXT_LIMIT = 2000  # per field of a character, location or item; the web editors share this cap
PLOT_TEXT = {"title", "tagline", "public_intro", "conflict", "stakes"}


class EditError(Conflict):
    """The patch is invalid; nothing was changed."""

    def __init__(self, code: str, ref: str = ""):
        super().__init__(f"{code}: {ref}" if ref else code)
        self.code = code


def _find(plan: dict, ref: str) -> tuple[str, dict] | tuple[None, None]:
    for kind in KINDS:
        for obj in plan.get(kind) or []:
            if obj.get("id") == ref:
                return kind, obj
    return None, None


def _check_text(value: str, ref: str, *, name: bool = False) -> str:
    text = value.strip()
    if len(text) > TEXT_LIMIT or (name and not text):
        raise EditError("invalid_field", ref)
    return text


def _apply(plan: dict, setting: dict, patch: DraftPatch) -> tuple[dict, dict, list[ResultRef]]:
    """Pure: returns the edited copies and the objects that block a requested removal."""
    plan, setting = copy.deepcopy(plan), copy.deepcopy(setting)
    blocked: list[ResultRef] = []
    for op in patch.operations:
        if isinstance(op, SetLore):
            if not set(op.fields) <= LORE_KEYS:
                raise EditError("unknown_lore_field", ",".join(sorted(set(op.fields) - LORE_KEYS)))
            checked = {key: _check_lore_field(key, value) for key, value in op.fields.items()}
            setting["lore"] = {**(setting.get("lore") or {}), **checked}
        elif isinstance(op, SetPlotText):
            if not set(op.fields) <= PLOT_TEXT:
                raise EditError("field_not_editable", ",".join(sorted(set(op.fields) - PLOT_TEXT)))
            for key, value in op.fields.items():
                if len(value) > 4000 or (key == "title" and not value.strip()):
                    raise EditError("invalid_field", key)
                plan[key] = value.strip()
        elif isinstance(op, UpdatePlotObject):
            kind, obj = _find(plan, op.ref)
            if obj is None:
                raise EditError("unknown_ref", op.ref)
            if not set(op.fields) <= TEXT_FIELDS[kind]:
                raise EditError("field_not_editable", op.ref)
            for key, value in op.fields.items():
                obj[key] = _check_text(value, f"{op.ref}.{key}", name=key == "name")
        elif isinstance(op, UpdateItem):
            item = next((i for i in plan.get("items") or [] if i.get("ref") == op.ref), None)
            if item is None:
                raise EditError("unknown_ref", op.ref)
            if not set(op.fields) <= ITEM_FIELDS:
                raise EditError("field_not_editable", op.ref)
            for key, value in op.fields.items():
                item[key] = _check_text(value, f"{op.ref}.{key}", name=key in ("name", "template_id"))
        elif isinstance(op, SetPlacement):
            loc = next((x for x in plan.get("locations") or [] if x["id"] == op.location_ref), None)
            if loc is None:
                raise EditError("unknown_ref", op.location_ref)
            parts = {p["ref"] for p in (loc.get("spatial") or {}).get("parts") or []}
            if op.area_ref is not None and parts and op.area_ref not in parts:
                raise EditError("unknown_part", f"{op.location_ref}/{op.area_ref}")
            holders = {i["ref"] for i in plan.get("items") or [] if i.get("container")}
            holders |= {n["id"] for n in plan.get("npcs") or []}
            if op.container_ref is not None and (op.container_ref not in holders or op.container_ref == op.ref):
                raise EditError("unknown_container", op.container_ref)
            entry = {
                "ref": op.ref,
                "location_ref": op.location_ref,
                "area_ref": op.area_ref,
                "container_ref": op.container_ref,
            }
            plan["placements"] = [p for p in plan.get("placements") or [] if p.get("ref") != op.ref] + [entry]
        elif isinstance(op, UpsertRoute):
            route = {
                "ref": op.ref,
                "from": op.source,
                "to": op.target,
                "bidirectional": op.bidirectional,
                "hidden": op.hidden,
            }
            plan["routes"] = [r for r in plan.get("routes") or [] if r.get("ref") != op.ref] + [route]
        elif isinstance(op, EditMap):
            loc = next((x for x in plan.get("locations") or [] if x["id"] == op.location_ref), None)
            if loc is None:
                raise EditError("unknown_ref", op.location_ref)
            try:
                loc["spatial"] = SpatialPlan.model_validate(op.spatial).model_dump(mode="json")
            except ValueError as exc:
                raise EditError("invalid_map", op.location_ref) from exc
        elif isinstance(op, RemoveObject):
            users = [u for u in users_of(plan, op.ref) if u.ref != op.ref]
            if users:
                blocked.extend(users)
                continue
            for key in (*KINDS, "items", "routes", "placements"):
                idkey = "id" if key in KINDS else "ref"
                plan[key] = [x for x in plan.get(key) or [] if x.get(idkey) != op.ref]
    try:
        compile_plan(plan)  # one validator: references, parts and routes stay consistent
    except GeographyError as exc:
        raise EditError(exc.code, ",".join(exc.refs)) from exc
    return plan, setting, blocked


def preview_edit(plan: dict, setting: dict, patch: DraftPatch) -> EditProposal:
    """Dry run: the proposed patch, what it would invalidate; nothing is written."""
    _apply(plan, setting, patch)
    return EditProposal(base_revision=0, patch=patch, affected=affected_results(patch, plan))


def _key(project_id: str, request_key: str) -> str:
    return hashlib.sha256(f"{project_id}:{request_key}".encode()).hexdigest()[:64]


def _digest(patch: DraftPatch) -> str:
    body = json.dumps(patch.model_dump(mode="json", by_alias=True), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


async def apply_edits(
    session: AsyncSession, project: AuthorProject, patch: DraftPatch, expected_revision: int, request_key: str
) -> EditResult:
    key, digest = _key(project.id, request_key), _digest(patch)
    done = await session.scalar(
        select(Event).where(Event.campaign_id == project.workspace_campaign_id, Event.idempotency_key == key)
    )
    if done is not None:
        if done.payload.get("patch_digest") != digest:
            raise Conflict("request_key уже использован для другой правки")
        return EditResult.model_validate(done.payload["result"]).model_copy(update={"event_id": done.id})
    await author_write(session, project, expected_revision)  # stale revision -> Conflict, no change
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    plan, setting = (secret.plot if secret else None) or {}, (secret.setting if secret else None) or {}
    new_plan, new_setting, blocked = _apply(plan, setting, patch)
    result_patch = patch
    if blocked:
        result_patch = DraftPatch(operations=[op for op in patch.operations if not isinstance(op, RemoveObject)])
    affected = affected_results(result_patch, plan)
    if secret is None:
        secret = CampaignSecret(campaign_id=project.workspace_campaign_id)
        session.add(secret)
    changed = (new_plan, new_setting) != (plan, setting)
    if changed:
        secret.plot, secret.setting = new_plan, new_setting
        await _sync_names(session, project, new_plan)
        stale = set((project.dependencies or {}).get("stale") or [])
        stale |= {f"{a.kind}:{a.ref}" for a in affected}
        deps = {**(project.dependencies or {}), "stale": sorted(stale)}
        if new_setting.get("lore") != setting.get("lore"):
            from app.core.authoring.pipeline import output_digest

            # A manual lore edit is a new input for the plot: a background result built on the old lore goes stale.
            deps["lore"] = output_digest({"lore": new_setting.get("lore")})
        project.dependencies = deps
    result = EditResult(
        applied=changed,
        draft_revision=project.draft_revision,
        affected=affected if changed else (),
        blocked_by=tuple(blocked),
    )
    event = Event(
        campaign_id=project.workspace_campaign_id,
        tool="author_edit",
        hidden=True,
        idempotency_key=key,
        payload={
            "request_key": request_key,
            "patch_digest": digest,
            "before": {"plot": plan, "setting": setting} if changed else {},
            "after": {"plot": new_plan, "setting": new_setting} if changed else {},
            "result": result.model_dump(mode="json"),
        },
    )
    session.add(event)
    await session.flush()
    return result.model_copy(update={"event_id": event.id})


async def _sync_names(session: AsyncSession, project: AuthorProject, plan: dict) -> None:
    """A renamed place or NPC renames its entity and geography node; maps are not rebuilt."""
    for kind in ("locations", "npcs"):
        for obj in plan.get(kind) or []:
            if obj.get("entity_id"):
                entity = await session.get(Entity, obj["entity_id"])
                if entity is not None and entity.name != obj["name"]:
                    entity.name = obj["name"]
    for node in await session.scalars(
        select(GeographyNode).where(GeographyNode.campaign_id == project.workspace_campaign_id)
    ):
        loc = next((x for x in plan.get("locations") or [] if x["id"] == node.ref), None)
        if loc is not None and node.name != loc["name"]:
            node.name = loc["name"]


async def accept_stale(
    session: AsyncSession, project: AuthorProject, refs: list[str], expected_revision: int, request_key: str
) -> EditResult:
    """The author keeps an existing result as current instead of regenerating it; the choice is journaled."""
    key = _key(project.id, request_key)
    done = await session.scalar(
        select(Event).where(Event.campaign_id == project.workspace_campaign_id, Event.idempotency_key == key)
    )
    if done is not None:
        return EditResult.model_validate(done.payload["result"]).model_copy(update={"event_id": done.id})
    await author_write(session, project, expected_revision)
    before = list((project.dependencies or {}).get("stale") or [])
    unknown = sorted(set(refs) - set(before))
    if unknown:
        raise EditError("not_stale", ",".join(unknown))
    project.dependencies = {**(project.dependencies or {}), "stale": sorted(set(before) - set(refs))}
    result = EditResult(applied=True, draft_revision=project.draft_revision)
    event = Event(
        campaign_id=project.workspace_campaign_id,
        tool="author_edit",
        hidden=True,
        idempotency_key=key,
        payload={"request_key": request_key, "accepted_stale": sorted(refs), "result": result.model_dump(mode="json")},
    )
    session.add(event)
    await session.flush()
    return result.model_copy(update={"event_id": event.id})
