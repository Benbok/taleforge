"""Подготовка мира по запросу (docs/world-objects-delivery3.md): команды только принимают подготовку и отдают
квитанцию ``{accepted, operation_ref}``; наполняет исполнитель (``app/core/world_generation/service.py``) после
фиксации хода. Чтение статуса ничего не запускает."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import economy
from app.core.layout.intent import LayoutIntent
from app.core.preparation import brief_status, public_status, receipt
from app.core.world_generation import storage
from app.core.world_generation.profiles import MINIMAL_REF, ProfileError, load_profile
from app.db.models import Event
from app.tools.master.items import _accessible_container, _approach, container_contents
from app.tools.registry import ToolContext, ToolError, tool

# Команды ведущего: ИИ-мастер их не видит (app/agents/master/common.py)
HOST_TOOLS = frozenset(
    {
        "resolve_location",
        "retry_preparation",
        "bind_plot_anchor",
        "prepare_complex",
        "prepare_location",
        "preparation_cost",
    }
)


class ResolveLocationArgs(BaseModel):
    location_id: str = Field(description="реальный id локации, не название")
    profile_id: str | None = Field(
        None, description="профиль scene_profile.* из пакета или minimal; пусто — профиль шаблона места"
    )


@tool(
    "resolve_location",
    "Команда ведущего: назначает месту профиль наполнения и просит подготовить его. Возвращает квитанцию; "
    "наполнение появится после подготовки. Профиль уже подготовленного места не меняется.",
    ResolveLocationArgs,
    ids={"location_id": "locations", "profile_id": "templates:scene_profile"},
    closes=False,
)
async def resolve_location(ctx: ToolContext, a: ResolveLocationArgs) -> dict:
    target = ctx.world.entities.get(a.location_id)
    if target is None or target.kind != "location" or target.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    row = await storage.find(ctx.session, ctx.campaign.id, target.id, "location_initial")
    inverse: list = []
    if a.profile_id is not None:
        try:
            load_profile(ctx.world.catalog, a.profile_id)
        except ProfileError as e:
            raise ToolError(f"профиль не подходит: {e}") from e
        if row is not None and row.profile_ref != a.profile_id:
            raise ToolError("у места уже есть резерв подготовки с другим профилем")
        if row is None:
            inverse.append({"table": "entities", "id": target.id, "field": "state", "before": dict(target.state or {})})
            target.state = {**(target.state or {}), "scene_profile": a.profile_id}
    if row is None:
        row = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, target)
        inverse.append({"table": "world_generation_states", "op": "delete", "id": row.id})
    storage.activate(row)
    result = {"location_id": target.id, "profile": row.profile_ref or MINIMAL_REF, **receipt(row.id)}
    await ctx.record("resolve_location", target_id=target.id, payload=result, inverse=inverse, hidden=True)
    return result


class RetryPreparationArgs(BaseModel):
    operation_ref: str = Field(description="operation_ref заблокированной подготовки")


@tool(
    "retry_preparation",
    "Команда ведущего: повторить заблокированную подготовку с тем же резервом и seed. Герои ничего не тратят.",
    RetryPreparationArgs,
    closes=False,
)
async def retry_preparation(ctx: ToolContext, a: RetryPreparationArgs) -> dict:
    from app.db.models import WorldGenerationState

    row = await ctx.session.get(WorldGenerationState, a.operation_ref)
    if row is None or row.campaign_id != ctx.campaign.id:
        raise ToolError("подготовка не найдена")
    if row.status != "blocked":
        raise ToolError("повторить можно только заблокированную подготовку")
    if row.last_error == "unsupported_source" and not row.reservation:
        raise ToolError("профиль места не прошёл проверку: исправьте пакет, повтор с тем же резервом невозможен")
    reason = row.last_error
    storage.retry(row)
    result = {**receipt(row.id), "previous_reason": reason}
    await ctx.record("retry_preparation", target_id=row.target_entity_id, payload=result, hidden=True)
    return result


class SearchContainerArgs(BaseModel):
    character_id: str
    container_id: str


async def _accepted_by(ctx: ToolContext, hero_id: str, container_id: str, ref: str) -> dict | None:
    """Квитанция, которую этот герой уже получил за эту фазу (любым ключом)."""
    q = select(Event).where(
        Event.campaign_id == ctx.campaign.id,
        Event.tool == "search_container",
        Event.actor_id == hero_id,
        Event.target_id == container_id,
    )
    for ev in await ctx.session.scalars(q.order_by(Event.created_at)):
        result = (ev.payload or {}).get("result") or {}
        if result.get("accepted") and result.get("operation_ref") == ref:
            return result
    return None


@tool(
    "search_container",
    "Герой обыскивает открытый доступный контейнер. Готовое содержимое возвращается сразу; неисследованное "
    "принимается к подготовке (квитанция operation_ref), в бою это стоит действия один раз. Повтор не платит.",
    SearchContainerArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def search_container(ctx: ToolContext, a: SearchContainerArgs) -> dict:
    hero, container, found = await _accessible_container(ctx, a.character_id, a.container_id)
    if not (container.state or {}).get("world_object", {}).get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    row = await storage.find(ctx.session, ctx.campaign.id, container.id, "container_contents")
    status = "ready" if row is None else public_status(row)
    if status == "ready":  # ручной контейнер или уже подготовленное: чтение без расхода
        _approach(ctx, hero, container, walk=False)
        ctx.closed.add(hero.id)
        return {"container_id": container.id, "status": "ready", "contents": container_contents(ctx, container, found)}
    if status == "blocked":
        ctx.closed.add(hero.id)
        return {"container_id": container.id, **await brief_status(ctx.session, ctx.campaign.id, row.id)}
    prior = await _accepted_by(ctx, hero.id, container.id, row.id)
    if prior is not None:  # тот же герой, та же фаза: исходная квитанция без нового расхода
        ctx.closed.add(hero.id)
        return prior
    if status == "pending":  # другой герой уже обыскивает: статус без расхода
        ctx.closed.add(hero.id)
        return {"container_id": container.id, **await brief_status(ctx.session, ctx.campaign.id, row.id)}
    inverse = economy.charge(ctx, hero.id, "search")  # вне боя ничего не стоит
    inverse += _approach(ctx, hero, container, walk=True)
    storage.activate(row)
    result = {"container_id": container.id, **receipt(row.id)}
    await ctx.record("search_container", actor_id=hero.id, target_id=container.id, payload=result, inverse=inverse)
    ctx.closed.add(hero.id)
    return result


class GenerationStatusArgs(BaseModel):
    operation_ref: str = Field(description="operation_ref из квитанции принятого исследования")


@tool(
    "generation_status",
    "Только чтение: текущий статус подготовки мира по operation_ref из квитанции — unexamined, pending, ready "
    "или blocked с причиной; после ready — созданные объекты. Ничего не запускает и не меняет.",
    GenerationStatusArgs,
    mutating=False,
    closes=False,
)
async def generation_status(ctx: ToolContext, a: GenerationStatusArgs) -> dict:
    from app.core import preparation
    from app.core.campaigns import NotFound

    try:
        return await preparation.generation_status(ctx.session, ctx.campaign.id, a.operation_ref, None)
    except NotFound as e:
        raise ToolError(str(e)) from e


class PrepareComplexArgs(BaseModel):
    location_id: str = Field(description="реальный id места, которое станет комплексом участков")
    intent: LayoutIntent = Field(description="пространственный замысел: части, связи, подходы, дороги и ручьи")


@tool(
    "prepare_complex",
    "Команда ведущего: принимает пространственный замысел места и просит подготовить его структуру — участки и "
    "проходы между ними. Возвращает квитанцию; уже принятый замысел не перестраивается.",
    PrepareComplexArgs,
    ids={"location_id": "locations"},
    closes=False,
)
async def prepare_complex(ctx: ToolContext, a: PrepareComplexArgs) -> dict:
    from app.core import adventure
    from app.core.layout import store as layout_store

    w = ctx.world
    root = w.entities.get(a.location_id)
    if root is None or root.kind != "location" or root.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    if layout_store.complex_of(root) is not None:
        raise ToolError("участок комплекса сам комплексом не становится")
    if adventure.room_of(root) is not None:
        raise ToolError("готовое приключение берёт план места из книги")
    for ap in a.intent.approaches:
        outside = w.entities.get(ap.outside_id or root.id)
        if outside is None or outside.kind != "location":
            raise ToolError(f"подход «{ap.public_name}»: нет места {ap.outside_id}")
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    inverse: list = []
    if row is None:
        row = await layout_store.reserve_layout(ctx.session, ctx.campaign, root, a.intent)
        inverse.append({"table": "world_generation_states", "op": "delete", "id": row.id})
    elif (row.reservation or {}).get("intent") != a.intent.model_dump(mode="json"):
        raise ToolError("у места уже есть замысел комплекса: структура не перестраивается")
    storage.activate(row)
    result = {"location_id": root.id, **receipt(row.id)}
    await ctx.record("prepare_complex", target_id=root.id, payload=result, inverse=inverse, hidden=True)
    return result


class PrepareLocationArgs(BaseModel):
    location_id: str = Field(description="реальный id места каркаса с пространством")
    furnish: bool = Field(False, description="ещё и наполнить все участки обстановкой (вызовы модели — по бюджету)")


def _visited(ctx: ToolContext, place) -> bool:
    w = ctx.world
    here = {w.actor_place(h.id) for h in w.characters.values()} | {w.scene.location_id}
    return place.id in here or bool((place.state or {}).get("visited_by"))


@tool(
    "prepare_location",
    "Команда ведущего: заранее готовит место каркаса с пространством — структуру, затем геометрию всех участков и "
    "по желанию обстановку. Героям ничего не открывает и никого не перемещает. Первый вызов принимает структуру; "
    "после её готовности повторный вызов готовит участки. Возвращает квитанции и верхнюю оценку вызовов модели.",
    PrepareLocationArgs,
    ids={"location_id": "locations"},
    closes=False,
)
async def prepare_location(ctx: ToolContext, a: PrepareLocationArgs) -> dict:
    from app.core import plot as plot_mod
    from app.core.layout import plan as layout_plan
    from app.core.layout import store as layout_store
    from app.core.world_generation.service import LLM_LIMIT

    root = ctx.world.entities.get(a.location_id)
    if root is None or root.kind != "location" or root.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    inverse: list = []
    if row is None:
        if _visited(ctx, root):
            raise ToolError("отряд здесь уже был: устройство посещённого места не перестраивается")
        kind, sketch = plot_mod._index(ctx.world.plot or {}).get(
            (root.state or {}).get("plot_id") or "", (None, None)
        )
        if kind != "location" or not (sketch or {}).get("spatial"):
            raise ToolError("у места нет пространственного замысла в каркасе: используйте prepare_complex")
        row = await layout_plan.reserve_from_plan(ctx, root, sketch, inverse)
        if row is None:
            raise ToolError("это место не становится комплексом (готовое приключение или уже есть план)")
    storage.activate(row)
    refs = [row.id]
    settings = ctx.campaign.settings or {}
    furnish_calls = 0
    bp = layout_store.blueprint_of(root)
    if bp is not None:
        for area_id in layout_store.area_ids(root).values():
            area = ctx.world.entities[area_id]
            geo = await storage.find(ctx.session, ctx.campaign.id, area_id, "location_geometry")
            if geo is not None and storage.activate(geo):
                refs.append(geo.id)
            if a.furnish:
                initial = await storage.find(ctx.session, ctx.campaign.id, area_id, "location_initial")
                if initial is None:
                    initial = await storage.reserve_root(
                        ctx.session, ctx.campaign, ctx.world, area, minimal=not settings.get("scene_generation")
                    )
                    inverse.append({"table": "world_generation_states", "op": "delete", "id": initial.id})
                if storage.activate(initial):
                    refs.append(initial.id)
                    if settings.get("scene_generation_llm"):
                        furnish_calls += max(0, LLM_LIMIT - int(initial.llm_attempt_count or 0))
    structure_calls = 0
    if row.status not in ("ready", "blocked") and settings.get("location_layouts_llm"):
        structure_calls = max(0, LLM_LIMIT - int(row.llm_attempt_count or 0))
    ctx.operation_refs.update(refs)
    result = {
        "location_id": root.id,
        "structure": receipt(row.id),
        "operation_refs": refs,
        "blueprint_ready": bp is not None,
        "estimate": {"structure_calls_max": structure_calls, "furnish_calls_max": furnish_calls},
    }
    await ctx.record("prepare_location", target_id=root.id, payload=result, inverse=inverse, hidden=True)
    return result


class PreparationCostArgs(BaseModel):
    location_id: str = Field(description="реальный id места (корня комплекса или обычного)")


@tool(
    "preparation_cost",
    "Только чтение: сколько стоила подготовка места — по фазам: вызовы модели, исправления, токены (и рассуждений), "
    "цена и длительность. Ничего не запускает и не меняет.",
    PreparationCostArgs,
    ids={"location_id": "locations"},
    mutating=False,
    closes=False,
)
async def preparation_cost(ctx: ToolContext, a: PreparationCostArgs) -> dict:
    from app.core import preparation
    from app.core.campaigns import NotFound

    try:
        return await preparation.location_cost(ctx.session, ctx.campaign.id, a.location_id)
    except NotFound as e:
        raise ToolError(str(e)) from e


