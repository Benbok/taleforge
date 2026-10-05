"""Проверка персонажа ИИ-мастером (раздел 5.1)."""

from __future__ import annotations

import asyncio
import json
import logging

from app.agents.llm import LLMError
from app.agents.master.common import _world_choices
from app.agents.providers import explain
from app.core.campaigns import master_seat
from app.db.models import AgentConfig, Campaign, Event, LlmCall
from app.gateway.events import envelope
from app.tools.registry import execute, tool_specs
from app.tools.runtime import open_context

log = logging.getLogger(__name__)


class ReviewMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- проверка персонажа ИИ-мастером (раздел 5.1) ---

    async def review_character(self, cid: str, character_id: str) -> str | None:
        """Проверка героя ИИ-мастером. Если модель недоступна или так и не вынесла решения, герой остаётся
        на проверке, а причина пишется в журнал и видна игроку и владельцу: владелец может проверить сам."""
        lock = self.turn_lock(cid)
        async with lock:
            calls: list[LlmCall] = []
            error = None
            try:
                attempted, status = await self._review(cid, character_id, calls)
                if attempted and not status:
                    error = "модель не вынесла решения за три попытки"
            except asyncio.CancelledError:
                raise
            except LLMError as e:
                attempted, status, error = True, None, explain(str(e))
            except Exception as e:  # noqa: BLE001 — сбой проверки не должен теряться молча
                log.exception("проверка героя %s сорвалась", character_id)
                attempted, status, error = True, None, f"{type(e).__name__}: {e}"[:500]
            finally:
                if calls:
                    async with self.maker() as s:
                        s.add_all(calls)
                        await s.commit()
            if error:
                async with self.maker() as s:
                    failed = {"error": error}
                    s.add(Event(campaign_id=cid, tool="review_failed", target_id=character_id, payload=failed))
                    await s.commit()
                await self.bus.publish(
                    cid, envelope("character.review_failed", cid, {"character_id": character_id, "error": error}), None
                )
            return status

    async def _review(self, cid: str, character_id: str, calls: list) -> tuple[bool, str | None]:
        """ИИ-проверка героя. Сессия БД не держится во время обращения к модели: в SQLite открытая транзакция
        не даёт другим писать, и игроки получали «database is locked», пока модель думала."""
        from app.core.characters import full_view

        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            seat = master_seat(c)
            if seat.occupant_type != "agent":
                return False, None
            seat_id = seat.id
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
            ch = ctx.world.characters.get(character_id)
            if ch is None or ch.status != "submitted":
                return False, None
            sheet = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), [])
            world = _world_choices(ctx.world.catalog)
            system = await self._system_prompt(s, c, cfg, ctx)
            tools = tool_specs(ctx.world, ["review_character"])
            s.expunge(cfg)  # нужен и после закрытия сессии: провайдер, модель, настройки
        msgs = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "Игрок прислал персонажа на проверку. Правила сервер уже проверил. Оцени историю и "
                    "соответствие сеттингу и вызови review_character: одобри или верни с комментарием. "
                    "Соответствие миру проверяй по его фактам: класс и происхождение взяты из списков мира, но "
                    "история, внешность и характер не должны вводить то, чего в мире нет (чужие расы, народы, "
                    "боги, магия или земли, противоречащие лору). Возвращай только за явное противоречие и "
                    "в комментарии назови его и предложи, как поправить в духе мира; стиль и мелочи не повод.\n"
                    + world
                    + "\n"
                    "Можешь тайно связать историю героя с сюжетом через secret_link, а если есть каркас — "
                    "привязать эту связь к узлу, NPC, злодею или месту каркаса через hook_ref.\n\n"
                    + json.dumps(sheet, ensure_ascii=False, default=str)
                ),
            },
        ]
        for _ in range(3):
            reply = await self._ask(calls, cfg, cid, seat_id, None, "review", msgs, tools)
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            if not reply.tool_calls:
                msgs.append({"role": "user", "content": "Вызови review_character."})
                continue
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                ch = ctx.world.characters.get(character_id)
                if ch is None or ch.status != "submitted":
                    return False, None  # пока модель думала, героя проверил человек или игрок его отозвал
                status = None
                for call in reply.tool_calls:
                    args = {**call.arguments, "character_id": ch.id}
                    r = (
                        await execute(ctx, "review_character", args)
                        if call.name == "review_character"
                        else {"ok": False, "error": "здесь доступен только review_character"}
                    )
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(r, ensure_ascii=False, default=str),
                        }
                    )
                    if r.get("ok"):
                        status = r["result"]["status"]
                await s.commit()
                if not status:
                    continue
                if ch.seat_id:
                    full = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), ctx.world.effects)
                    await self.bus.publish(
                        cid,
                        envelope(
                            "character.reviewed",
                            cid,
                            {"character": full, "status": status, "comment": ch.review_comment},
                        ),
                        [ch.seat_id],
                    )
                return True, status
        return True, None
