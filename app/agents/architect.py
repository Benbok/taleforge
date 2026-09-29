"""Архитектор кампании: строит каркас сюжета по анкете и лору пакета (проект «Подготовка кампании», раздел 2).

Работает один раз при подготовке кампании на модели мастера (у живого мастера — на модели по умолчанию).
Каркас проверяет сервер (app/core/plot.py); ошибки возвращаются архитектору, до ATTEMPTS попыток.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.agents.llm import LLMError, model_for
from app.content.catalog import campaign_catalog
from app.core import knowledge, plot
from app.core.brief import brief_text
from app.core.campaigns import default_model_profile, master_seat
from app.db.models import AgentConfig, Campaign, CampaignPlan, CampaignSecret, ContentPack, GameSession, LlmCall
from app.gateway.events import envelope

log = logging.getLogger(__name__)

ATTEMPTS = 3
MAX_TOKENS = 12000
LORE_K = 25
OUT_TOKENS = {"oneshot": 3500, "short": 6000, "long": 9000}
FIGURES = 60  # ключевые лица мира (тег unique) в задании архитектору
PLACES = 30  # ключевые места мира (тег atlas)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def model_of(s, c: Campaign) -> tuple[str, str, str | None, float]:
    """(провайдер, модель для LiteLLM, api_base, температура): модель ИИ-мастера или модель по умолчанию."""
    seat = master_seat(c)
    if seat.occupant_type == "agent" and seat.agent_config_id:
        cfg = await s.get(AgentConfig, seat.agent_config_id)
        return cfg.provider, model_for(cfg.provider, cfg.model), (cfg.settings or {}).get("api_base"), cfg.temperature
    p = await default_model_profile(s)
    if p is not None:
        return p.provider, model_for(p.provider, p.model), p.api_base, p.temperature
    return "claude", model_for("claude", None), None, 0.8


async def started(s, cid: str) -> bool:
    n = await s.scalar(select(func.count()).select_from(GameSession).where(GameSession.campaign_id == cid))
    return bool(n)


def tags(e) -> list[str]:
    return [str(t) for t in e.data.get("tags") or []]


def unique(e) -> bool:
    """Именное лицо мира пакета (глава фракции, хозяин города), а не шаблон."""
    return "unique" in tags(e)


def length_of(c: Campaign) -> str:
    return (c.brief or {}).get("length") or "short"


async def build_input(s, c: Campaign, note: str = "", structure_id: str | None = None) -> tuple[str, str | None]:
    """Текст задания архитектору и id выбранного шаблона сюжета."""
    catalog = await campaign_catalog(s, c)
    brief = c.brief or {}
    structure = plot.pick_structure(catalog.by_kind("plot_structure"), brief, structure_id)
    if structure_id and structure is None:
        raise LookupError("шаблон сюжета не найден")
    query = " ".join(
        [brief.get("wishes") or "", c.name, structure.name if structure else "", c.public_intro or ""]
    ).strip()
    lore = [x for x in knowledge.lore_for(catalog, query or c.name, LORE_K) if x.kind != "location_template"]
    factions = [e for e in catalog.by_kind("faction")]
    lore_text = "\n".join(f"- {x.id}: {x.render()}" for x in lore)
    if factions:
        lore_text += "\nФракции:\n" + "\n".join(
            f"- {e.id}: {e.name} — {e.data.get('goal', '')}" for e in factions if e.id not in {x.id for x in lore}
        )
    creatures = catalog.by_kind("creature_template")
    npcs = [e for e in creatures if e.data.get("creature_type") == "humanoid" and not unique(e)]
    figures = []
    for e in [e for e in creatures if unique(e)][:FIGURES]:
        secret = catalog.find(str(e.data.get("secret_ref") or ""), "campaign_secret")
        figures.append(plot.figure_line(e, secret.data.get("text", "") if secret else ""))
    places = [plot.place_line(e) for e in catalog.by_kind("location_template") if "atlas" in tags(e)][:PLACES]
    secret = await s.get(CampaignSecret, c.id)
    previous = secret.plot if secret and secret.plot and secret.plot.get("title") else None
    party = sum(1 for x in c.seats if x.role == "player")
    text = plot.plan_input(
        campaign_name=c.name,
        brief_text=brief_text(brief),
        length=length_of(c),
        difficulty=c.difficulty,
        party=party,
        structure=structure,
        excluded=list((c.settings or {}).get("excluded_themes") or []),
        lore=lore_text.strip(),
        locations=catalog.by_kind("location_template"),
        npcs=npcs,
        note=note,
        previous=previous,
        figures=figures,
        places=places,
    )
    return text, structure.id if structure else None


def estimate_cost(model: str, prompt: str, length: str) -> dict:
    """Примерная стоимость генерации: вход — по длине задания, выход — по длительности кампании."""
    tokens_in = int(len(plot.SYSTEM + prompt) / 3.2) + 2500  # + схема инструмента
    tokens_out = OUT_TOKENS.get(length, 6000)
    usd = None
    try:
        import litellm

        cin, cout = litellm.cost_per_token(model=model, prompt_tokens=tokens_in, completion_tokens=tokens_out)
        usd = round(float(cin + cout), 4)
    except Exception:  # noqa: BLE001 — у локальной модели и неизвестных моделей цены нет
        usd = None
    return {"model": model, "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd}


async def set_status(s, c: Campaign, **status) -> dict:
    settings = dict(c.settings or {})
    settings["plan"] = {**(settings.get("plan") or {}), **status, "updated_at": now_iso()}
    c.settings = settings
    return settings["plan"]


async def publish(svc, cid: str, c: Campaign) -> None:
    st = c.settings or {}
    payload = {"plan": st.get("plan") or {}, "poster": st.get("poster"), "public_intro": c.public_intro}
    await svc.bus.publish(cid, envelope("campaign.plan", cid, payload), None)


async def generate(svc, cid: str, note: str = "", structure_id: str | None = None) -> str | None:
    """Строит каркас в фоне. Возвращает id версии или None при сбое (статус и ошибка — в settings.plan)."""
    try:
        async with svc.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None:
                return None
            provider, model, api_base, temperature = await model_of(s, c)
            prompt, sid = await build_input(s, c, note, structure_id)
            catalog = await campaign_catalog(s, c)
            length = length_of(c)
            excluded = list((c.settings or {}).get("excluded_themes") or [])
            level_cap = int((await _level_cap(s, c)) or 20)
            seat_id = master_seat(c).id
            await s.rollback()  # не держим транзакцию, пока модель думает
        msgs = [{"role": "system", "content": plot.SYSTEM}, {"role": "user", "content": prompt}]
        plan, errors, calls = None, ["модель не сдала каркас"], []
        for _ in range(ATTEMPTS):
            call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="plan", model=model)
            calls.append(call)
            try:
                reply = await svc.llm.complete(
                    msgs,
                    model=model,
                    tools=[plot.tool_spec()],
                    max_tokens=MAX_TOKENS,
                    temperature=min(max(temperature, 0.7), 1.0),
                    api_base=api_base,
                )
            except LLMError as e:
                call.error = str(e)[:2000]
                errors = [f"модель недоступна: {e}"]
                break
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
            tc = next((t for t in reply.tool_calls if t.name == plot.TOOL), None)
            if tc is None:
                errors = ["модель не вызвала submit_campaign_plan"]
                msgs.append(reply.message or {"role": "assistant", "content": reply.text})
                msgs.append({"role": "user", "content": "Сдай каркас вызовом submit_campaign_plan."})
                call.error = errors[0]
                continue
            plan, errors = plot.check(
                tc.arguments, length=length, catalog=catalog, excluded=excluded, level_cap=level_cap
            )
            if plan is not None:
                break
            call.error = "; ".join(errors)[:2000]
            msgs.append(_assistant(reply, tc))
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(
                        {"ok": False, "errors": errors, "hint": "исправь и сдай каркас целиком ещё раз"},
                        ensure_ascii=False,
                    ),
                }
            )
        async with svc.maker() as s:
            for call in calls:
                s.add(call)
            c = await s.get(Campaign, cid)
            if c is None:
                return None
            version_id = None
            if plan is not None:
                prev = await s.scalar(select(func.max(CampaignPlan.version)).where(CampaignPlan.campaign_id == cid))
                version = int(prev or 0) + 1
                plan["structure_id"] = sid or plan.get("structure_id")
                plan["version"] = version
                row = CampaignPlan(campaign_id=cid, version=version, content=plan, note=note or "")
                s.add(row)
                secret = await s.get(CampaignSecret, cid)
                if secret is None:
                    secret = CampaignSecret(campaign_id=cid)
                    s.add(secret)
                for key in ("character_links", "hooks"):  # связи героев переживают новый вариант каркаса
                    if (secret.plot or {}).get(key):
                        plan[key] = secret.plot[key]
                if plan.get("hooks"):
                    targets = set(plot.hook_targets(plan))
                    plan["hooks"] = {k: h for k, h in plan["hooks"].items() if h.get("ref") in targets}
                secret.plot = plan
                settings = dict(c.settings or {})
                settings["poster"] = plot.poster(plan)
                if not (c.public_intro or "").strip() or settings.get("intro_from_plan"):
                    c.public_intro = plan["public_intro"]
                    settings["intro_from_plan"] = True
                c.settings = settings
                await set_status(s, c, status="ready", version=version, error=None)
                await s.flush()
                version_id = row.id
            else:
                await set_status(s, c, status="failed", error="; ".join(errors)[:1000])
            await s.commit()
            await publish(svc, cid, c)
            return version_id
    except Exception as e:  # noqa: BLE001 — сбой генерации не должен ронять сервер
        log.exception("каркас кампании %s не построен", cid)
        async with svc.maker() as s:
            c = await s.get(Campaign, cid)
            if c is not None:
                await set_status(s, c, status="failed", error=f"внутренняя ошибка: {e}"[:500])
                await s.commit()
                await publish(svc, cid, c)
        return None


def _assistant(reply, tc) -> dict:
    """Ответ модели с вызовом инструмента — чтобы вернуть ей ошибки сервера сообщением роли tool."""
    return reply.message or {
        "role": "assistant",
        "content": reply.text,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.raw_arguments or json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
        ],
    }


async def _level_cap(s, c: Campaign) -> int | None:
    if not c.pack_id:
        return None
    pack = await s.get(ContentPack, (c.pack_id, c.pack_version))
    return (pack.manifest or {}).get("level_cap") if pack else None


async def revise(svc, cid: str) -> str | None:
    """Пересмотр оставшихся актов после закрытия акта (раздел 3). Только у ИИ-мастера и если владелец не отключил
    (``settings.replan = false``). Сбой не трогает каркас: игра идёт по прежнему плану."""
    try:
        async with svc.maker() as s:
            c = await s.get(Campaign, cid)
            secret = await s.get(CampaignSecret, cid)
            if c is None or secret is None or not plot.has_plan(secret.plot):
                return None
            seat = master_seat(c)
            if seat.occupant_type != "agent" or (c.settings or {}).get("replan") is False:
                return None
            if not plot.open_acts(secret.plot):
                return None
            provider, model, api_base, temperature = await model_of(s, c)
            catalog = await campaign_catalog(s, c)
            length = length_of(c)
            excluded = list((c.settings or {}).get("excluded_themes") or [])
            level_cap = int((await _level_cap(s, c)) or 20)
            prompt = plot.revise_input(secret.plot, brief_text=brief_text(c.brief or {}), excluded=excluded)
            await set_status(s, c, revision={"status": "revising"})
            await s.commit()
            await publish(svc, cid, c)
        msgs = [{"role": "system", "content": plot.REVISE_SYSTEM}, {"role": "user", "content": prompt}]
        revision, errors, calls = None, ["модель не сдала пересмотр"], []
        for _ in range(ATTEMPTS):
            call = LlmCall(campaign_id=cid, seat_id=seat.id, turn_id=None, purpose="replan", model=model)
            calls.append(call)
            try:
                reply = await svc.llm.complete(
                    msgs,
                    model=model,
                    tools=[plot.revision_spec()],
                    max_tokens=MAX_TOKENS,
                    temperature=min(max(temperature, 0.7), 1.0),
                    api_base=api_base,
                )
            except LLMError as e:
                call.error = str(e)[:2000]
                errors = [f"модель недоступна: {e}"]
                break
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
            tc = next((t for t in reply.tool_calls if t.name == plot.REVISE_TOOL), None)
            if tc is None:
                errors = ["модель не вызвала submit_plan_revision"]
                call.error = errors[0]
                msgs.append(reply.message or {"role": "assistant", "content": reply.text})
                msgs.append({"role": "user", "content": "Сдай пересмотр вызовом submit_plan_revision."})
                continue
            async with svc.maker() as s:
                current = (await s.get(CampaignSecret, cid)).plot
            merged, errors = plot.merge_revision(current, tc.arguments)
            if not errors:
                merged, errors = plot.check(
                    merged, length=length, catalog=catalog, excluded=excluded, level_cap=level_cap, keep_state=True
                )
            if not errors:
                revision = tc.arguments
                break
            call.error = "; ".join(errors)[:2000]
            msgs.append(_assistant(reply, tc))
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(
                        {"ok": False, "errors": errors, "hint": "исправь и сдай пересмотр целиком ещё раз"},
                        ensure_ascii=False,
                    ),
                }
            )
        async with svc.maker() as s:
            s.add_all(calls)
            c = await s.get(Campaign, cid)
            secret = await s.get(CampaignSecret, cid)
            version_id = None
            if revision is not None:
                # накладываем на свежий каркас: пока модель думала, игра могла уйти вперёд
                merged, errors = plot.merge_revision(secret.plot, revision)
                if not errors:
                    merged, errors = plot.check(
                        merged, length=length, catalog=catalog, excluded=excluded, level_cap=level_cap, keep_state=True
                    )
            if revision is not None and not errors:
                prev = await s.scalar(select(func.max(CampaignPlan.version)).where(CampaignPlan.campaign_id == cid))
                version = int(prev or 0) + 1
                merged["version"] = version
                summary = str(revision.get("summary") or "")[:600]
                row = CampaignPlan(campaign_id=cid, version=version, content=merged, note=f"пересмотр: {summary}")
                s.add(row)
                secret.plot = merged
                # итог пересмотра — только в версии каркаса: настройки кампании видят и игроки
                await set_status(s, c, version=version, revision={"status": "ready"})
                await s.flush()
                version_id = row.id
            else:
                log.warning("пересмотр каркаса кампании %s не принят: %s", cid, "; ".join(errors))
                await set_status(s, c, revision={"status": "failed"})
            await s.commit()
            await publish(svc, cid, c)
            return version_id
    except Exception:  # noqa: BLE001 — сбой пересмотра не должен ронять сервер
        log.exception("пересмотр каркаса кампании %s не удался", cid)
        async with svc.maker() as s:
            c = await s.get(Campaign, cid)
            if c is not None:
                await set_status(s, c, revision={"status": "failed"})
                await s.commit()
                await publish(svc, cid, c)
        return None
